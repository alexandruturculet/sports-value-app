"""Sports betting section — V7 Edge Engine predictions, lineups, tickets.

Performance model:
  • League data (standings/matches/scorers) — one cached parallel batch,
    capped at FOOTBALL_DATA_WORKERS (free tier: 10 req/min).
  • Today's match context (lineups + injuries) — one cached parallel batch
    over ESPN/API-Football, ESPN_WORKERS wide.
  • Upcoming match context — fully lazy: fetched per match inside an
    st.fragment when the user clicks the load button.
  • st.cache_data only on main-thread orchestrators; worker threads call
    raw, requests-only service helpers.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import streamlit as st

from config import (
    ALL_LEAGUES, DEFAULT_LEAGUES, DISPLAY_TZ, ESPN_WORKERS,
    FOOTBALL_DATA_WORKERS, LEAGUE_CODES, MAX_MATCHES, ODDS_KEYS,
    REFRESH_COOLDOWN_SECONDS, TTL_CONTEXT_BATCH, TTL_MATCHES, TTL_MOTIVATION,
    TTL_ODDS,
)
from models.data_normalizer import normalize_league, register_team_stats
from models.team_strength_model import get_team_strength
from models.v7.match_preview import generate_preview
from models.v7.motivation_engine import analyze_motivation
from models.v7.prediction_engine import apply_motivation_adjustment, generate_prediction
from models.v7.team_context import set_league_standings
from models.v7.ticket_engine import build_ticket
from models.v7.ticket_eval import pick_won
from services.api_football import get_fixture_injuries, get_team_season_stats, is_api_rate_limited
from services.espn_api import get_espn_injuries, get_espn_last_lineup, get_espn_lineups
from services.football_api import (
    fetch_h2h, fetch_league_matches, fetch_league_scorers, fetch_league_standings,
    fetch_live_matches, fetch_match_score, top_scorer_from_list,
)
from services.odds_api import fetch_league_odds, find_event_odds, odds_requests_remaining
from services.player_images import get_player_image_url
from services.supabase_client import (
    get_all_tickets, get_motivations_bulk, log_predictions, save_motivation,
    save_ticket, update_ticket_picks_and_result, update_ticket_result,
)
from ui.components import (
    LOSS, PRED_STYLE, TEXT, TEXT_DIM, TEXT_FAINT, WARN, WIN,
    bar_row, card_html, conf_color, confidence_bar, count_up,
    pill, pred_pill, section_header,
)

logger = logging.getLogger(__name__)

_LINEUP_EMPTY = {"home": {"lineup": [], "bench": []}, "away": {"lineup": [], "bench": []}}
_EMPTY_CONTEXT = {"lineup": _LINEUP_EMPTY, "probable": False, "injuries": {"home": [], "away": []}}


# ══════════════════════════════════════════════════════════════════════════════
# Data loading — parallel, cached orchestrators
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=TTL_MATCHES, show_spinner=False)
def load_league_data(leagues: tuple) -> dict:
    """Standings + matches + scorers for all selected leagues, fetched in parallel."""
    today = datetime.now(timezone.utc).date().isoformat()
    next_week = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
    codes = {lg: LEAGUE_CODES[lg] for lg in leagues if lg in LEAGUE_CODES}

    standings: dict = {}
    matches: list = []
    scorers: dict = {}
    with ThreadPoolExecutor(max_workers=FOOTBALL_DATA_WORKERS) as ex:
        stand_f = {lg: ex.submit(fetch_league_standings, c) for lg, c in codes.items()}
        match_f = {lg: ex.submit(fetch_league_matches, c, today, next_week) for lg, c in codes.items()}
        scorer_f = {c: ex.submit(fetch_league_scorers, c) for c in set(codes.values())}

        for lg, fut in stand_f.items():
            table = fut.result()
            if table:
                standings[lg] = table
        for fut in match_f.values():
            matches.extend(fut.result())
        for c, fut in scorer_f.items():
            scorers[c] = fut.result()

    return {"standings": standings, "matches": matches, "scorers": scorers}


@st.cache_data(ttl=3600, show_spinner=False)
def cached_prediction(home: str, away: str, league: str, fixture_id):
    return generate_prediction(home, away, league, fixture_id)


@st.cache_data(ttl=TTL_MOTIVATION, show_spinner=False)
def load_motivations(fixture_ids: tuple) -> dict:
    """All saved motivation analyses in ONE Supabase query."""
    return get_motivations_bulk([int(f) for f in fixture_ids if f])


@st.cache_data(ttl=TTL_ODDS, show_spinner=False)
def load_odds(league_codes: tuple) -> dict:
    """Real bookmaker odds per competition, fetched in parallel.
    The Odds API free tier = 500 credits/month → 30-min cache."""
    keys = {c: ODDS_KEYS[c] for c in league_codes if c in ODDS_KEYS}
    out: dict = {}
    with ThreadPoolExecutor(max_workers=FOOTBALL_DATA_WORKERS) as ex:
        futures = {ex.submit(fetch_league_odds, k): c for c, k in keys.items()}
        for fut in as_completed(futures):
            code = futures[fut]
            try:
                out[code] = fut.result()
            except Exception as e:
                logger.warning("Odds fetch failed for %s: %s", code, e)
                out[code] = []
    return out


def _real_edge(conf: float, odds: float) -> tuple[float, float]:
    """(EV, Kelly fraction) against a real decimal price. p = confidence/100."""
    p = conf / 100
    ev = p * odds - 1
    kelly = max(0.0, (p * odds - 1) / (odds - 1)) if odds > 1 else 0.0
    return round(ev, 3), round(kelly, 3)


def _market_prior(market_odds: dict) -> tuple | None:
    """Derive (market, confidence, probs) from de-vigged bookmaker prices.

    Used when the standings carry no signal yet (e.g. World Cup group stage
    before matchday 1: every team is on 0 played / 0 points, so the model
    outputs an identical 'X · 45%' for every fixture).
    """
    try:
        o1 = market_odds.get("1", (None,))[0]
        ox = market_odds.get("X", (None,))[0]
        o2 = market_odds.get("2", (None,))[0]
        if not (o1 and ox and o2):
            return None
        inv = [1 / o1, 1 / ox, 1 / o2]
        s = sum(inv)
        p1, px, p2 = (v / s for v in inv)

        p_over = None
        over = market_odds.get("Over 2.5")
        under = market_odds.get("Under 2.5")
        if over and under:
            io, iu = 1 / over[0], 1 / under[0]
            p_over = io / (io + iu)

        if p1 >= 0.55:
            pick, p = "1", p1
        elif p2 >= 0.55:
            pick, p = "2", p2
        elif p_over is not None and p_over >= 0.58:
            pick, p = "Over 2.5", p_over
        elif p_over is not None and (1 - p_over) >= 0.58:
            pick, p = "Under 2.5", 1 - p_over
        elif p1 >= p2:
            pick, p = "1X", p1 + px
        else:
            pick, p = "X2", p2 + px

        conf = round(max(38.0, min(92.0, p * 100)), 1)
        probs = {"p1": round(p1, 3), "px": round(px, 3), "p2": round(p2, 3),
                 "p_over_2_5": round(p_over, 3) if p_over is not None else None}
        return pick, conf, probs
    except (TypeError, ZeroDivisionError):
        return None


def _apply_market_priors(results: list, odds_by_code: dict, standings: dict) -> None:
    """For fixtures where neither team has played yet, replace the data-less
    model output with a market-derived prediction."""
    played_by_league: dict = {}
    for lg, table in standings.items():
        played_by_league[lg] = {
            t["team"]["name"]: t.get("playedGames", 0) or 0 for t in table
        }

    for r in results:
        played = played_by_league.get(r["league"], {})
        if played.get(r["home"], 0) > 0 or played.get(r["away"], 0) > 0:
            continue  # the model has real data — keep it

        events = odds_by_code.get(r["competition_code"], [])
        market_odds = find_event_odds(events, r["home"], r["away"]) if events else {}
        r["market_odds"] = market_odds
        prior = _market_prior(market_odds)
        if not prior:
            continue
        pick, conf, probs = prior
        r["prediction"] = pick
        r["confidence"] = conf
        r["reason"] = "Market prior — derived from bookmaker odds (no matches played yet)"
        r["breakdown"]["market"] = pick
        r["breakdown"]["odds_prior"] = probs


def _attach_real_odds(results: list, odds_by_code: dict) -> list:
    """Replace the synthetic EV with bookmaker-priced EV wherever odds exist.

    edge.ev/kelly become the real values (used for sorting, value flag,
    ticket building); the model-only numbers are kept as edge.model_ev/kelly.
    """
    for r in results:
        market_odds = r.get("market_odds")
        if market_odds is None:
            events = odds_by_code.get(r["competition_code"], [])
            market_odds = find_event_odds(events, r["home"], r["away"]) if events else {}
            r["market_odds"] = market_odds
        edge = r["edge"]
        edge["model_ev"] = edge.get("ev", 0)
        edge["model_kelly"] = edge.get("kelly", 0)
        best = market_odds.get(r["prediction"])
        if best:
            odds, bookie = best
            ev, kelly = _real_edge(r["confidence"], odds)
            edge.update({
                "ev": ev, "kelly": kelly, "odds": odds,
                "bookmaker": bookie, "value_bet": ev > 0,
            })
    return sorted(results, key=lambda x: x.get("edge", {}).get("ev", 0), reverse=True)


def _fetch_one_context(home: str, away: str, code: str, date_str: str,
                       want_lineups: bool = True) -> dict:
    """Lineups + injuries for one match. Raw — safe inside worker threads."""
    lineup, probable = _LINEUP_EMPTY, False
    if want_lineups:
        confirmed = get_espn_lineups(home, away, code, date_str)
        if confirmed["home"]["lineup"] and confirmed["away"]["lineup"]:
            lineup, probable = confirmed, False
        else:
            home_last = get_espn_last_lineup(home, code)
            away_last = get_espn_last_lineup(away, code)
            lineup = {"home": home_last, "away": away_last}
            probable = bool(home_last["lineup"] or away_last["lineup"])

    injuries = get_fixture_injuries(home, away, date_str, code)
    if not injuries["home"] and not injuries["away"]:
        injuries = get_espn_injuries(home, away, code, date_str)

    return {"lineup": lineup, "probable": probable, "injuries": injuries}


@st.cache_data(ttl=TTL_CONTEXT_BATCH, show_spinner=False)
def load_context_batch(match_keys: tuple) -> dict:
    """Parallel lineup+injury fetch for today's matches (was the 5-minute serial loop)."""
    out: dict = {}
    if not match_keys:
        return out
    with ThreadPoolExecutor(max_workers=ESPN_WORKERS) as ex:
        futures = {
            ex.submit(_fetch_one_context, home, away, code, date_str): mid
            for (mid, home, away, code, date_str) in match_keys
        }
        for fut in as_completed(futures):
            mid = futures[fut]
            try:
                out[mid] = fut.result()
            except Exception as e:
                logger.warning("Context fetch failed for %s: %s", mid, e)
                out[mid] = _EMPTY_CONTEXT
    return out


