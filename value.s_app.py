import streamlit as st
from datetime import datetime, timedelta, timezone

from services.football_api import (
    get_standings_for_leagues,
    make_request,
    BASE_URL,
    LEAGUE_CODES
)

from models.team_strength_model import get_team_strength
from models.data_normalizer import register_team_stats, normalize_league

from models.v7.prediction_engine import (
    generate_prediction,
    calculate_risk
)

from models.v7.ticket_engine import build_ticket


# =========================
# CONFIG
# =========================

st.set_page_config(
    page_title="V7 EDGE ENGINE",
    layout="wide"
)

st.title("🔥 V7 REAL EDGE ENGINE")


# =========================
# MATCH FETCH
# =========================

@st.cache_data(ttl=3600)
def get_matches(leagues):

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
            if m["status"] not in ["SCHEDULED", "TIMED", "IN_PLAY", "LIVE"]:
                continue

            all_matches.append(m)

    return all_matches


# =========================
# SIDEBAR
# =========================

with st.sidebar:
    leagues = st.multiselect(
        "Leagues",
        ["Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1"],
        default=["Premier League"]
    )


# =========================
# LOAD DATA
# =========================

standings = get_standings_for_leagues(leagues)
matches = get_matches(leagues)

results = []


# =========================
# ENGINE LOOP
# =========================

now_utc = datetime.now(timezone.utc)

today = now_utc.date()

start_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
end_day = now_utc.replace(hour=23, minute=59, second=59, microsecond=999999)


for m in matches:

    # normalize kickoff
    match_dt = datetime.fromisoformat(
        m["utcDate"].replace("Z", "+00:00")
    ).astimezone(timezone.utc)

    # =========================
    # 🔥 FIX: STRICT TODAY FILTER
    # =========================
    if not (start_day <= match_dt <= end_day):
        continue

    home_name = m["homeTeam"]["name"]
    away_name = m["awayTeam"]["name"]

    league = normalize_league(m["competition"]["name"])

    league_data = standings.get(league) or standings.get(m["competition"]["name"], [])

    home = get_team_strength(league_data, home_name)
    away = get_team_strength(league_data, away_name)

    register_team_stats(home_name, league, home)
    register_team_stats(away_name, league, away)

    prediction, reason, breakdown, edge, confidence = generate_prediction(
    home_name,
    away_name,
    league
)

    risk = calculate_risk(confidence)

    results.append({
        "match": f"{home_name} vs {away_name}",
        "kickoff": match_dt.strftime("%d-%m-%Y %H:%M UTC"),
        "prediction": prediction,
        "confidence": confidence,
        "risk": risk,
        "reason": reason,
        "breakdown": breakdown,
        "edge": edge
    })


# =========================
# SORT SAFE
# =========================

results = sorted(
    results,
    key=lambda x: x.get("edge", {}).get("ev", 0),
    reverse=True
)


# =========================
# DISPLAY
# =========================

st.header("🔥 V7 EDGE PICKS")

for r in results[:20]:

    with st.expander(f"{r['match']} | {r['prediction']} ({round(r['confidence'],2)}%)"):

        st.write("🕒 Kickoff:", r["kickoff"])
        st.write(f"🎯 Prediction: {r['prediction']}")
        st.write(f"⚡ Confidence: {round(r['confidence'], 2)}%")
        st.write(f"⚠️ Risk: {r['risk']}")

        st.write(f"📊 EV: {round(r['edge'].get('ev', 0), 3)}")
        st.write(f"💰 Kelly: {round(r['edge'].get('kelly', 0), 3)}")

        if r["edge"].get("value_bet"):
            st.success("✔ VALUE BET")
        else:
            st.warning("No edge")

        with st.expander("📊 Model details"):
            st.json(r["breakdown"])


# =========================
# AUTO TICKET
# =========================

ticket = build_ticket(results)

st.header("💰 Auto Ticket Builder")

if ticket and ticket.get("ticket"):

    for t in ticket["ticket"]:
        st.write(
            f"✔ {t['match']} → {t['prediction']} "
            f"EV: {round(t.get('ev', 0), 3)} | Kelly: {round(t.get('kelly', 0), 3)}"
        )

    st.success(f"Avg Confidence: {round(ticket.get('avg_confidence', 0), 2)}%")

else:
    st.warning("No value bets today")