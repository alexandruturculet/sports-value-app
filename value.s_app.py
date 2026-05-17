import logging
import os
import streamlit as st
from datetime import datetime, timedelta, timezone
import pytz

from services.football_api import (
    get_standings_for_leagues,
    get_top_scorer_for_team,
    make_request,
    BASE_URL,
    LEAGUE_CODES,
)
from models.v7.prediction_engine import generate_prediction
from models.v7.ticket_engine import build_ticket
from models.v7.match_preview import generate_preview
from services.player_images import get_player_image_url
from services.api_football import get_fixture_injuries
from services.espn_api import get_espn_lineups, get_espn_last_lineup, get_espn_injuries
from services.supabase_client import save_ticket, get_all_tickets, update_ticket_result
from models.data_normalizer import normalize_league, register_team_stats
from models.team_strength_model import get_team_strength

logging.basicConfig(level=logging.INFO)

_FOOTBALL_DATA_KEY = os.getenv("football-data-api-key")
if not _FOOTBALL_DATA_KEY:
    st.error(
        "**API key missing.** Set `football-data-api-key` in Streamlit Cloud → "
        "Manage app → Settings → Secrets.",
        icon="🔑",
    )
    st.stop()

DISPLAY_TZ = pytz.timezone("Europe/Bucharest")
MAX_MATCHES = 25
REFRESH_COOLDOWN_SECONDS = 60

ALL_LEAGUES = [
    "Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1",
    "Liga Portugal", "Eredivisie", "Championship", "Belgian Pro League",
]

st.set_page_config(page_title="V7 EDGE ENGINE", layout="wide")
st.title("V7 REAL EDGE ENGINE")

