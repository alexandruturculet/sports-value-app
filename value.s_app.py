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
from models.v7.prediction_engine import generate_prediction, apply_motivation_adjustment
from models.v7.ticket_engine import build_ticket
from models.v7.match_preview import generate_preview
from services.player_images import get_player_image_url
from services.api_football import get_fixture_injuries, get_team_season_stats, is_api_rate_limited
from services.espn_api import get_espn_lineups, get_espn_last_lineup, get_espn_injuries
from services.supabase_client import save_ticket, get_all_tickets, update_ticket_result, update_ticket_picks_and_result, get_motivation, save_motivation
from models.v7.motivation_engine import analyze_motivation
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
@keyframes liquidPour {
    0%   {
        opacity: 0;
        clip-path: polygon(4% 0%, 96% 0%, 95% 1%, 5% 1%);
        filter: blur(10px) hue-rotate(220deg) saturate(8) brightness(3.5);
        transform: translateY(-12px);
    }
    12%  {
        opacity: 0.85;
        clip-path: polygon(-1% 0%, 101% 0%, 107% 18%, -7% 12%);
        filter: blur(7px) hue-rotate(160deg) saturate(5) brightness(2.2);
        transform: translateY(-6px);
    }
    30%  {
        clip-path: polygon(-5% 0%, 105% 0%, 112% 52%, -12% 42%);
        filter: blur(3px) hue-rotate(90deg) saturate(3) brightness(1.6);
        transform: translateY(-2px);
    }
    52%  {
        opacity: 1;
        clip-path: polygon(-7% 0%, 107% 0%, 105% 88%, -5% 78%);
        filter: blur(1px) hue-rotate(28deg) saturate(1.9) brightness(1.25);
        transform: translateY(0);
    }
    68%  {
        clip-path: polygon(-2% 0%, 102% 0%, 102% 100%, -2% 100%);
        filter: blur(0) hue-rotate(8deg) saturate(1.4) brightness(1.08);
        transform: translateY(4px);
    }
    81%  {
        clip-path: polygon(0.5% 0%, 99.5% 0%, 99% 100%, 1% 100%);
        filter: blur(0) saturate(1.15) brightness(1.03);
        transform: translateY(-1.5px);
    }
    91%  {
        clip-path: polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%);
        filter: saturate(1.04);
        transform: translateY(0.8px);
    }
    100% {
        opacity: 1;
        clip-path: polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%);
        filter: blur(0) hue-rotate(0deg) saturate(1) brightness(1);
        transform: translateY(0);
    }
}

@keyframes iridShimmer {
    0%   { background-position: -100% 0; }
    100% { background-position: 280% 0; }
}

[data-testid="stExpanderDetails"] {
    animation:
        liquidPour 0.9s cubic-bezier(0.16, 1, 0.3, 1) forwards,
        iridShimmer 1.1s ease-out 0.08s forwards;
    transform-origin: top center;
    background: linear-gradient(
        108deg,
        transparent 15%,
        rgba(64, 210, 255, 0.09) 36%,
        rgba(200, 70, 255, 0.09) 50%,
        rgba(50, 255, 180, 0.07) 64%,
        transparent 84%
    ) no-repeat;
    background-size: 420% 100%;
}