def _match_id(r: dict) -> str:
    return str(r.get("fixture_id") or r["match"])


def _build_results(matches: list, standings: dict) -> list:
    """Run the prediction engine over fetched matches (CPU only — no HTTP)."""
    results = []
    processed = 0
    for m in matches:
        if processed >= MAX_MATCHES:
            break
        processed += 1

        match_dt = (
            datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
            .astimezone(DISPLAY_TZ)
        )
        home_name = m["homeTeam"]["name"]
        away_name = m["awayTeam"]["name"]
        league = normalize_league(m["competition"]["name"])
        competition_code = m["competition"].get("code", "PL")
        fixture_id = m.get("id")

        league_data = standings.get(league) or standings.get(m["competition"]["name"], [])
        home = get_team_strength(league_data, home_name)
        away = get_team_strength(league_data, away_name)

        register_team_stats(home_name, league, home)
        register_team_stats(away_name, league, away)

        try:
            prediction, reason, breakdown, edge, confidence = cached_prediction(
                home_name, away_name, league, fixture_id
            )
        except Exception:
            continue

        results.append({
            "home": home_name,
            "away": away_name,
            "match": f"{home_name} vs {away_name}",
            "kickoff": match_dt.strftime("%d-%m-%Y %H:%M") + " (Romania)",
            "kickoff_date": match_dt.date(),
            "kickoff_date_str": match_dt.date().isoformat(),
            "competition_code": competition_code,
            "league": league,
            "fixture_id": fixture_id,
            "prediction": prediction,
            "confidence": confidence,
            "reason": reason,
            "breakdown": breakdown,
            "edge": edge,
            "home_crest": m["homeTeam"].get("crest", ""),
            "away_crest": m["awayTeam"].get("crest", ""),
        })

    return sorted(results, key=lambda x: x.get("edge", {}).get("ev", 0), reverse=True)


# ══════════════════════════════════════════════════════════════════════════════
# Render helpers
# ══════════════════════════════════════════════════════════════════════════════

# Granular position → pitch layer (0=GK … 5=FWD); sub-MID rows enable 4-2-3-1 display
_POS_LAYER = {
    "Goalkeeper": 0, "Keeper": 0,
    "Centre-Back": 1, "Right-Back": 1, "Left-Back": 1, "Defender": 1,
    "Defensive Midfield": 2,
    "Central Midfield": 3, "Right Midfield": 3, "Left Midfield": 3, "Midfielder": 3,
    "Attacking Midfield": 4,
    "Centre-Forward": 5, "Left Winger": 5, "Right Winger": 5,
    "Forward": 5, "Attacker": 5, "Winger": 5, "Striker": 5,
}


def _group_layers(lineup: list) -> dict:
    layers: dict = {i: [] for i in range(6)}
    for p in lineup:
        layers[_POS_LAYER.get(p.get("position", ""), 3)].append(p)
    return layers


def _formation_str(layers: dict) -> str:
    counts = [len(layers[i]) for i in range(1, 6) if layers[i]]
    if len(counts) < 2:
        return ""
    def_count = len(layers.get(1, []))
    fwd_count = len(layers.get(5, []))
    if not (2 <= def_count <= 5 and 1 <= fwd_count <= 4):
        return ""
    return "-".join(str(c) for c in counts)


def _short_name(name: str) -> str:
    parts = name.split()
    return parts[-1][:12] if len(parts) > 1 else name[:12]


def _logo_img(url: str, size: int = 20) -> str:
    if not url:
        return ""
    return (
        f'<img src="{url}" style="width:{size}px;height:{size}px;'
        f'object-fit:contain;vertical-align:middle;flex-shrink:0;">'
    )


def _player_dot(p: dict, bg: str) -> str:
    num = str(p.get("shirtNumber", "")) or "?"
    name = _short_name(p.get("name", ""))
    return (
        '<div style="display:flex;flex-direction:column;align-items:center;margin:0 2px 4px;">'
        f'<div style="background:{bg};color:#0a0f0a;border-radius:50%;width:28px;height:28px;'
        f'display:flex;align-items:center;justify-content:center;font-weight:700;font-size:10px;'
        f'box-shadow:0 0 8px rgba(255,255,255,0.25),0 2px 5px rgba(0,0,0,0.5);">{num}</div>'
        f'<span style="color:#fff;font-size:7.5px;text-align:center;width:34px;'
        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'
        f'text-shadow:0 1px 2px rgba(0,0,0,0.9);margin-top:2px;">{name}</span>'
        '</div>'
    )


