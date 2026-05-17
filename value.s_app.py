import logging
import streamlit as st
from datetime import datetime, timedelta, timezone
import pytz

from services.football_api import (
    get_standings_for_leagues,
    make_request,
    BASE_URL,
    LEAGUE_CODES,
)
from models.v7.prediction_engine import generate_prediction
from models.v7.ticket_engine import build_ticket
from models.data_normalizer import normalize_league, register_team_stats
from models.team_strength_model import get_team_strength

logging.basicConfig(level=logging.INFO)

import os
_FOOTBALL_DATA_KEY = os.getenv("football-data-api-key")
if not _FOOTBALL_DATA_KEY:
    st.error(
        "**API key missing.** Set `football-data-api-key` in Streamlit Cloud → Manage app → Settings → Secrets.",
        icon="🔑",
    )
    st.stop()

DISPLAY_TZ = pytz.timezone("Europe/Bucharest")

MAX_MATCHES = 25
REFRESH_COOLDOWN_SECONDS = 60

ALL_LEAGUES = [
    "Premier League",
    "La Liga",
    "Serie A",
    "Bundesliga",
    "Ligue 1",
    "Liga Portugal",
    "Eredivisie",
    "Championship",
    "Belgian Pro League",
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
# cache_data requires hashable args — convert list to tuple
matches = get_matches(tuple(leagues))

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
        "match": f"{home_name} vs {away_name}",
        "kickoff": match_dt.strftime("%d-%m-%Y %H:%M %Z"),
        "prediction": prediction,
        "confidence": confidence,
        "reason": reason,
        "breakdown": breakdown,
        "edge": edge,
    })


# ── Sort ──────────────────────────────────────────────────────────────────────

results = sorted(results, key=lambda x: x.get("edge", {}).get("ev", 0), reverse=True)


# ── Display ───────────────────────────────────────────────────────────────────

st.header("V7 EDGE PICKS")

if not results:
    st.warning("No matches found for the selected leagues and time window.")

for r in results:
    is_fallback = r["breakdown"].get("is_fallback")
    label = f"{r['match']} | {r['prediction']} ({round(r['confidence'], 2)}%)"
    if is_fallback:
        label += " ⚠ fallback data"

    with st.expander(label):
        st.write("Kickoff:", r["kickoff"])
        st.write(f"Prediction: {r['prediction']}")
        st.write(f"Confidence: {round(r['confidence'], 2)}%")
        st.write(f"EV: {round(r['edge'].get('ev', 0), 3)}")
        st.write(f"Kelly: {round(r['edge'].get('kelly', 0), 3)}")

        if is_fallback:
            st.warning("One or both teams used fallback stats — treat this pick with caution.")

        if r["edge"].get("value_bet"):
            st.success("VALUE BET")
        else:
            st.warning("No edge")

        with st.expander("Model details"):
            st.json(r["breakdown"])


# ── Auto ticket ───────────────────────────────────────────────────────────────

ticket = build_ticket(results)

st.header("Auto Ticket Builder")

if ticket and ticket.get("ticket"):
    for t in ticket["ticket"]:
        st.write(
            f"{t['match']} → {t['prediction']} "
            f"EV: {round(t.get('ev', 0), 3)} | Kelly: {round(t.get('kelly', 0), 3)}"
        )
    st.success(f"Avg Confidence: {round(ticket.get('avg_confidence', 0), 2)}%")
else:
    st.warning("No value bets today")