[data-testid="stExpander"] summary:hover {
    background: rgba(255,255,255,0.04) !important;
    border-radius: 6px;
    transition: background 0.2s;
}
</style>
""", unsafe_allow_html=True)


# ── League state (set before data fetch, updated by widget inside sports tab) ──

_DEFAULT_LEAGUES = ["Premier League", "La Liga", "Serie A"]

leagues = st.session_state.get("leagues_sel", _DEFAULT_LEAGUES)


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


@st.cache_data(ttl=600)
def _cached_motivation(fixture_id):
    if not fixture_id:
        return None
    return get_motivation(int(fixture_id))


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


_PRED_STYLE = {
    "1":         ("#1e4d1e", "#5dd65d"),
    "2":         ("#1a1e4d", "#5d8af5"),
    "X":         ("#4a4220", "#f5d45d"),
    "1X":        ("#1e3d2a", "#5dd680"),
    "X2":        ("#2a1e3d", "#8a5df5"),
    "BTTS":      ("#1a3d4d", "#5dd4f5"),
    "Over 2.5":  ("#4d3a1a", "#f5a45d"),
    "Under 2.5": ("#3a1a4d", "#a45df5"),
}


def _conf_color(conf: float) -> str:
    if conf >= 72:
        return "#4caf50"
    if conf >= 58:
        return "#ff9800"
    return "#f44336"


def _bar_row(label: str, home_name: str, home_val: float,
             away_name: str, away_val: float,
             home_color: str = "#5dd65d", away_color: str = "#5d8af5") -> str:
    mx = max(home_val, away_val, 0.01)
    h_pct = min(home_val / mx * 100, 100)
    a_pct = min(away_val / mx * 100, 100)
    ns = "font-size:11px;color:#ddd;width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:right;"
    bb = "height:7px;background:#1e1e1e;border-radius:4px;overflow:hidden;flex:1;"
    return (
        f'<div style="margin:8px 0 2px;">'
        f'<div style="font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:5px;">{label}</div>'
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
        f'<span style="{ns}">{home_name}</span>'
        f'<div style="{bb}"><div style="width:{h_pct:.0f}%;height:100%;background:{home_color};border-radius:4px;"></div></div>'
        f'<span style="font-size:11px;font-weight:700;color:{home_color};width:34px;">{home_val:.2f}</span>'
        f'</div>'
        f'<div style="display:flex;align-items:center;gap:8px;">'
        f'<span style="{ns}">{away_name}</span>'
        f'<div style="{bb}"><div style="width:{a_pct:.0f}%;height:100%;background:{away_color};border-radius:4px;"></div></div>'
        f'<span style="font-size:11px;font-weight:700;color:{away_color};width:34px;">{away_val:.2f}</span>'
        f'</div>'
        f'</div>'
    )


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


_MOTIVATION_BADGE = {
    "HIGH":   ("#0d2d0d", "#5dd65d", "rgba(93,214,93,0.3)"),
    "MEDIUM": ("#2d2700", "#f5d45d", "rgba(245,212,93,0.3)"),
    "LOW":    ("#2d0d0d", "#f55d5d", "rgba(245,93,93,0.3)"),
}


def _motivation_badge(level: str) -> str:
    bg, fg, border = _MOTIVATION_BADGE.get(level, _MOTIVATION_BADGE["MEDIUM"])
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 10px;border-radius:12px;'
        f'font-size:11px;font-weight:700;border:1px solid {border};">{level}</span>'
    )


def _render_motivation_section(r: dict, motivation: dict | None, base_conf: float, conf: float, adjustment: float) -> None:
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
            adj_str = f'<span style="color:#5dd65d;font-weight:700;">+{adjustment:.1f}</span>'
        elif adjustment < 0:
            adj_str = f'<span style="color:#f55d5d;font-weight:700;">{adjustment:.1f}</span>'
        else:
            adj_str = '<span style="color:#888;font-weight:700;">0</span>'
        st.markdown(
            '<div style="padding:8px 12px;background:rgba(255,255,255,0.03);border-radius:8px;border:1px solid rgba(255,255,255,0.06);">'
            '<div style="font-size:10px;color:#666;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">🧠 Motivation</div>'
            '<div style="display:flex;gap:16px;margin-bottom:8px;">'
            f'<div style="flex:1;"><div style="font-size:12px;font-weight:600;margin-bottom:4px;">{r["home"]} &nbsp;{_motivation_badge(home_lvl)}</div>'
            f'<ul style="margin:4px 0 0 16px;padding:0;">{home_list}</ul></div>'
            f'<div style="flex:1;"><div style="font-size:12px;font-weight:600;margin-bottom:4px;">{r["away"]} &nbsp;{_motivation_badge(away_lvl)}</div>'
            f'<ul style="margin:4px 0 0 16px;padding:0;">{away_list}</ul></div>'
            '</div>'
            f'<div style="font-size:11px;color:#ccc;font-style:italic;margin-bottom:6px;">{summary}</div>'
            f'<div style="font-size:11px;color:#888;">Confidence: {base_conf}% → <strong>{conf}%</strong> · motivation {adj_str}</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        if fixture_id and st.button("↻ Re-analyze", key=f"mot_reanalyze_{fixture_id}", help="Re-run with latest standings"):
            league = r.get("league", "")
            league_standings = standings.get(league, []) if league else []
            analysis = analyze_motivation(r["home"], r["away"], league, league_standings)
            if save_motivation(int(fixture_id), r["home"], r["away"], analysis):
                _cached_motivation.clear()
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
            _cached_motivation.clear()
        else:
            st.session_state[f"_mot_{fixture_id}"] = analysis
        st.rerun()


def render_match_card(r: dict) -> None:
    is_fallback = r["breakdown"].get("is_fallback")
    base_conf = round(r["confidence"], 1)
    pred = r["prediction"]
    fixture_id = r.get("fixture_id")
    motivation = (
        st.session_state.get(f"_mot_{fixture_id}") if fixture_id else None
    ) or _cached_motivation(fixture_id)
    if motivation:
        conf, mot_adjustment = apply_motivation_adjustment(base_conf, motivation, pred)
    else:
        conf, mot_adjustment = base_conf, 0.0
    ev = round(r["edge"].get("ev", 0), 3)
    kelly = round(r["edge"].get("kelly", 0), 3)
    is_value = r["edge"].get("value_bet")
    home_crest = r.get("home_crest", "")
    away_crest = r.get("away_crest", "")

    val_star = " ⭐" if is_value else ""
    label = f"{r['home']} vs {r['away']}  ·  {pred}  ·  {conf}%{val_star}"

    with st.expander(label):
        # ── Match header ──────────────────────────────────────────
        hl = _logo_img(home_crest, 28)
        al = _logo_img(away_crest, 28)
        conf_col = _conf_color(conf)
        pred_bg, pred_fg = _PRED_STYLE.get(pred, ("#333", "#fff"))
        ev_col = "#4caf50" if ev > 0 else "#f44336"
        val_badge = (
            '<span style="background:#0d2d0d;color:#5dd65d;padding:3px 10px;border-radius:20px;'
            'font-size:11px;font-weight:700;border:1px solid rgba(93,214,93,0.3);">⭐ VALUE BET</span>'
            if is_value else
            '<span style="background:#1e1010;color:#666;padding:3px 10px;border-radius:20px;'
            'font-size:11px;border:1px solid rgba(255,255,255,0.08);">No edge</span>'
        )
        fallback_note = (
            ' &nbsp;<span style="background:#2d2000;color:#e6a817;padding:2px 8px;border-radius:4px;'
            'font-size:10px;">⚠ Fallback stats</span>' if is_fallback else ""
        )
        xg_h = r["breakdown"]["xg"]["home"]
        xg_a = r["breakdown"]["xg"]["away"]

        st.markdown(
            '<div style="padding:4px 0 12px;">'
            f'<div style="display:flex;align-items:center;justify-content:center;gap:14px;margin-bottom:16px;">'
            f'<div style="display:flex;align-items:center;gap:7px;">{hl}<strong style="font-size:15px;">{r["home"]}</strong></div>'
            f'<span style="color:#444;font-size:11px;padding:2px 8px;border:1px solid #2a2a2a;border-radius:4px;">vs</span>'
            f'<div style="display:flex;align-items:center;gap:7px;"><strong style="font-size:15px;">{r["away"]}</strong>{al}</div>'
            f'</div>'
            f'<div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:12px;">'
            f'<span style="background:{pred_bg};color:{pred_fg};padding:5px 14px;border-radius:20px;font-size:14px;font-weight:700;">{pred}</span>'
            f'<div style="flex:1;min-width:100px;">'
            f'<div style="display:flex;justify-content:space-between;margin-bottom:3px;">'
            f'<span style="font-size:10px;color:#666;">Confidence</span>'
            f'<span style="font-size:10px;color:{conf_col};font-weight:700;">{conf}%</span>'
            f'</div>'
            f'<div style="height:5px;background:#1e1e1e;border-radius:3px;overflow:hidden;">'
            f'<div style="width:{conf}%;height:100%;background:{conf_col};border-radius:3px;"></div>'
            f'</div></div>'
            f'<div style="display:flex;gap:16px;">'
            f'<div style="text-align:center;">'
            f'<div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.5px;">EV</div>'
            f'<div style="font-size:14px;font-weight:700;color:{ev_col};">{ev:+.3f}</div>'
            f'</div>'
            f'<div style="text-align:center;">'
            f'<div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.5px;">Kelly</div>'
            f'<div style="font-size:14px;font-weight:700;">{kelly:.3f}</div>'
            f'</div></div>'
            f'{val_badge}'
            f'</div>'
            + _bar_row("Expected Goals (xG)", r["home"], xg_h, r["away"], xg_a)
            + f'<div style="font-size:11px;color:#666;margin-top:10px;">🕐 {r["kickoff"]}{fallback_note}</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        # Preview
        preview = generate_preview(r["home"], r["away"], pred, r["breakdown"], r["confidence"])
        st.markdown(f"_{preview}_")
        st.divider()

        # Motivation panel / button
        _render_motivation_section(r, motivation, base_conf, conf, mot_adjustment)
        st.divider()

        # Top scorers
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
                    f'<img src="{img_url}" style="width:72px;height:72px;border-radius:50%;object-fit:cover;flex-shrink:0;">'
                    if img_url else
                    '<div style="width:72px;height:72px;border-radius:50%;background:#2a2a2a;flex-shrink:0;"></div>'
                )
                cards_html.append(
                    f'<div style="flex:1 1 180px;display:flex;align-items:center;gap:10px;padding:10px 14px;'
                    f'border-radius:8px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.07);">'
                    f'{img_el}<div style="min-width:0;">'
                    f'<div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">TOP SCORER · {team}</div>'
                    f'<div style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{player}</div>'
                    f'<div style="font-size:11px;color:#888;margin-top:2px;">⚽ {goals} &nbsp;·&nbsp; {assists} assists</div>'
                    f'</div></div>'
                )
            if cards_html:
                st.markdown(
                    '<div style="display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 10px;">' + "".join(cards_html) + "</div>",
                    unsafe_allow_html=True,
                )

        # Starting XI
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

        # Injuries
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

        # ── Season stats (on demand) ──────────────────────────────
        st.divider()
        _stats_key = f"_teamstats_{r.get('fixture_id', r['match'])}"
        _btn_key = f"load_stats_{r.get('fixture_id', r['match'])}"
        if _stats_key not in st.session_state:
            if st.button("📊 Load season stats", key=_btn_key):
                _code = r.get("competition_code", "PL")
                st.session_state[_stats_key] = {
                    "home": get_team_season_stats(r["home"], _code),
                    "away": get_team_season_stats(r["away"], _code),
                }
        if _stats_key in st.session_state:
            _sd = st.session_state[_stats_key]
            _hs, _as = _sd["home"], _sd["away"]
            if not _hs and not _as:
                if is_api_rate_limited():
                    st.warning("API-Football daily limit reached (100 req/day). Try again tomorrow.")
                else:
                    st.caption("No stats available — team not found in API-Football for this league.")
                if st.button("↩ Retry", key=f"retry_stats_{r.get('fixture_id', r['match'])}"):
                    del st.session_state[_stats_key]
                    st.rerun()
            else:
                played = _hs.get("played") or _as.get("played") or "?"
                _bars = f'<div style="padding:4px 0;"><div style="font-size:10px;color:#555;margin-bottom:10px;">Season averages · {played} games</div>'
                hy = _hs.get("avg_yellow") or 0
                ay = _as.get("avg_yellow") or 0
                hr = _hs.get("avg_red") or 0
                ar = _as.get("avg_red") or 0
                hc = _hs.get("avg_corners_ft") or 0
                ac = _as.get("avg_corners_ft") or 0
                if hy or ay:
                    _bars += _bar_row("🟨 Yellow cards / game", r["home"], hy, r["away"], ay, "#f5d45d", "#f5d45d")
                if hr or ar:
                    _bars += _bar_row("🟥 Red cards / game", r["home"], hr, r["away"], ar, "#f55d5d", "#f55d5d")
                if hc or ac:
                    _bars += _bar_row("⛳ Corners FT / game", r["home"], hc, r["away"], ac, "#5dd4f5", "#5dd4f5")
                _bars += "</div>"
                st.markdown(_bars, unsafe_allow_html=True)

        with st.expander("Model details"):
            st.json(r["breakdown"])



def _sports_display() -> None:
    # ── Filters ───────────────────────────────────────────────────────────────────

    _fcol1, _fcol2 = st.columns([5, 1])
    with _fcol1:
        st.multiselect(
            "Leagues",
            ALL_LEAGUES,
            default=_DEFAULT_LEAGUES,
            key="leagues_sel",
            label_visibility="collapsed",
        )
    with _fcol2:
        _now = datetime.now(timezone.utc).timestamp()
        _last_refresh = st.session_state.get("last_refresh", 0)
        _seconds_since = _now - _last_refresh
        _can_refresh = _seconds_since >= REFRESH_COOLDOWN_SECONDS
        if st.button("🔄 Refresh", disabled=not _can_refresh, use_container_width=True):
            st.cache_data.clear()
            st.session_state["last_refresh"] = _now
            st.rerun()
        if not _can_refresh:
            _wait = int(REFRESH_COOLDOWN_SECONDS - _seconds_since)
            st.markdown(
                f'<div style="text-align:center;font-size:11px;color:#555;margin-top:4px;">Next refresh in {_wait}s</div>',
                unsafe_allow_html=True,
            )
        elif _last_refresh:
            _last_str = datetime.fromtimestamp(_last_refresh, tz=DISPLAY_TZ).strftime("%H:%M")
            st.markdown(
                f'<div style="text-align:center;font-size:11px;color:#555;margin-top:4px;">Last refreshed {_last_str}</div>',
                unsafe_allow_html=True,
            )

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
        _avg_conf = round(ticket.get("avg_confidence", 0), 1)
        _conf_col = _conf_color(_avg_conf)

        _slip_rows = ""
        for t in ticket["ticket"]:
            h_crest, a_crest = _crest_map.get(t["match"], ("", ""))
            h_img = _logo_img(h_crest, 18)
            a_img = _logo_img(a_crest, 18)
            parts = t["match"].split(" vs ", 1)
            home_part = parts[0] if parts else t["match"]
            away_part = parts[1] if len(parts) > 1 else ""
            pred_bg, pred_fg = _PRED_STYLE.get(t["prediction"], ("#333", "#fff"))
            ev_val = round(t.get("ev", 0), 3)
            ev_col = "#4caf50" if ev_val > 0 else "#f44336"
            ko = f'<span style="color:#555;font-size:10px;">🕐 {t["kickoff"]}</span>' if t.get("kickoff") else ""
            _slip_rows += (
                f'<div style="display:flex;align-items:center;gap:8px;padding:10px 0;'
                f'border-bottom:1px solid rgba(255,255,255,0.06);">'
                f'<div style="display:flex;align-items:center;gap:5px;flex:1;min-width:0;">'
                f'{h_img}<span style="font-size:12px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{home_part}</span>'
                f'<span style="color:#444;font-size:10px;flex-shrink:0;">vs</span>'
                f'<span style="font-size:12px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{away_part}</span>{a_img}'
                f'</div>'
                f'<div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">'
                f'{ko}'
                f'<span style="background:{pred_bg};color:{pred_fg};padding:2px 9px;border-radius:12px;font-size:11px;font-weight:700;">{t["prediction"]}</span>'
                f'<span style="font-size:11px;font-weight:700;color:{ev_col};">EV {ev_val:+.3f}</span>'
                f'</div></div>'
            )

        st.markdown(
            f'<div style="background:#0a1a0a;border:1px solid rgba(93,214,93,0.18);border-radius:12px;padding:16px 20px;margin:4px 0;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">'
            f'<span style="font-size:11px;color:#5dd65d;text-transform:uppercase;letter-spacing:1px;font-weight:600;">📋 Today\'s Ticket</span>'
            f'<span style="font-size:11px;color:#555;">{len(ticket["ticket"])} picks</span>'
            f'</div>'
            f'{_slip_rows}'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.08);">'
            f'<span style="font-size:11px;color:#666;">Avg Confidence</span>'
            f'<span style="font-size:16px;font-weight:700;color:{_conf_col};">{_avg_conf}%</span>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="background:#1a0a0a;border:1px solid rgba(255,255,255,0.08);border-radius:12px;'
            'padding:16px 20px;text-align:center;color:#666;font-size:13px;">No picks available for today</div>',
            unsafe_allow_html=True,
        )


    # ── Ticket History ────────────────────────────────────────────────────────────


    def _fetch_match_score(fixture_id: int) -> tuple[int, int] | None:
        """Returns (home_goals, away_goals) if finished, else None."""
        data = make_request(f"{BASE_URL}/matches/{fixture_id}")
        if not data or data.get("status") != "FINISHED":
            return None
        score = data.get("score", {}).get("fullTime", {})
        h, a = score.get("home"), score.get("away")
        if h is None or a is None:
            return None
        return (int(h), int(a))


    def _pick_won(prediction: str, h: int, a: int) -> bool:
        """Evaluate whether a pick was correct given the final score."""
        p = prediction.strip()
        if p == "1":
            return h > a
        if p == "2":
            return a > h
        if p == "X":
            return h == a
        if p == "1X":
            return h >= a
        if p == "X2":
            return a >= h
        if p == "BTTS":
            return h >= 1 and a >= 1
        if p in ("Over 2.5", "Over2.5"):
            return h + a >= 3
        if p in ("Under 2.5", "Under2.5"):
            return h + a <= 2
        return False


    def _auto_evaluate_pending_tickets() -> None:
        """Evaluate each pick individually and derive ticket status from pick results.

        Per-pick result: 'won', 'lost', or 'pending' (match not yet finished).
        Ticket result:
          - 'lost'    if any pick is 'lost' (fail-fast, even if other picks still pending)
          - 'won'     if all picks are 'won'
          - 'pending' otherwise
        """
        for ticket in get_all_tickets():
            if ticket["result"] not in ("pending", "won"):
                continue  # already lost, nothing to update
            picks = ticket.get("picks", [])
            if not picks:
                continue

            updated_picks = [dict(p) for p in picks]
            changed = False

            for pick in updated_picks:
                if pick.get("result") in ("won", "lost"):
                    continue  # already resolved, skip API call
                fid = pick.get("fixture_id")
                if not fid:
                    pick["result"] = "pending"
                    continue
                score = _fetch_match_score(int(fid))
                if score is None:
                    pick["result"] = "pending"
                else:
                    pick["result"] = "won" if _pick_won(pick["prediction"], score[0], score[1]) else "lost"
                    changed = True

            pick_results = [p.get("result", "pending") for p in updated_picks]
            if "lost" in pick_results:
                new_ticket_result = "lost"
            elif all(r == "won" for r in pick_results):
                new_ticket_result = "won"
            else:
                new_ticket_result = "pending"

            if changed or new_ticket_result != ticket["result"]:
                update_ticket_picks_and_result(ticket["id"], updated_picks, new_ticket_result)


    # Run evaluation once per session (not on every rerender)
    if not st.session_state.get("_tickets_evaluated"):
        _auto_evaluate_pending_tickets()
        st.session_state["_tickets_evaluated"] = True

    _col_title, _col_refresh = st.columns([6, 1])
    with _col_title:
        st.header("Ticket History")
        st.caption("Results are evaluated per match — ticket is lost as soon as any pick loses")
    with _col_refresh:
        st.write("")
        if st.button("↺ Refresh", key="refresh_ticket_results"):
            st.session_state["_tickets_evaluated"] = False
            _auto_evaluate_pending_tickets()
            st.session_state["_tickets_evaluated"] = True
            st.rerun()

    _tickets = get_all_tickets()

    if not _tickets:
        st.info("No tickets saved yet. Today's ticket saves automatically when picks are available.")
    else:
        _won = sum(1 for t in _tickets if t["result"] == "won")
        _lost = sum(1 for t in _tickets if t["result"] == "lost")
        _decided = _won + _lost
        _win_rate = (_won / _decided * 100) if _decided > 0 else None

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
        _streak_label = (f"{'W' if _streak_type == 'won' else 'L'}{_streak}" if _streak_type else "—")

        # W/L chip strip (last 15 decided tickets)
        _chip_style = {
            "won":  "background:#1a3d1a;color:#5dd65d;",
            "lost": "background:#3d1a1a;color:#f55d5d;",
        }
        _decided_tickets = [t for t in _tickets if t["result"] in ("won", "lost")]
        _chips = "".join(
            f'<span style="{_chip_style[t["result"]]}padding:3px 8px;border-radius:4px;font-size:11px;font-weight:700;">{"W" if t["result"]=="won" else "L"}</span>'
            for t in _decided_tickets[:15]
        )

        # Summary bar
        st.markdown(
            f'<div style="background:#111;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:14px 18px;margin-bottom:12px;">'
            f'<div style="display:flex;flex-wrap:wrap;gap:20px;align-items:center;margin-bottom:12px;">'
            f'<div style="text-align:center;"><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.5px;">Total</div><div style="font-size:18px;font-weight:700;">{len(_tickets)}</div></div>'
            f'<div style="text-align:center;"><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.5px;">Won</div><div style="font-size:18px;font-weight:700;color:#5dd65d;">{_won}</div></div>'
            f'<div style="text-align:center;"><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.5px;">Lost</div><div style="font-size:18px;font-weight:700;color:#f55d5d;">{_lost}</div></div>'
            f'<div style="text-align:center;"><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.5px;">Win Rate</div><div style="font-size:18px;font-weight:700;">{f"{_win_rate:.0f}%" if _win_rate is not None else "—"}</div></div>'
            f'<div style="text-align:center;"><div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:0.5px;">Streak</div><div style="font-size:18px;font-weight:700;color:{"#5dd65d" if _streak_type=="won" else "#f55d5d" if _streak_type else "#888"};">{_streak_label}</div></div>'
            f'</div>'
            + (f'<div style="display:flex;gap:4px;flex-wrap:wrap;">{_chips}</div>' if _chips else "")
            + '</div>',
            unsafe_allow_html=True,
        )

        _RESULT_BADGE = {
            "won":     "background:#0d2d0d;color:#5dd65d;border:1px solid rgba(93,214,93,0.3);",
            "lost":    "background:#2d0d0d;color:#f55d5d;border:1px solid rgba(245,93,93,0.3);",
            "pending": "background:#2d2700;color:#f5d45d;border:1px solid rgba(245,212,93,0.3);",
        }
        _RESULT_LABEL = {"won": "WON", "lost": "LOST", "pending": "PENDING"}

        for _t in _tickets:
            _date = _t["date"]
            _result = _t.get("result", "pending")
            _picks = _t.get("picks", [])
            _avg_conf = _t.get("avg_confidence", 0)
            _badge_style = _RESULT_BADGE.get(_result, _RESULT_BADGE["pending"])
            _badge_label = _RESULT_LABEL.get(_result, "PENDING")
            _exp_label = f"{_date}  ·  {_badge_label}  ·  {len(_picks)} picks"

            with st.expander(_exp_label):
                _hdr_col, _override_col = st.columns([3, 1])
                with _hdr_col:
                    st.markdown(
                        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">'
                        f'<span style="font-weight:600;font-size:13px;">{_date}</span>'
                        f'<span style="{_badge_style}padding:2px 10px;border-radius:12px;font-size:11px;font-weight:700;">{_badge_label}</span>'
                        f'<span style="color:#555;font-size:11px;margin-left:auto;">{len(_picks)} picks · avg conf {round(_avg_conf, 1)}%</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                if _result == "pending":
                    with _override_col:
                        _ow, _ol = st.columns(2)
                        if _ow.button("W", key=f"override_won_{_t['id']}", help="Mark as WON"):
                            update_ticket_result(_t["id"], "won")
                            st.rerun()
                        if _ol.button("L", key=f"override_lost_{_t['id']}", help="Mark as LOST"):
                            update_ticket_result(_t["id"], "lost")
                            st.rerun()
                _PICK_RESULT_STYLE = {
                    "won":     ("●", "#5dd65d"),
                    "lost":    ("●", "#f55d5d"),
                    "pending": ("●", "#555"),
                }
                for _p in _picks:
                    _ppred = _p["prediction"]
                    _ppb, _ppf = _PRED_STYLE.get(_ppred, ("#333", "#fff"))
                    _pev = round(_p.get("ev", 0), 3)
                    _pev_col = "#4caf50" if _pev > 0 else "#f44336"
                    _pr = _p.get("result", "pending")
                    _pr_dot, _pr_col = _PICK_RESULT_STYLE.get(_pr, ("●", "#555"))
                    st.markdown(
                        f'<div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.05);">'
                        f'<span style="color:{_pr_col};font-size:10px;">{_pr_dot}</span>'
                        f'<span style="font-size:12px;font-weight:600;flex:1;">{_p["match"]}</span>'
                        f'<span style="background:{_ppb};color:{_ppf};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;">{_ppred}</span>'
                        f'<span style="font-size:11px;color:{_pev_col};font-weight:600;">EV {_pev:+.3f}</span>'
                        f'<span style="font-size:11px;color:#555;">Kelly {round(_p.get("kelly",0),3)}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )




_tab_sports, _tab_crypto, _tab_markets = st.tabs(["⚽ Sports Betting", "₿ Crypto", "📈 Markets"])

with _tab_sports:
    _sports_display()
with _tab_crypto:
    from sections.crypto import render as _rc
    _rc()
with _tab_markets:
    from sections.markets import render as _rm
    _rm()