def _pos_row(players: list, bg: str) -> str:
    if not players:
        return ""
    dots = "".join(_player_dot(p, bg) for p in players)
    return (
        f'<div style="display:flex;justify-content:space-evenly;align-items:flex-start;'
        f'padding:5px 6px;">{dots}</div>'
    )


def _render_pitch(home_name: str, home_xi: list, away_name: str, away_xi: list, probable: bool,
                  home_crest: str = "", away_crest: str = "") -> None:
    hl = _group_layers(home_xi)
    al = _group_layers(away_xi)

    label = "Probable XI — based on last match" if probable else "Confirmed lineup"
    h_form = _formation_str(hl)
    a_form = _formation_str(al)

    away_logo = _logo_img(away_crest, 18)
    if away_xi:
        # Render layers top-to-bottom: GK(0) → DEF(1) → DM(2) → CM(3) → AM(4) → FWD(5)
        away_rows = "".join(_pos_row(al[i], "#ffd080") for i in range(6) if al[i])
        a_header = (
            f'<div style="font-size:11px;color:#ffd080;font-weight:600;padding:2px 10px 3px;'
            f'display:flex;align-items:center;gap:5px;">'
            f'{away_logo}{away_name}'
            + (f'<span style="color:rgba(255,255,255,0.38);font-weight:400;font-size:10px;'
               f'margin-left:4px;">{a_form}</span>' if a_form else "")
            + '</div>'
        )
    else:
        away_rows = (
            '<div style="display:flex;align-items:center;justify-content:center;padding:18px;'
            'color:rgba(255,255,255,0.35);font-size:11px;">Lineup not yet announced</div>'
        )
        a_header = (
            f'<div style="font-size:11px;color:#ffd080;font-weight:600;padding:2px 10px 3px;'
            f'display:flex;align-items:center;gap:5px;">{away_logo}{away_name}</div>'
        )

    home_logo = _logo_img(home_crest, 18)
    if home_xi:
        # Render layers bottom-to-top: FWD(5) → AM(4) → CM(3) → DM(2) → DEF(1) → GK(0)
        home_rows = "".join(_pos_row(hl[i], "#e8e8e8") for i in range(5, -1, -1) if hl[i])
        h_footer = (
            f'<div style="font-size:11px;color:#eee;font-weight:600;text-align:right;padding:3px 10px 2px;'
            f'display:flex;align-items:center;justify-content:flex-end;gap:5px;">'
            + (f'<span style="color:rgba(255,255,255,0.38);font-weight:400;font-size:10px;">{h_form}</span>'
               if h_form else "")
            + f'{home_name}{home_logo}</div>'
        )
    else:
        home_rows = (
            '<div style="display:flex;align-items:center;justify-content:center;padding:18px;'
            'color:rgba(255,255,255,0.35);font-size:11px;">Lineup not yet announced</div>'
        )
        h_footer = (
            f'<div style="font-size:11px;color:#eee;font-weight:600;text-align:right;padding:3px 10px 2px;'
            f'display:flex;align-items:center;justify-content:flex-end;gap:5px;">'
            f'{home_name}{home_logo}</div>'
        )

    center_line = (
        '<div style="display:flex;align-items:center;margin:4px 0;">'
        '<div style="flex:1;height:1px;background:rgba(255,255,255,0.2);"></div>'
        '<div style="margin:0 8px;width:30px;height:30px;border-radius:50%;'
        'border:1px solid rgba(255,255,255,0.2);flex-shrink:0;"></div>'
        '<div style="flex:1;height:1px;background:rgba(255,255,255,0.2);"></div>'
        '</div>'
    )

    html = (
        '<div style="width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 auto 8px;">'
        '<div style="min-width:280px;max-width:500px;margin:0 auto;'
        'background:linear-gradient(180deg,rgba(20,70,35,0.9) 0%,rgba(10,40,22,0.95) 100%);'
        'backdrop-filter:blur(10px);'
        'border-radius:12px;padding:8px 2px;font-family:Inter,\'Segoe UI\',sans-serif;'
        'border:1px solid rgba(52,211,153,0.18);box-shadow:0 0 24px rgba(52,211,153,0.07) inset;">'
        f'<div style="text-align:center;font-size:10px;color:rgba(255,255,255,0.45);margin-bottom:4px;">{label}</div>'
        f'{a_header}{away_rows}'
        f'{center_line}'
        f'{home_rows}{h_footer}'
        '</div></div>'
    )
    st.markdown(html, unsafe_allow_html=True)


_MOTIVATION_BADGE = {
    "HIGH":   ("rgba(52,211,153,0.12)", WIN),
    "MEDIUM": ("rgba(251,191,36,0.12)", WARN),
    "LOW":    ("rgba(248,113,113,0.12)", LOSS),
}


def _motivation_badge(level: str) -> str:
    bg, fg = _MOTIVATION_BADGE.get(level, _MOTIVATION_BADGE["MEDIUM"])
    return pill(level, bg, fg)


def _render_motivation_section(r: dict, motivation: dict | None, standings: dict,
                               base_conf: float, conf: float, adjustment: float) -> None:
    fixture_id = r.get("fixture_id")
    if motivation:
        home_lvl = motivation.get("home_motivation", "MEDIUM")
        away_lvl = motivation.get("away_motivation", "MEDIUM")
        home_factors = motivation.get("home_factors") or []
        away_factors = motivation.get("away_factors") or []
        summary = motivation.get("summary", "")
        home_list = "".join(f'<li style="font-size:11px;color:#aaa;">{f}</li>' for f in home_factors[:3])
        away_list = "".join(f'<li style="font-size:11px;color:#aaa;">{f}</li>' for f in away_factors[:3])
        if adjustment > 0:
            adj_str = f'<span style="color:{WIN};font-weight:700;">+{adjustment:.1f}</span>'
        elif adjustment < 0:
            adj_str = f'<span style="color:{LOSS};font-weight:700;">{adjustment:.1f}</span>'
        else:
            adj_str = '<span style="color:#888;font-weight:700;">0</span>'
        inner = (
            f'<div style="font-size:10px;color:{TEXT_FAINT};text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">🧠 Motivation</div>'
            '<div style="display:flex;gap:16px;margin-bottom:8px;">'
            f'<div style="flex:1;"><div style="font-size:12px;font-weight:600;margin-bottom:4px;">{r["home"]} &nbsp;{_motivation_badge(home_lvl)}</div>'
            f'<ul style="margin:4px 0 0 16px;padding:0;">{home_list}</ul></div>'
            f'<div style="flex:1;"><div style="font-size:12px;font-weight:600;margin-bottom:4px;">{r["away"]} &nbsp;{_motivation_badge(away_lvl)}</div>'
            f'<ul style="margin:4px 0 0 16px;padding:0;">{away_list}</ul></div>'
            '</div>'
            f'<div style="font-size:11px;color:#ccc;font-style:italic;margin-bottom:6px;">{summary}</div>'
            f'<div style="font-size:11px;color:#888;">Confidence: {base_conf}% → <strong>{conf}%</strong> · motivation {adj_str}</div>'
        )
        st.markdown(card_html(inner, padding="10px 14px"), unsafe_allow_html=True)
        if fixture_id and st.button("↻ Re-analyze", key=f"mot_reanalyze_{fixture_id}", help="Re-run with latest standings"):
            league = r.get("league", "")
            league_standings = standings.get(league, []) if league else []
            analysis = analyze_motivation(r["home"], r["away"], league, league_standings)
            if save_motivation(int(fixture_id), r["home"], r["away"], analysis):
                load_motivations.clear()
            st.session_state[f"_mot_{fixture_id}"] = analysis
            st.rerun()
        return

    if not fixture_id:
        return

    if st.button("🧠 Analyze motivation", key=f"mot_btn_{fixture_id}"):
        league = r.get("league", "")
        league_standings = standings.get(league, []) if league else []
        analysis = analyze_motivation(r["home"], r["away"], league, league_standings)
        if save_motivation(int(fixture_id), r["home"], r["away"], analysis):
            load_motivations.clear()
        else:
            st.session_state[f"_mot_{fixture_id}"] = analysis
        st.rerun()


