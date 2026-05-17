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
        "competition_code": competition_code,
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


# ── Render helper ─────────────────────────────────────────────────────────────

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
        home_player, home_wiki = get_top_scorer_for_team(r["home"], r["competition_code"])
        away_player, away_wiki = get_top_scorer_for_team(r["away"], r["competition_code"])

        if home_player or away_player:
            col_home, col_spacer, col_away = st.columns([2, 1, 2])

            with col_home:
                if home_player:
                    st.caption(f"Top scorer — {r['home']}")
                    st.markdown(f"**{home_player}**")
                    img = get_player_image_url(home_wiki)
                    if img:
                        st.image(img, width=160)

            with col_away:
                if away_player:
                    st.caption(f"Top scorer — {r['away']}")
                    st.markdown(f"**{away_player}**")
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

        # Starting XI + Absents
        st.divider()
        ctx = r["breakdown"].get("context", {})
        home_ctx = ctx.get("home", {})
        away_ctx = ctx.get("away", {})

        home_confirmed = home_ctx.get("confirmed", [])
        away_confirmed = away_ctx.get("confirmed", [])
        home_lineup = home_ctx.get("lineup", [])
        away_lineup = away_ctx.get("lineup", [])
        home_injuries = home_ctx.get("injuries", [])
        away_injuries = away_ctx.get("injuries", [])

        st.markdown("**Probable Starting XI**")
        xi_home, xi_away = st.columns(2)

        def _render_xi(col, team_name, confirmed, lineup, injuries):
            with col:
                st.markdown(f"**{team_name}**")
                # API-Football confirmed lineup format
                shown = False
                for entry in confirmed:
                    if not isinstance(entry, dict):
                        continue
                    start_xi = entry.get("startXI", [])
                    if not start_xi:
                        continue
                    shown = True
                    formation = entry.get("formation", "")
                    if formation:
                        st.caption(f"Formation: {formation}")
                    for slot in start_xi:
                        pl = slot.get("player", {})
                        num = pl.get("number", "")
                        name = pl.get("name", "")
                        pos = pl.get("pos", "")
                        st.write(f"{num}. {name}" + (f" ({pos})" if pos else ""))
                if not shown:
                    if lineup:
                        for name in lineup:
                            st.write(f"• {name}")
                    else:
                        st.caption("Lineup not yet announced")

                if injuries:
                    st.markdown("**Absents / Injuries:**")
                    for inj in injuries:
                        pl_name = inj.get("player", {}).get("name", "Unknown") if isinstance(inj, dict) else str(inj)
                        reason = inj.get("injury", {}).get("reason", "") if isinstance(inj, dict) else ""
                        st.write(f"❌ {pl_name}" + (f" — {reason}" if reason else ""))
                else:
                    st.caption("No injury reports available")

        _render_xi(xi_home, r["home"], home_confirmed, home_lineup, home_injuries)
        _render_xi(xi_away, r["away"], away_confirmed, away_lineup, away_injuries)

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
