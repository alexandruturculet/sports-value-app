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
from services.espn_api import get_espn_lineups, get_espn_last_lineup
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
        "kickoff": match_dt.strftime("%d-%m-%Y %H:%M %Z"),
        "kickoff_date": match_dt.date(),
        "kickoff_date_str": match_dt.date().isoformat(),
        "competition_code": competition_code,
        "fixture_id": fixture_id,
        "prediction": prediction,
        "confidence": confidence,
        "reason": reason,
        "breakdown": breakdown,
        "edge": edge,
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
    r["_injuries"] = get_fixture_injuries(r["home"], r["away"], date_str)

for r in upcoming_results:
    r["_lineup"] = _LINEUP_EMPTY
    r["_probable"] = False
    r["_injuries"] = {"home": [], "away": []}


# ── Render helpers ────────────────────────────────────────────────────────────

_POS_GROUP = {
    "Goalkeeper": "GK", "Keeper": "GK",
    "Defender": "DEF", "Centre-Back": "DEF", "Right-Back": "DEF", "Left-Back": "DEF",
    "Midfielder": "MID", "Defensive Midfield": "MID", "Central Midfield": "MID",
    "Attacking Midfield": "MID", "Right Midfield": "MID", "Left Midfield": "MID",
    "Forward": "FWD", "Attacker": "FWD", "Winger": "FWD",
    "Centre-Forward": "FWD", "Left Winger": "FWD", "Right Winger": "FWD",
    "Striker": "FWD",
}


def _short_name(name: str) -> str:
    parts = name.split()
    return parts[-1][:12] if len(parts) > 1 else name[:12]


def _player_dot(p: dict, bg: str) -> str:
    num = str(p.get("shirtNumber", "")) or "?"
    name = _short_name(p.get("name", ""))
    return (
        '<div style="display:flex;flex-direction:column;align-items:center;margin:0 5px;">'
        f'<div style="background:{bg};color:#111;border-radius:50%;width:30px;height:30px;'
        f'display:flex;align-items:center;justify-content:center;font-weight:700;font-size:10px;'
        f'box-shadow:0 2px 4px rgba(0,0,0,0.5);">{num}</div>'
        f'<span style="color:#fff;font-size:8.5px;text-align:center;width:38px;white-space:nowrap;'
        f'overflow:hidden;text-overflow:ellipsis;text-shadow:0 1px 2px rgba(0,0,0,0.9);margin-top:2px;">{name}</span>'
        '</div>'
    )


def _pos_row(players: list, bg: str) -> str:
    if not players:
        return ""
    dots = "".join(_player_dot(p, bg) for p in players)
    return f'<div style="display:flex;justify-content:center;flex-wrap:wrap;padding:5px 4px;">{dots}</div>'


def _infer_formation(groups: dict) -> str:
    d = len(groups.get("DEF", []))
    m = len(groups.get("MID", []))
    f = len(groups.get("FWD", []))
    if 2 <= d <= 5 and 2 <= m <= 6 and 1 <= f <= 4:
        return f"{d}-{m}-{f}"
    return ""