def _render_context_content(r: dict, ctx: dict) -> None:
    """Pitch + injuries, given an already-fetched context."""
    lineup_data = ctx["lineup"]
    probable = ctx["probable"]
    injuries = ctx["injuries"]
    home_xi = lineup_data["home"]["lineup"]
    away_xi = lineup_data["away"]["lineup"]

    if home_xi or away_xi:
        _render_pitch(r["home"], home_xi, r["away"], away_xi, probable,
                      r.get("home_crest", ""), r.get("away_crest", ""))
    else:
        xi_l, xi_r = st.columns(2)
        xi_l.caption(f"{r['home']} — Lineup not yet announced")
        xi_r.caption(f"{r['away']} — Lineup not yet announced")

    home_inj = injuries.get("home", [])
    away_inj = injuries.get("away", [])
    if home_inj or away_inj:
        abs_l, abs_r = st.columns(2)
        with abs_l:
            if home_inj:
                st.markdown(f"**Absents — {r['home']}**")
                for inj in home_inj:
                    reason = inj.get("reason") or inj.get("type") or ""
                    st.write(f"❌ {inj['name']}" + (f" — *{reason}*" if reason else ""))
        with abs_r:
            if away_inj:
                st.markdown(f"**Absents — {r['away']}**")
                for inj in away_inj:
                    reason = inj.get("reason") or inj.get("type") or ""
                    st.write(f"❌ {inj['name']}" + (f" — *{reason}*" if reason else ""))
    else:
        st.caption("No injury data found. Reports are typically available 24–48 h before kickoff via API-Football; ESPN does not publish structured soccer injury lists.")


@st.fragment
def _context_section(r: dict, preloaded: dict | None) -> None:
    """Lazy lineups & injuries — button click reruns only this fragment."""
    mid = _match_id(r)
    ctx = preloaded or st.session_state.get(f"_ctx_{mid}")
    if ctx is None:
        if st.button("📋 Load lineups & injuries", key=f"ctx_btn_{mid}"):
            with st.spinner("Loading lineups & injuries…"):
                ctx = _fetch_one_context(
                    r["home"], r["away"], r.get("competition_code", "PL"),
                    r.get("kickoff_date_str", ""),
                )
            st.session_state[f"_ctx_{mid}"] = ctx
        else:
            st.caption("Lineups & injuries load on demand.")
            return
    _render_context_content(r, ctx)


@st.fragment
def _h2h_section(r: dict) -> None:
    """Head-to-head history on demand — one football-data request per click."""
    fixture_id = r.get("fixture_id")
    if not fixture_id:
        return
    key = f"_h2h_{fixture_id}"
    if key not in st.session_state:
        if st.button("⚔ Head-to-head", key=f"h2h_btn_{fixture_id}"):
            with st.spinner("Loading H2H…"):
                st.session_state[key] = fetch_h2h(int(fixture_id))
        else:
            return
    h2h = st.session_state[key]
    if not h2h:
        st.caption("No head-to-head history available.")
        return
    rows = ""
    for m in h2h:
        hg, ag = m["home_goals"], m["away_goals"]
        if hg is None or ag is None:
            continue
        # color from the perspective of the current home team
        if (m["home"] == r["home"] and hg > ag) or (m["away"] == r["home"] and ag > hg):
            res_col = WIN
        elif hg == ag:
            res_col = WARN
        else:
            res_col = LOSS
        rows += (
            f'<div style="display:flex;align-items:center;gap:10px;padding:5px 0;'
            f'border-bottom:1px solid rgba(255,255,255,0.05);">'
            f'<span style="font-size:10px;color:{TEXT_FAINT};width:74px;">{m["date"]}</span>'
            f'<span style="font-size:12px;flex:1;text-align:right;">{m["home"]}</span>'
            f'<span class="sv-mono" style="font-size:13px;font-weight:800;color:{res_col};padding:0 8px;">{hg}–{ag}</span>'
            f'<span style="font-size:12px;flex:1;">{m["away"]}</span>'
            f'<span style="font-size:9px;color:{TEXT_FAINT};">{m["competition"]}</span>'
            f'</div>'
        )
    if rows:
        st.markdown(
            f'<div style="font-size:10px;color:{TEXT_FAINT};text-transform:uppercase;'
            f'letter-spacing:0.5px;margin-bottom:4px;">⚔ Last meetings</div>{rows}',
            unsafe_allow_html=True,
        )


@st.fragment
def _season_stats_section(r: dict) -> None:
    """On-demand season stats — fragment-scoped, no full-page rerun."""
    mid = _match_id(r)
    stats_key = f"_teamstats_{mid}"
    if stats_key not in st.session_state:
        if st.button("📊 Load season stats", key=f"load_stats_{mid}"):
            with st.spinner("Loading season stats…"):
                code = r.get("competition_code", "PL")
                st.session_state[stats_key] = {
                    "home": get_team_season_stats(r["home"], code),
                    "away": get_team_season_stats(r["away"], code),
                }
        else:
            return
    sd = st.session_state[stats_key]
    hs, as_ = sd["home"], sd["away"]
    if not hs and not as_:
        if is_api_rate_limited():
            st.warning("API-Football daily limit reached (100 req/day). Try again tomorrow.")
        else:
            st.caption("No stats available — team not found in API-Football for this league.")
        if st.button("↩ Retry", key=f"retry_stats_{mid}"):
            del st.session_state[stats_key]
            st.rerun(scope="fragment")
        return
    played = hs.get("played") or as_.get("played") or "?"
    bars = f'<div style="padding:4px 0;"><div style="font-size:10px;color:{TEXT_FAINT};margin-bottom:10px;">Season averages · {played} games</div>'
    hy, ay = hs.get("avg_yellow") or 0, as_.get("avg_yellow") or 0
    hr, ar = hs.get("avg_red") or 0, as_.get("avg_red") or 0
    hc, ac = hs.get("avg_corners_ft") or 0, as_.get("avg_corners_ft") or 0
    if hy or ay:
        bars += bar_row("🟨 Yellow cards / game", r["home"], hy, r["away"], ay, WARN, WARN)
    if hr or ar:
        bars += bar_row("🟥 Red cards / game", r["home"], hr, r["away"], ar, LOSS, LOSS)
    if hc or ac:
        bars += bar_row("⛳ Corners FT / game", r["home"], hc, r["away"], ac, "#22d3ee", "#22d3ee")
    bars += "</div>"
    st.markdown(bars, unsafe_allow_html=True)