st.markdown("""
<style>
@keyframes matchReveal {
    0%   { opacity: 0; transform: translateY(-16px) scale(0.97); filter: blur(4px); }
    60%  { opacity: 1; transform: translateY(3px)   scale(1.004); filter: blur(0); }
    100% { opacity: 1; transform: translateY(0)     scale(1);    filter: blur(0); }
}
[data-testid="stExpanderDetails"] {
    animation: matchReveal 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
}
[data-testid="stExpander"] summary:hover {
    background: rgba(255,255,255,0.04) !important;
    border-radius: 6px;
    transition: background 0.2s;
}
</style>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    leagues = st.multiselect(
        "Select leagues",
        ALL_LEAGUES,
        default=["Premier League", "La Liga", "Serie A"],
    )

    st.divider()

    now = datetime.now(timezone.utc).timestamp()
    last_refresh = st.session_state.get("last_refresh", 0)
    seconds_since = now - last_refresh
    can_refresh = seconds_since >= REFRESH_COOLDOWN_SECONDS

    if st.button("Refresh predictions", disabled=not can_refresh):
        st.cache_data.clear()
        st.session_state["last_refresh"] = now
        st.rerun()

    if not can_refresh:
        wait = int(REFRESH_COOLDOWN_SECONDS - seconds_since)
        st.caption(f"Next refresh available in {wait}s")


# ── Data fetching ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def get_matches(leagues: tuple):
    all_matches = []
    today = datetime.now(timezone.utc).date()
    next_week = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")

    for league in leagues:
        code = LEAGUE_CODES.get(league)
        if not code:
            continue
        url = f"{BASE_URL}/competitions/{code}/matches?dateFrom={today}&dateTo={next_week}"
        data = make_request(url)
        if not data or "matches" not in data:
            continue
        for m in data["matches"]:
            if m["status"] in ("SCHEDULED", "TIMED", "IN_PLAY", "LIVE"):
                all_matches.append(m)

    return all_matches


@st.cache_data(ttl=3600)
def cached_prediction(home: str, away: str, league: str, fixture_id):
    return generate_prediction(home, away, league, fixture_id)


# ── Engine loop ───────────────────────────────────────────────────────────────

standings = get_standings_for_leagues(leagues)
matches = get_matches(tuple(leagues))

results = []
processed = 0
today_local = datetime.now(DISPLAY_TZ).date()

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
        "fixture_id": fixture_id,
        "prediction": prediction,
        "confidence": confidence,
        "reason": reason,
        "breakdown": breakdown,
        "edge": edge,
        "home_crest": m["homeTeam"].get("crest", ""),
        "away_crest": m["awayTeam"].get("crest", ""),
    })


# ── Sort ──────────────────────────────────────────────────────────────────────

results = sorted(results, key=lambda x: x.get("edge", {}).get("ev", 0), reverse=True)

today_results = [r for r in results if r["kickoff_date"] == today_local]
upcoming_results = [r for r in results if r["kickoff_date"] > today_local]


# ── Precompute lineup + injury data (all HTTP calls happen here, not inside expanders) ──

_LINEUP_EMPTY = {"home": {"lineup": [], "bench": []}, "away": {"lineup": [], "bench": []}}

for r in today_results:
    date_str = r.get("kickoff_date_str", "")
    code = r.get("competition_code", "PL")
    confirmed = get_espn_lineups(r["home"], r["away"], code, date_str)
    if confirmed["home"]["lineup"] and confirmed["away"]["lineup"]:
        r["_lineup"] = confirmed
        r["_probable"] = False
    else:
        home_last = get_espn_last_lineup(r["home"], code)
        away_last = get_espn_last_lineup(r["away"], code)
        r["_lineup"] = {"home": home_last, "away": away_last}
        r["_probable"] = bool(home_last["lineup"] or away_last["lineup"])
    r["_injuries"] = get_fixture_injuries(r["home"], r["away"], date_str, code)
    if not r["_injuries"]["home"] and not r["_injuries"]["away"]:
        r["_injuries"] = get_espn_injuries(r["home"], r["away"], code, date_str)

_tomorrow_str = (today_local + timedelta(days=2)).isoformat()
for r in upcoming_results:
    r["_lineup"] = _LINEUP_EMPTY
    r["_probable"] = False
    date_str = r.get("kickoff_date_str", "")
    code = r.get("competition_code", "PL")
    if date_str <= _tomorrow_str:
        r["_injuries"] = get_fixture_injuries(r["home"], r["away"], date_str, code)
        if not r["_injuries"]["home"] and not r["_injuries"]["away"]:
            r["_injuries"] = get_espn_injuries(r["home"], r["away"], code, date_str)
    else:
        r["_injuries"] = {"home": [], "away": []}


# ── Render helpers ────────────────────────────────────────────────────────────

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
        f'<div style="background:{bg};color:#111;border-radius:50%;width:28px;height:28px;'
        f'display:flex;align-items:center;justify-content:center;font-weight:700;font-size:10px;'
        f'box-shadow:0 2px 5px rgba(0,0,0,0.5);">{num}</div>'
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
        'background:linear-gradient(180deg,#1e6e1e 0%,#164d16 100%);'
        'border-radius:10px;padding:8px 2px;font-family:\'Segoe UI\',Arial,sans-serif;'
        'border:1px solid rgba(255,255,255,0.12);">'
        f'<div style="text-align:center;font-size:10px;color:rgba(255,255,255,0.45);margin-bottom:4px;">{label}</div>'
        f'{a_header}{away_rows}'
        f'{center_line}'
        f'{home_rows}{h_footer}'
        '</div></div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_match_card(r: dict) -> None:
    is_fallback = r["breakdown"].get("is_fallback")
    value_badge = " ✔ VALUE" if r["edge"].get("value_bet") else ""
    label = f"{r['match']} | {r['prediction']} ({round(r['confidence'], 2)}%){value_badge}"
    home_crest = r.get("home_crest", "")
    away_crest = r.get("away_crest", "")

    with st.expander(label):
        # Match header with team logos
        hl = _logo_img(home_crest, 24)
        al = _logo_img(away_crest, 24)
        st.markdown(
            f'<div style="display:flex;align-items:center;justify-content:center;gap:10px;'
            f'padding:2px 0 10px;">'
            f'<div style="display:flex;align-items:center;gap:6px;">'
            f'{hl}<strong>{r["home"]}</strong></div>'
            f'<span style="color:#888;font-size:12px;">vs</span>'
            f'<div style="display:flex;align-items:center;gap:6px;">'
            f'<strong>{r["away"]}</strong>{al}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Preview text
        preview = generate_preview(
            r["home"], r["away"], r["prediction"], r["breakdown"], r["confidence"]
        )
        st.markdown(f"_{preview}_")
        st.divider()

        # Key player cards — compact inline scorer strip
        home_player, home_wiki, home_goals, home_assists = get_top_scorer_for_team(r["home"], r["competition_code"])
        away_player, away_wiki, away_goals, away_assists = get_top_scorer_for_team(r["away"], r["competition_code"])

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
                    f'<img src="{img_url}" style="width:72px;height:72px;border-radius:50%;'
                    f'object-fit:cover;flex-shrink:0;">'
                    if img_url else
                    '<div style="width:72px;height:72px;border-radius:50%;background:#2a2a2a;flex-shrink:0;"></div>'
                )
                cards_html.append(
                    f'<div style="flex:1 1 180px;display:flex;align-items:center;gap:10px;padding:10px 14px;'
                    f'border-radius:8px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.07);">'
                    f'{img_el}'
                    f'<div style="min-width:0;">'
                    f'<div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px;'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">TOP SCORER · {team}</div>'
                    f'<div style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;'
                    f'text-overflow:ellipsis;">{player}</div>'
                    f'<div style="font-size:11px;color:#888;margin-top:2px;">⚽ {goals} &nbsp;·&nbsp; {assists} assists</div>'
                    f'</div></div>'
                )
            if cards_html:
                st.markdown(
                    '<div style="display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 10px;">' + "".join(cards_html) + "</div>",
                    unsafe_allow_html=True,
                )
            st.divider()

        # Stats
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Prediction", r["prediction"])
        c2.metric("Confidence", f"{round(r['confidence'], 1)}%")
        c3.metric("EV", round(r["edge"].get("ev", 0), 3))
        c4.metric("Kelly", round(r["edge"].get("kelly", 0), 3))

        st.write("**Kickoff:**", r["kickoff"])

        if is_fallback:
            st.warning("One or both teams used fallback stats — treat this pick with caution.")

        if r["edge"].get("value_bet"):
            st.success("VALUE BET")
        else:
            st.warning("No edge detected")

        # Starting XI + Absents  (data pre-fetched before render loop)
        st.divider()
        lineup_data = r["_lineup"]
        probable = r["_probable"]
        injuries = r["_injuries"]
        home_xi = lineup_data["home"]["lineup"]
        away_xi = lineup_data["away"]["lineup"]

        if home_xi or away_xi:
            _render_pitch(r["home"], home_xi, r["away"], away_xi, probable, home_crest, away_crest)
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

        with st.expander("Model details"):
            st.json(r["breakdown"])


# ── Today's matches ───────────────────────────────────────────────────────────

st.header(f"Today's Picks — {today_local.strftime('%d %B %Y')}")

if today_results:
    for r in today_results:
        render_match_card(r)
else:
    st.info("No matches scheduled for today in the selected leagues.")


# ── Upcoming matches ──────────────────────────────────────────────────────────

st.header("Upcoming Picks")

if upcoming_results:
    # Group by date
    seen_dates: set = set()
    for r in upcoming_results:
        date_label = r["kickoff_date"].strftime("%A, %d %B %Y")
        if date_label not in seen_dates:
            seen_dates.add(date_label)
            st.subheader(date_label)
        render_match_card(r)
else:
    st.info("No upcoming matches in the next 7 days for the selected leagues.")


# ── Auto ticket ───────────────────────────────────────────────────────────────

ticket = build_ticket(today_results)

# Auto-save today's ticket to Supabase whenever the app loads
if ticket and ticket.get("ticket"):
    save_ticket(ticket["ticket"], ticket.get("avg_confidence", 0), today_local.isoformat())

st.header("Auto Ticket Builder")
st.caption("Today's picks only — sorted by Expected Value")

if ticket and ticket.get("ticket"):
    _crest_map = {r["match"]: (r.get("home_crest", ""), r.get("away_crest", "")) for r in today_results}

    for t in ticket["ticket"]:
        h_crest, a_crest = _crest_map.get(t["match"], ("", ""))
        h_img = _logo_img(h_crest, 20)
        a_img = _logo_img(a_crest, 20)
        parts = t["match"].split(" vs ", 1)
        home_part = parts[0] if parts else t["match"]
        away_part = parts[1] if len(parts) > 1 else ""
        kickoff_label = f"&nbsp;·&nbsp;{t['kickoff']}" if t.get("kickoff") else ""
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:6px;padding:7px 0;'
            f'border-bottom:1px solid rgba(128,128,128,0.15);">'
            f'{h_img}&nbsp;<strong>{home_part}</strong>'
            f'<span style="color:#888;font-size:11px;margin:0 2px;">vs</span>'
            f'<strong>{away_part}</strong>&nbsp;{a_img}'
            f'<span style="color:#aaa;font-size:11px;margin-left:auto;">'
            f'{t["prediction"]}&nbsp;·&nbsp;EV&nbsp;{round(t.get("ev", 0), 3)}'
            f'&nbsp;|&nbsp;Kelly&nbsp;{round(t.get("kelly", 0), 3)}{kickoff_label}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    st.success(f"Avg Confidence: {round(ticket.get('avg_confidence', 0), 2)}%")
else:
    st.warning("No picks available for today")


# ── Ticket History ────────────────────────────────────────────────────────────


def _match_outcome(fixture_id: int) -> str | None:
    """Returns 'Home Win', 'Away Win', 'Draw', or None if not yet finished."""
    data = make_request(f"{BASE_URL}/matches/{fixture_id}")
    if not data or data.get("status") != "FINISHED":
        return None
    score = data.get("score", {}).get("fullTime", {})
    h, a = score.get("home"), score.get("away")
    if h is None or a is None:
        return None
    return "Home Win" if h > a else ("Away Win" if a > h else "Draw")


def _auto_evaluate_pending_tickets(today_str: str) -> None:
    """Check all past pending tickets and auto-mark won/lost. Runs once per session."""
    for ticket in get_all_tickets():
        if ticket["result"] != "pending":
            continue
        if ticket["date"] >= today_str:
            continue  # today's ticket — wait until tomorrow
        picks = ticket.get("picks", [])
        if not picks:
            continue
        outcomes = []
        all_finished = True
        for pick in picks:
            fid = pick.get("fixture_id")
            if not fid:
                all_finished = False
                break
            outcome = _match_outcome(int(fid))
            if outcome is None:
                all_finished = False
                break
            outcomes.append(outcome == pick["prediction"])
        if all_finished and outcomes:
            update_ticket_result(ticket["id"], "won" if all(outcomes) else "lost")


# Run evaluation once per session (not on every rerender)
if not st.session_state.get("_tickets_evaluated"):
    _auto_evaluate_pending_tickets(today_local.isoformat())
    st.session_state["_tickets_evaluated"] = True

st.header("Ticket History")
st.caption("Results are evaluated automatically once all matches in a ticket finish")

_tickets = get_all_tickets()

if not _tickets:
    st.info("No tickets saved yet. Today's ticket saves automatically when picks are available.")
else:
    # Stats
    _won = sum(1 for t in _tickets if t["result"] == "won")
    _lost = sum(1 for t in _tickets if t["result"] == "lost")
    _decided = _won + _lost
    _win_rate = (_won / _decided * 100) if _decided > 0 else None

    # Current streak (skip pending)
    _streak, _streak_type = 0, ""
    for _t in _tickets:
        if _t["result"] == "pending":
            continue
        if not _streak_type:
            _streak_type, _streak = _t["result"], 1
        elif _t["result"] == _streak_type:
            _streak += 1
        else:
            break
    _streak_label = (
        f"{'W' if _streak_type == 'won' else 'L'}{_streak}" if _streak_type else "—"
    )

    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
    sc1.metric("Total", len(_tickets))
    sc2.metric("Won", _won)
    sc3.metric("Lost", _lost)
    sc4.metric("Win Rate", f"{_win_rate:.1f}%" if _win_rate is not None else "N/A")
    sc5.metric("Streak", _streak_label)

    st.divider()

    _RESULT_BADGE = {
        "won":     '<span style="background:#1a7a3f;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">WON</span>',
        "lost":    '<span style="background:#7a1a1a;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">LOST</span>',
        "pending": '<span style="background:#5a4a00;color:#ffd080;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">PENDING</span>',
    }

    for _t in _tickets:
        _date = _t["date"]
        _result = _t.get("result", "pending")
        _picks = _t.get("picks", [])
        _avg_conf = _t.get("avg_confidence", 0)
        _badge = _RESULT_BADGE.get(_result, _RESULT_BADGE["pending"])

        with st.expander(f"{_date}  |  {_result.upper()}  |  {len(_picks)} picks"):
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
                f'<span style="font-weight:600;">{_date}</span>{_badge}'
                f'<span style="color:#888;font-size:11px;">'
                f'{len(_picks)} picks · Avg conf {round(_avg_conf, 1)}%</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            for _p in _picks:
                st.write(
                    f"**{_p['match']}** — {_p['prediction']} "
                    f"— EV: {round(_p.get('ev', 0), 3)} | Kelly: {round(_p.get('kelly', 0), 3)}"
                )