def _render_pitch(home_name: str, home_xi: list, away_name: str, away_xi: list, probable: bool) -> None:
    def group(lineup):
        g: dict = {"GK": [], "DEF": [], "MID": [], "FWD": []}
        for p in lineup:
            g.setdefault(_POS_GROUP.get(p.get("position", ""), "MID"), []).append(p)
        return g

    hg = group(home_xi)
    ag = group(away_xi)

    label = "Probable XI — based on last match" if probable else "Confirmed lineup"
    h_form = _infer_formation(hg)
    a_form = _infer_formation(ag)

    # Away team: GK at top of pitch → FWD closest to center
    if away_xi:
        away_rows = "".join(_pos_row(ag.get(pos, []), "#ffd080") for pos in ("GK", "DEF", "MID", "FWD"))
        a_header = (
            f'<div style="font-size:11px;color:#ffd080;font-weight:600;padding:0 4px 3px;">'
            f'{away_name}'
            + (f'&nbsp;<span style="color:rgba(255,255,255,0.38);font-weight:400;">{a_form}</span>' if a_form else "")
            + '</div>'
        )
    else:
        away_rows = '<div style="display:flex;align-items:center;justify-content:center;padding:14px;color:rgba(255,255,255,0.38);font-size:12px;">Lineup not yet announced</div>'
        a_header = f'<div style="font-size:11px;color:#ffd080;font-weight:600;padding:0 4px 3px;">{away_name}</div>'

    # Home team: FWD closest to center → GK at bottom of pitch
    if home_xi:
        home_rows = "".join(_pos_row(hg.get(pos, []), "#e8e8e8") for pos in ("FWD", "MID", "DEF", "GK"))
        h_footer = (
            f'<div style="font-size:11px;color:#eee;font-weight:600;text-align:right;padding:3px 4px 0;">'
            + (f'<span style="color:rgba(255,255,255,0.38);font-weight:400;">{h_form}</span>&nbsp;' if h_form else "")
            + f'{home_name}</div>'
        )
    else:
        home_rows = '<div style="display:flex;align-items:center;justify-content:center;padding:14px;color:rgba(255,255,255,0.38);font-size:12px;">Lineup not yet announced</div>'
        h_footer = f'<div style="font-size:11px;color:#eee;font-weight:600;text-align:right;padding:3px 4px 0;">{home_name}</div>'

    center_line = (
        '<div style="display:flex;align-items:center;margin:3px 0;">'
        '<div style="flex:1;height:1px;background:rgba(255,255,255,0.18);"></div>'
        '<div style="margin:0 10px;width:18px;height:18px;border-radius:50%;'
        'border:1px solid rgba(255,255,255,0.18);flex-shrink:0;"></div>'
        '<div style="flex:1;height:1px;background:rgba(255,255,255,0.18);"></div>'
        '</div>'
    )

    html = (
        '<div style="background:linear-gradient(180deg,#256d25 0%,#1a5218 100%);'
        'border-radius:10px;padding:8px 6px;font-family:\'Segoe UI\',Arial,sans-serif;'
        'border:1px solid rgba(255,255,255,0.10);margin-bottom:6px;">'
        f'<div style="text-align:center;font-size:10px;color:rgba(255,255,255,0.45);margin-bottom:6px;">{label}</div>'
        f'{a_header}{away_rows}'
        f'{center_line}'
        f'{home_rows}{h_footer}'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_match_card(r: dict) -> None:
    is_fallback = r["breakdown"].get("is_fallback")
    value_badge = " ✔ VALUE" if r["edge"].get("value_bet") else ""
    label = f"{r['match']} | {r['prediction']} ({round(r['confidence'], 2)}%){value_badge}"

    with st.expander(label):
        # Preview text
        preview = generate_preview(
            r["home"], r["away"], r["prediction"], r["breakdown"], r["confidence"]
        )
        st.markdown(f"_{preview}_")
        st.divider()

        # Key player cards — live data from scorers endpoint
        home_player, home_wiki, home_goals, home_assists = get_top_scorer_for_team(r["home"], r["competition_code"])
        away_player, away_wiki, away_goals, away_assists = get_top_scorer_for_team(r["away"], r["competition_code"])

        if home_player or away_player:
            col_home, col_spacer, col_away = st.columns([2, 1, 2])

            with col_home:
                if home_player:
                    st.caption(f"Top scorer — {r['home']}")
                    st.markdown(f"**{home_player}**  \n{home_goals} goals · {home_assists} assists")
                    img = get_player_image_url(home_wiki)
                    if img:
                        st.image(img, width=160)

            with col_away:
                if away_player:
                    st.caption(f"Top scorer — {r['away']}")
                    st.markdown(f"**{away_player}**  \n{away_goals} goals · {away_assists} assists")
                    img = get_player_image_url(away_wiki)
                    if img:
                        st.image(img, width=160)

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
            _render_pitch(r["home"], home_xi, r["away"], away_xi, probable)
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

st.header("Auto Ticket Builder")
st.caption("Today's picks only — sorted by Expected Value")

if ticket and ticket.get("ticket"):
    for t in ticket["ticket"]:
        kickoff_label = f" | {t['kickoff']}" if t.get("kickoff") else ""
        st.write(
            f"**{t['match']}**{kickoff_label}  \n"
            f"{t['prediction']} — EV: {round(t.get('ev', 0), 3)} | Kelly: {round(t.get('kelly', 0), 3)}"
        )
    st.success(f"Avg Confidence: {round(ticket.get('avg_confidence', 0), 2)}%")
else:
    st.warning("No picks available for today")