def render_match_card(r: dict, standings: dict, scorers: dict, motivations: dict,
                      preloaded_ctx: dict | None) -> None:
    is_fallback = r["breakdown"].get("is_fallback")
    base_conf = round(r["confidence"], 1)
    pred = r["prediction"]
    fixture_id = r.get("fixture_id")
    motivation = (
        st.session_state.get(f"_mot_{fixture_id}") if fixture_id else None
    ) or (motivations.get(fixture_id) if fixture_id else None)
    if motivation:
        conf, mot_adjustment = apply_motivation_adjustment(base_conf, motivation, pred)
    else:
        conf, mot_adjustment = base_conf, 0.0
    edge = r["edge"]
    odds = edge.get("odds")
    bookmaker = edge.get("bookmaker", "")
    if odds:
        # Re-price EV/Kelly with the motivation-adjusted confidence
        ev, kelly = _real_edge(conf, odds)
        is_value = ev > 0
    else:
        ev = round(edge.get("ev", 0), 3)
        kelly = round(edge.get("kelly", 0), 3)
        is_value = edge.get("value_bet")
    home_crest = r.get("home_crest", "")
    away_crest = r.get("away_crest", "")

    val_star = " ⭐" if is_value else ""
    odds_tag = f"  ·  @{odds:.2f}" if odds else ""
    label = f"{r['home']} vs {r['away']}  ·  {pred}  ·  {conf}%{odds_tag}{val_star}"

    with st.expander(label):
        # ── Match header — glass card, gradient border on value bets ──
        hl = _logo_img(home_crest, 28)
        al = _logo_img(away_crest, 28)
        ev_col = WIN if ev > 0 else LOSS
        val_badge = (
            pill("⭐ VALUE BET", "rgba(52,211,153,0.12)", WIN)
            if is_value else
            pill("No edge", "rgba(255,255,255,0.05)", "#666")
        )
        fallback_note = (
            ' &nbsp;' + pill("⚠ Fallback stats", "rgba(251,191,36,0.10)", WARN)
            if is_fallback else ""
        )
        xg_h = r["breakdown"]["xg"]["home"]
        xg_a = r["breakdown"]["xg"]["away"]

        ev_label = f"EV @ {odds:.2f}" if odds else "EV (model)"
        odds_block = ""
        if odds:
            bankroll = float(st.session_state.get("bankroll") or 0)
            stake = round(bankroll * kelly * 0.25, 2) if bankroll > 0 and kelly > 0 else 0
            stake_part = (
                f'<span class="sv-mono" style="font-size:11px;color:{WIN};font-weight:700;">¼ Kelly: €{stake:,.2f}</span>'
                if stake > 0 else ""
            )
            bookie_label = "derived from 1X2" if bookmaker == "~derived" else bookmaker
            odds_block = (
                f'<div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:12px;">'
                f'{pill(f"💰 {odds:.2f}", "rgba(34,211,238,0.10)", "#22d3ee", 12)}'
                f'<span style="font-size:10px;color:{TEXT_DIM};">best price · {bookie_label}</span>'
                f'{stake_part}'
                f'</div>'
            )
        header_inner = (
            f'<div style="display:flex;align-items:center;justify-content:center;gap:14px;margin-bottom:16px;">'
            f'<div style="display:flex;align-items:center;gap:7px;">{hl}<strong style="font-size:15px;">{r["home"]}</strong></div>'
            f'<span style="color:{TEXT_FAINT};font-size:11px;padding:2px 8px;border:1px solid rgba(255,255,255,0.1);border-radius:4px;">vs</span>'
            f'<div style="display:flex;align-items:center;gap:7px;"><strong style="font-size:15px;">{r["away"]}</strong>{al}</div>'
            f'</div>'
            f'<div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:12px;">'
            f'{pred_pill(pred, 14)}'
            f'{confidence_bar(conf)}'
            f'<div style="display:flex;gap:16px;">'
            f'<div style="text-align:center;">'
            f'<div style="font-size:9px;color:{TEXT_FAINT};text-transform:uppercase;letter-spacing:0.5px;">{ev_label}</div>'
            f'<div class="sv-mono" style="font-size:14px;font-weight:700;color:{ev_col};">{ev:+.3f}</div>'
            f'</div>'
            f'<div style="text-align:center;">'
            f'<div style="font-size:9px;color:{TEXT_FAINT};text-transform:uppercase;letter-spacing:0.5px;">Kelly</div>'
            f'<div class="sv-mono" style="font-size:14px;font-weight:700;">{kelly:.3f}</div>'
            f'</div></div>'
            f'{val_badge}'
            f'</div>'
            f'{odds_block}'
            + bar_row("Expected Goals (xG)", r["home"], xg_h, r["away"], xg_a)
            + f'<div style="font-size:11px;color:{TEXT_DIM};margin-top:10px;">🕐 {r["kickoff"]}{fallback_note}</div>'
        )
        st.markdown(card_html(header_inner, accent=bool(is_value)), unsafe_allow_html=True)

        # Preview
        preview = generate_preview(r["home"], r["away"], pred, r["breakdown"], r["confidence"])
        st.markdown(f"_{preview}_")
        st.divider()

        # Motivation panel / button
        _render_motivation_section(r, motivation, standings, base_conf, conf, mot_adjustment)
        st.divider()

        # Top scorers — from the prefetched league scorer lists (no extra HTTP)
        league_scorers = scorers.get(r["competition_code"], [])
        home_player, home_wiki, home_goals, home_assists = top_scorer_from_list(league_scorers, r["home"])
        away_player, away_wiki, away_goals, away_assists = top_scorer_from_list(league_scorers, r["away"])

        if home_player or away_player:
            cards_html = []
            for player, wiki, goals, assists, team in [
                (home_player, home_wiki, home_goals, home_assists, r["home"]),
                (away_player, away_wiki, away_goals, away_assists, r["away"]),
            ]:
                if not player:
                    continue
                img_url = get_player_image_url(wiki)
                img_el = (
                    f'<img src="{img_url}" style="width:72px;height:72px;border-radius:50%;object-fit:cover;flex-shrink:0;">'
                    if img_url else
                    '<div style="width:72px;height:72px;border-radius:50%;background:rgba(255,255,255,0.06);flex-shrink:0;"></div>'
                )
                cards_html.append(
                    '<div class="sv-card" style="flex:1 1 180px;display:flex;align-items:center;gap:10px;padding:10px 14px;">'
                    f'{img_el}<div style="min-width:0;">'
                    f'<div style="font-size:9px;color:{TEXT_FAINT};text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">TOP SCORER · {team}</div>'
                    f'<div style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{player}</div>'
                    f'<div style="font-size:11px;color:#888;margin-top:2px;">⚽ {goals} &nbsp;·&nbsp; {assists} assists</div>'
                    f'</div></div>'
                )
            if cards_html:
                st.markdown(
                    '<div style="display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 10px;">' + "".join(cards_html) + "</div>",
                    unsafe_allow_html=True,
                )

        # Starting XI + injuries (batch-preloaded for today, lazy for upcoming)
        st.divider()
        _context_section(r, preloaded_ctx)

        # Head-to-head (on demand, fragment-scoped)
        st.divider()
        _h2h_section(r)

        # Season stats (on demand, fragment-scoped)
        st.divider()
        _season_stats_section(r)

        with st.expander("Model details"):
            st.json(r["breakdown"])


# ══════════════════════════════════════════════════════════════════════════════
# Ticket evaluation — parallel score fetch
# ══════════════════════════════════════════════════════════════════════════════

def _auto_evaluate_pending_tickets() -> None:
    """Evaluate each pick individually and derive ticket status from pick results.

    Per-pick result: 'won', 'lost', or 'pending' (match not yet finished).
    Ticket result:
      - 'lost'    if any pick is 'lost' (fail-fast, even if other picks still pending)
      - 'won'     if all picks are 'won'
      - 'pending' otherwise
    """
    tickets = get_all_tickets()

    # Collect every unresolved fixture across all open tickets…
    pending_fids: set = set()
    for ticket in tickets:
        if ticket["result"] not in ("pending", "won"):
            continue
        for pick in ticket.get("picks", []):
            if pick.get("result") in ("won", "lost"):
                continue
            fid = pick.get("fixture_id")
            try:
                pending_fids.add(int(fid))
            except (TypeError, ValueError):
                continue

    # …then fetch all scores in parallel (capped: football-data 10 req/min)
    scores: dict = {}
    if pending_fids:
        with ThreadPoolExecutor(max_workers=FOOTBALL_DATA_WORKERS) as ex:
            futures = {ex.submit(fetch_match_score, fid): fid for fid in pending_fids}
            for fut in as_completed(futures):
                try:
                    scores[futures[fut]] = fut.result()
                except Exception:
                    scores[futures[fut]] = None

    for ticket in tickets:
        if ticket["result"] not in ("pending", "won"):
            continue  # already lost, nothing to update
        picks = ticket.get("picks", [])
        if not picks:
            continue

        updated_picks = [dict(p) for p in picks]
        changed = False

        for pick in updated_picks:
            if pick.get("result") in ("won", "lost"):
                continue  # already resolved
            try:
                fid = int(pick.get("fixture_id"))
            except (TypeError, ValueError):
                pick["result"] = "pending"
                continue
            score = scores.get(fid)
            if score is None:
                pick["result"] = "pending"
            else:
                pick["result"] = "won" if pick_won(pick["prediction"], score[0], score[1]) else "lost"
                changed = True

        pick_results = [p.get("result", "pending") for p in updated_picks]
        if "lost" in pick_results:
            new_ticket_result = "lost"
        elif all(res == "won" for res in pick_results):
            new_ticket_result = "won"
        else:
            new_ticket_result = "pending"

        if changed or new_ticket_result != ticket["result"]:
            update_ticket_picks_and_result(ticket["id"], updated_picks, new_ticket_result)


# ══════════════════════════════════════════════════════════════════════════════
# Sections
# ══════════════════════════════════════════════════════════════════════════════

def _filters_row() -> list:
    fcol1, fcol2 = st.columns([5, 1])
    with fcol1:
        leagues = st.multiselect(
            "Leagues",
            ALL_LEAGUES,
            default=DEFAULT_LEAGUES,
            key="leagues_sel",
            label_visibility="collapsed",
        )
    with fcol2:
        now = datetime.now(timezone.utc).timestamp()
        last_refresh = st.session_state.get("last_refresh", 0)
        seconds_since = now - last_refresh
        can_refresh = seconds_since >= REFRESH_COOLDOWN_SECONDS
        if st.button("🔄 Refresh", disabled=not can_refresh, width="stretch"):
            st.cache_data.clear()
            st.session_state["last_refresh"] = now
            st.rerun()
        if not can_refresh:
            wait = int(REFRESH_COOLDOWN_SECONDS - seconds_since)
            st.markdown(
                f'<div style="text-align:center;font-size:11px;color:{TEXT_FAINT};margin-top:4px;">Next refresh in {wait}s</div>',
                unsafe_allow_html=True,
            )
        elif last_refresh:
            last_str = datetime.fromtimestamp(last_refresh, tz=DISPLAY_TZ).strftime("%H:%M")
            st.markdown(
                f'<div style="text-align:center;font-size:11px;color:{TEXT_FAINT};margin-top:4px;">Last refreshed {last_str}</div>',
                unsafe_allow_html=True,
            )

    # Second row: card filters + bankroll for stake sizing
    with st.expander("🎛 Filters & bankroll"):
        f1, f2, f3, f4 = st.columns([1.1, 1.6, 2.2, 1.3])
        with f1:
            st.toggle("⭐ Value only", key="flt_value_only")
        with f2:
            st.slider("Min confidence", 38, 92, 38, key="flt_min_conf")
        with f3:
            st.multiselect("Markets", list(PRED_STYLE.keys()), key="flt_markets",
                           placeholder="All markets")
        with f4:
            st.number_input("Bankroll €", min_value=0.0, value=100.0, step=10.0,
                            key="bankroll")

    return leagues or DEFAULT_LEAGUES


def _apply_filters(results: list) -> list:
    out = results
    if st.session_state.get("flt_value_only"):
        out = [r for r in out if r["edge"].get("value_bet")]
    min_conf = st.session_state.get("flt_min_conf", 38)
    if min_conf > 38:
        out = [r for r in out if r["confidence"] >= min_conf]
    markets = st.session_state.get("flt_markets") or []
    if markets:
        out = [r for r in out if r["prediction"] in markets]
    return out


@st.cache_data(ttl=70, show_spinner=False)
def _cached_live_matches(league_codes: tuple) -> list:
    """TTL just under the fragment interval: each 75s tick refetches, but
    ordinary full-page reruns reuse the cached response."""
    return fetch_live_matches(league_codes)


@st.fragment(run_every=75)
def _live_scores_strip(league_codes: tuple) -> None:
    """Auto-refreshing live scores — one football-data request per tick."""
    live = _cached_live_matches(league_codes)
    if not live:
        return
    pills = ""
    for m in live:
        minute = f"{m['minute']}'" if m.get("minute") else "LIVE"
        pills += (
            f'<div class="sv-card" style="padding:8px 14px;display:inline-flex;align-items:center;gap:8px;margin:0 8px 8px 0;">'
            f'<span class="sv-live-dot"></span>'
            f'{_logo_img(m["home_crest"], 16)}'
            f'<span style="font-size:12px;font-weight:600;">{m["home"]}</span>'
            f'<span class="sv-mono" style="font-size:14px;font-weight:800;color:{WIN};">{m["home_goals"]}–{m["away_goals"]}</span>'
            f'<span style="font-size:12px;font-weight:600;">{m["away"]}</span>'
            f'{_logo_img(m["away_crest"], 16)}'
            f'<span class="sv-mono" style="font-size:10px;color:{WARN};">{minute}</span>'
            f'</div>'
        )
    st.markdown(
        f'<div style="font-size:11px;color:{LOSS};font-weight:700;letter-spacing:1px;margin-bottom:6px;">● LIVE NOW</div>'
        f'<div>{pills}</div>',
        unsafe_allow_html=True,
    )


def _render_ticket_slip(ticket: dict, today_results: list) -> None:
    crest_map = {r["match"]: (r.get("home_crest", ""), r.get("away_crest", "")) for r in today_results}
    avg_conf = round(ticket.get("avg_confidence", 0), 1)
    avg_col = conf_color(avg_conf)

    slip_rows = ""
    total_odds = 1.0
    all_have_odds = bool(ticket["ticket"])
    for t in ticket["ticket"]:
        h_crest, a_crest = crest_map.get(t["match"], ("", ""))
        h_img = _logo_img(h_crest, 18)
        a_img = _logo_img(a_crest, 18)
        parts = t["match"].split(" vs ", 1)
        home_part = parts[0] if parts else t["match"]
        away_part = parts[1] if len(parts) > 1 else ""
        ev_val = round(t.get("ev", 0), 3)
        ev_col = WIN if ev_val > 0 else LOSS
        pick_odds = t.get("odds")
        if pick_odds:
            total_odds *= pick_odds
            odds_html = f'<span class="sv-mono" style="font-size:11px;color:#22d3ee;font-weight:700;">@{pick_odds:.2f}</span>'
        else:
            all_have_odds = False
            odds_html = ""
        ko = f'<span style="color:{TEXT_FAINT};font-size:10px;">🕐 {t["kickoff"]}</span>' if t.get("kickoff") else ""
        slip_rows += (
            f'<div style="display:flex;align-items:center;gap:8px;padding:10px 0;'
            f'border-bottom:1px solid rgba(255,255,255,0.06);">'
            f'<div style="display:flex;align-items:center;gap:5px;flex:1;min-width:0;">'
            f'{h_img}<span style="font-size:12px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{home_part}</span>'
            f'<span style="color:{TEXT_FAINT};font-size:10px;flex-shrink:0;">vs</span>'
            f'<span style="font-size:12px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{away_part}</span>{a_img}'
            f'</div>'
            f'<div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">'
            f'{ko}'
            f'{pred_pill(t["prediction"])}'
            f'{odds_html}'
            f'<span class="sv-mono" style="font-size:11px;font-weight:700;color:{ev_col};">EV {ev_val:+.3f}</span>'
            f'</div></div>'
        )

    payout_html = ""
    if all_have_odds and total_odds > 1:
        stake = float(st.session_state.get("bankroll") or 100) * 0.05  # 5% of bankroll
        payout_html = (
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;">'
            f'<span style="font-size:11px;color:{TEXT_DIM};">Combined odds</span>'
            f'<span class="sv-mono" style="font-size:14px;font-weight:700;color:#22d3ee;">{total_odds:.2f}</span>'
            f'</div>'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px;">'
            f'<span style="font-size:11px;color:{TEXT_DIM};">€{stake:,.2f} (5% bankroll) returns</span>'
            f'<span class="sv-mono" style="font-size:14px;font-weight:700;color:{WIN};">€{stake * total_odds:,.2f}</span>'
            f'</div>'
        )

    inner = (
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">'
        f'<span style="font-size:11px;color:{WIN};text-transform:uppercase;letter-spacing:1px;font-weight:600;">📋 Today\'s Ticket</span>'
        f'<span style="font-size:11px;color:{TEXT_FAINT};">{len(ticket["ticket"])} picks</span>'
        f'</div>'
        f'{slip_rows}'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.08);">'
        f'<span style="font-size:11px;color:{TEXT_DIM};">Avg Confidence</span>'
        f'<span class="sv-mono" style="font-size:16px;font-weight:700;color:{avg_col};">{avg_conf}%</span>'
        f'</div>'
        f'{payout_html}'
    )
    st.markdown(card_html(inner, accent=True), unsafe_allow_html=True)


def _render_model_performance(tickets: list) -> None:
    """Calibration view built from decided ticket picks: hit rate per market
    and per confidence bucket — shows WHERE the model is right or wrong."""
    per_market: dict = {}
    buckets = {"38–55%": [0, 0], "55–65%": [0, 0], "65–75%": [0, 0], "75%+": [0, 0]}

    for t in tickets:
        for p in t.get("picks", []):
            res = p.get("result")
            if res not in ("won", "lost"):
                continue
            won = 1 if res == "won" else 0
            market = p.get("prediction", "?")
            m = per_market.setdefault(market, [0, 0])
            m[0] += won
            m[1] += 1 - won
            conf = p.get("confidence")
            if conf:
                if conf < 55:
                    b = buckets["38–55%"]
                elif conf < 65:
                    b = buckets["55–65%"]
                elif conf < 75:
                    b = buckets["65–75%"]
                else:
                    b = buckets["75%+"]
                b[0] += won
                b[1] += 1 - won

    if not per_market:
        return

    def _stat_rows(data: dict, label: str) -> str:
        rows = f'<div style="font-size:10px;color:{TEXT_FAINT};text-transform:uppercase;letter-spacing:0.5px;margin:10px 0 6px;">{label}</div>'
        for name, (w, l) in sorted(data.items(), key=lambda x: -(x[1][0] + x[1][1])):
            total = w + l
            if total == 0:
                continue
            rate = w / total * 100
            color = WIN if rate >= 55 else WARN if rate >= 45 else LOSS
            rows += (
                f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:5px;">'
                f'<span style="font-size:11px;width:80px;color:{TEXT};">{name}</span>'
                f'<div class="sv-track" style="height:7px;">'
                f'<div class="sv-fill" style="width:{rate:.0f}%;background:{color};color:{color};"></div></div>'
                f'<span class="sv-mono" style="font-size:11px;font-weight:700;color:{color};width:42px;">{rate:.0f}%</span>'
                f'<span style="font-size:10px;color:{TEXT_FAINT};width:64px;">{w}W–{l}L</span>'
                f'</div>'
            )
        return rows

    with st.expander("📊 Model performance — where the engine wins & loses"):
        html = _stat_rows(per_market, "Hit rate by market")
        if any(w + l for w, l in buckets.values()):
            html += _stat_rows(
                {k: v for k, v in buckets.items() if v[0] + v[1] > 0},
                "Calibration by confidence bucket",
            )
            html += (
                f'<div style="font-size:10px;color:{TEXT_FAINT};margin-top:8px;font-style:italic;">'
                'A calibrated model wins ~as often as its confidence bucket suggests.</div>'
            )
        st.markdown(html, unsafe_allow_html=True)


def _render_ticket_history() -> None:
    # Run evaluation once per session (not on every rerender)
    if not st.session_state.get("_tickets_evaluated"):
        _auto_evaluate_pending_tickets()
        st.session_state["_tickets_evaluated"] = True

    col_title, col_refresh = st.columns([6, 1])
    with col_title:
        section_header("Ticket History",
                       "Results are evaluated per match — ticket is lost as soon as any pick loses")
    with col_refresh:
        st.write("")
        if st.button("↺ Refresh", key="refresh_ticket_results"):
            st.session_state["_tickets_evaluated"] = False
            _auto_evaluate_pending_tickets()
            st.session_state["_tickets_evaluated"] = True
            st.rerun()

    tickets = get_all_tickets()

    if not tickets:
        st.info("No tickets saved yet. Today's ticket saves automatically when picks are available.")
        return

    won = sum(1 for t in tickets if t["result"] == "won")
    lost = sum(1 for t in tickets if t["result"] == "lost")
    decided = won + lost
    win_rate = (won / decided * 100) if decided > 0 else None

    streak, streak_type = 0, ""
    for t in tickets:
        if t["result"] == "pending":
            continue
        if not streak_type:
            streak_type, streak = t["result"], 1
        elif t["result"] == streak_type:
            streak += 1
        else:
            break
    streak_label = (f"{'W' if streak_type == 'won' else 'L'}{streak}" if streak_type else "—")
    streak_col = WIN if streak_type == "won" else LOSS if streak_type else "#888"

    # Stats row — animated count-up tiles
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        count_up(len(tickets), label="Total", size=22)
    with c2:
        count_up(won, label="Won", color=WIN, size=22)
    with c3:
        count_up(lost, label="Lost", color=LOSS, size=22)
    with c4:
        if win_rate is not None:
            count_up(win_rate, suffix="%", label="Win Rate", size=22)
        else:
            st.markdown(
                f'<div style="font-size:9px;color:{TEXT_FAINT};text-transform:uppercase;letter-spacing:0.6px;">Win Rate</div>'
                f'<div class="sv-mono" style="font-size:22px;font-weight:700;">—</div>',
                unsafe_allow_html=True,
            )
    with c5:
        st.markdown(
            f'<div style="font-size:9px;color:{TEXT_FAINT};text-transform:uppercase;letter-spacing:0.6px;">Streak</div>'
            f'<div class="sv-mono" style="font-size:22px;font-weight:700;color:{streak_col};">{streak_label}</div>',
            unsafe_allow_html=True,
        )

    # W/L chip strip (last 15 decided tickets) — staggered fade-in
    chip_style = {
        "won":  f"background:rgba(52,211,153,0.14);color:{WIN};",
        "lost": f"background:rgba(248,113,113,0.14);color:{LOSS};",
    }
    decided_tickets = [t for t in tickets if t["result"] in ("won", "lost")]
    chips = "".join(
        f'<span class="sv-chip" style="{chip_style[t["result"]]}animation-delay:{i * 0.05:.2f}s;">'
        f'{"W" if t["result"] == "won" else "L"}</span>'
        for i, t in enumerate(decided_tickets[:15])
    )
    if chips:
        st.markdown(
            f'<div style="display:flex;gap:4px;flex-wrap:wrap;margin:4px 0 12px;">{chips}</div>',
            unsafe_allow_html=True,
        )

    _render_model_performance(tickets)

    _RESULT_BADGE = {
        "won":     ("rgba(52,211,153,0.12)", WIN),
        "lost":    ("rgba(248,113,113,0.12)", LOSS),
        "pending": ("rgba(251,191,36,0.12)", WARN),
    }
    _RESULT_LABEL = {"won": "WON", "lost": "LOST", "pending": "PENDING"}
    _PICK_RESULT_COLOR = {"won": WIN, "lost": LOSS, "pending": "#555"}

    for t in tickets:
        date = t["date"]
        result = t.get("result", "pending")
        picks = t.get("picks", [])
        avg_conf = t.get("avg_confidence", 0)
        badge_bg, badge_fg = _RESULT_BADGE.get(result, _RESULT_BADGE["pending"])
        badge_label = _RESULT_LABEL.get(result, "PENDING")
        exp_label = f"{date}  ·  {badge_label}  ·  {len(picks)} picks"

        with st.expander(exp_label):
            hdr_col, override_col = st.columns([3, 1])
            with hdr_col:
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">'
                    f'<span style="font-weight:600;font-size:13px;">{date}</span>'
                    f'{pill(badge_label, badge_bg, badge_fg)}'
                    f'<span style="color:{TEXT_FAINT};font-size:11px;margin-left:auto;">{len(picks)} picks · avg conf {round(avg_conf, 1)}%</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            if result == "pending":
                with override_col:
                    ow, ol = st.columns(2)
                    if ow.button("W", key=f"override_won_{t['id']}", help="Mark as WON"):
                        update_ticket_result(t["id"], "won")
                        st.rerun()
                    if ol.button("L", key=f"override_lost_{t['id']}", help="Mark as LOST"):
                        update_ticket_result(t["id"], "lost")
                        st.rerun()
            for p in picks:
                pev = round(p.get("ev", 0), 3)
                pev_col = WIN if pev > 0 else LOSS
                pr = p.get("result", "pending")
                pr_col = _PICK_RESULT_COLOR.get(pr, "#555")
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.05);">'
                    f'<span style="color:{pr_col};font-size:10px;">●</span>'
                    f'<span style="font-size:12px;font-weight:600;flex:1;">{p["match"]}</span>'
                    f'{pred_pill(p["prediction"], 11)}'
                    f'<span class="sv-mono" style="font-size:11px;color:{pev_col};font-weight:600;">EV {pev:+.3f}</span>'
                    f'<span class="sv-mono" style="font-size:11px;color:{TEXT_FAINT};">Kelly {round(p.get("kelly", 0), 3)}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

def render() -> None:
    leagues = _filters_row()

    # ── League data: one parallel cached batch ──
    with st.spinner("⚡ Loading league data…"):
        data = load_league_data(tuple(leagues))
    standings = data["standings"]
    scorers = data["scorers"]

    # Hand fetched tables to the prediction engine so it never re-fetches them
    for lg, table in standings.items():
        set_league_standings(lg, table)

    results = _build_results(data["matches"], standings)

    # ── Real bookmaker odds: synthetic EV → market-priced EV ──
    league_codes_in_play = tuple(sorted({r["competition_code"] for r in results}))
    if league_codes_in_play:
        with st.spinner("⚡ Fetching bookmaker odds…"):
            odds_by_code = load_odds(league_codes_in_play)
        # Tournaments before matchday 1 (all standings on zero) → market prior
        _apply_market_priors(results, odds_by_code, standings)
        results = _attach_real_odds(results, odds_by_code)
        remaining = odds_requests_remaining()
        if remaining is not None:
            st.caption(f"💰 Odds: The Odds API · {remaining} credits left this month")

    # ── Log ALL predictions once per day (backtesting data) ──
    today_local = datetime.now(DISPLAY_TZ).date()
    log_key = f"_preds_logged_{today_local.isoformat()}"
    if results and not st.session_state.get(log_key):
        log_predictions([
            {
                "fixture_id": int(r["fixture_id"]),
                "date": r["kickoff_date_str"],
                "match": r["match"],
                "league": r["league"],
                "market": r["prediction"],
                "confidence": r["confidence"],
                "ev": r["edge"].get("model_ev", 0),
                "real_ev": r["edge"].get("ev", 0) if r["edge"].get("odds") else None,
                "odds": r["edge"].get("odds"),
                "value_bet": bool(r["edge"].get("value_bet")),
            }
            for r in results if r.get("fixture_id")
        ])
        st.session_state[log_key] = True

    today_results = [r for r in results if r["kickoff_date"] == today_local]
    upcoming_results = [r for r in results if r["kickoff_date"] > today_local]

    # ── Live scores strip (auto-refreshes every 75s) ──
    _live_scores_strip(tuple(LEAGUE_CODES[lg] for lg in leagues if lg in LEAGUE_CODES))

    # ── Today's context: one parallel cached batch (lineups + injuries) ──
    today_keys = tuple(
        (_match_id(r), r["home"], r["away"], r.get("competition_code", "PL"),
         r.get("kickoff_date_str", ""))
        for r in today_results
    )
    with st.spinner("⚡ Fetching lineups & injuries…"):
        context_batch = load_context_batch(today_keys)

    # ── Motivations: ONE Supabase query for all fixtures ──
    fixture_ids = tuple(r["fixture_id"] for r in results if r.get("fixture_id"))
    motivations = load_motivations(fixture_ids)

    # ── Today's matches ──
    section_header(f"Today's Picks — {today_local.strftime('%d %B %Y')}")

    today_shown = _apply_filters(today_results)
    if today_shown:
        for r in today_shown:
            render_match_card(r, standings, scorers, motivations,
                              context_batch.get(_match_id(r)))
    elif today_results:
        st.info("All of today's matches are hidden by the active filters.")
    else:
        st.info("No matches scheduled for today in the selected leagues.")

    # ── Upcoming matches (context lazy-loads per card) ──
    section_header("Upcoming Picks")

    upcoming_shown = _apply_filters(upcoming_results)
    if upcoming_shown:
        seen_dates: set = set()
        for r in upcoming_shown:
            date_label = r["kickoff_date"].strftime("%A, %d %B %Y")
            if date_label not in seen_dates:
                seen_dates.add(date_label)
                st.subheader(date_label)
            render_match_card(r, standings, scorers, motivations, None)
    elif upcoming_results:
        st.info("All upcoming matches are hidden by the active filters.")
    else:
        st.info("No upcoming matches in the next 7 days for the selected leagues.")

    # ── Auto ticket ──
    ticket = build_ticket(today_results)

    # Auto-save today's ticket to Supabase whenever the app loads
    if ticket and ticket.get("ticket"):
        save_ticket(ticket["ticket"], ticket.get("avg_confidence", 0), today_local.isoformat())

    section_header("Auto Ticket Builder", "Today's picks only — sorted by Expected Value")

    if ticket and ticket.get("ticket"):
        _render_ticket_slip(ticket, today_results)
    else:
        st.markdown(
            card_html('<div style="text-align:center;color:#666;font-size:13px;">'
                      'No picks available for today</div>'),
            unsafe_allow_html=True,
        )

    # ── Ticket History ──
    _render_ticket_history()
