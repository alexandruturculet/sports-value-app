import streamlit as st
from datetime import datetime, timedelta
import pytz

from services.odds_api import get_matches
from services.football_api import (
    get_premier_league_standings,
    get_standings_for_leagues,
    get_team_form,
    get_team_goals
)
from models.scoring import (
    implied_probability,
    calculate_match_score,
    get_motivation_score
)

def convert_to_romania_time(iso_time_string):
    """Convert UTC ISO time to Romania timezone"""
    utc_time = datetime.fromisoformat(iso_time_string.replace('Z', '+00:00'))
    romania_tz = pytz.timezone('Europe/Bucharest')
    local_time = utc_time.astimezone(romania_tz)
    return local_time

def format_match_time(iso_time_string):
    """Format time for display: 'Wed, 08 May 2024 - 15:30 EEST'"""
    local_time = convert_to_romania_time(iso_time_string)
    return local_time.strftime("%a, %d %b %Y - %H:%M %Z")

def filter_matches_by_date(matches, date_filter):
    """Filter matches based on selected date range"""
    now = datetime.now(pytz.UTC)

    if date_filter == "Today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    elif date_filter == "Tomorrow":
        tomorrow = now + timedelta(days=1)
        start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end = tomorrow.replace(hour=23, minute=59, second=59, microsecond=0)
    elif date_filter == "Next 7 days":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = (now + timedelta(days=7)).replace(hour=23, minute=59, second=59, microsecond=0)
    elif date_filter == "Next 14 days":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = (now + timedelta(days=14)).replace(hour=23, minute=59, second=59, microsecond=0)
    else:
        return matches

    filtered = [
        m for m in matches
        if start <= datetime.fromisoformat(m['commence_time'].replace('Z', '+00:00')) <= end
    ]
    return filtered

st.set_page_config(page_title="Value Bet Finder")

st.title("🔥 Value Bet Finder")

# Sidebar controls
with st.sidebar:
    st.header("⚙️ Filters")
    date_filter = st.selectbox(
        "Select prediction date range:",
        ["Today", "Tomorrow", "Next 7 days", "Next 14 days"]
    )

    selected_leagues = st.multiselect(
        "Select leagues:",
        ["Premier League", "La Liga", "Serie A"],
        default=["Premier League"]
    )

    if not selected_leagues:
        st.warning("Please select at least one league")
        selected_leagues = ["Premier League"]

with st.spinner("📊 Fetching standings..."):
    standings_dict = get_standings_for_leagues(selected_leagues)

st.header("📊 League Standings")

for league, standings in standings_dict.items():
    if standings:
        st.subheader(league)
        for team in standings[:5]:
            st.write(
                f"{team['rank']}. "
                f"{team['team']['name']} "
                f"- {team['points']} pts"
            )

# Flatten all standings into a single team rankings dict
team_rankings = {}
for league, standings in standings_dict.items():
    if standings:
        for team in standings:
            team_name = team["team"]["name"]
            rank = team["rank"]
            # Use the rank from any league (teams won't appear in multiple leagues)
            team_rankings[team_name] = rank

if not team_rankings:
    st.error("No standings found")

with st.spinner("⚽ Fetching matches..."):
    matches = get_matches(selected_leagues)

# Apply date filter
matches = filter_matches_by_date(matches, date_filter)

if not matches:

    st.error("No matches found")

else:

    best_picks = []

    for match in matches:

        home = match["home_team"]
        away = match["away_team"]

        bookmakers = match.get("bookmakers", [])

        if not bookmakers:
            continue

        markets = bookmakers[0].get("markets", [])

        if not markets:
            continue

        outcomes = markets[0].get("outcomes", [])

        home_odds = None

        for outcome in outcomes:
            if outcome["name"] == home:
                home_odds = outcome["price"]
                break

        if home_odds:

            rank = team_rankings.get(home, 10)

            motivation_score = get_motivation_score(rank)
            recent_wins = get_team_form(home)

            form_score = recent_wins

            goals_for, goals_against = get_team_goals(home)

            attack_score = goals_for / 10
            defense_score = goals_against / 10

            probability = implied_probability(home_odds)

            score = calculate_match_score(
                home_odds,
                motivation_score,
                form_score,
                attack_score,
                defense_score
            )

            if rank <= 4:

               reason = (
    f"{home} has strong attack "
    f"({goals_for} goals scored) and "
    f"weak defense (conceded {goals_against}). "
    f"Form: {recent_wins}/5 wins."
)

            elif rank >= 16:

                reason = (
    f"{home} fights to avoid relegation "
    f"and has {recent_wins} wins "
    "in the last 5 matches."
)

            else:

                reason = (
                    f"{home} has decent value "
                    "based on current odds."
                )

            best_picks.append({
                "match": f"{home} vs {away}",
                "pick": f"{home} Win",
                "odds": home_odds,
                "probability": probability,
                "score": score,
                "reason": reason,
                "kickoff_time": format_match_time(match["commence_time"])
            })

    best_picks = sorted(
        best_picks,
        key=lambda x: x["score"],
        reverse=True
    )

    st.header("🔥 Today's Best Picks")

    ticket_odds = 1

    top_picks = best_picks[:3]

    for pick in top_picks:

        ticket_odds *= pick["odds"]

        st.subheader(pick["match"])

        st.write(f"⏰ Kick-off: {pick['kickoff_time']}")
        st.write(f"Pick: {pick['pick']}")
        st.write(f"Odds: {pick['odds']}")
        st.write(
            f"Implied Probability: "
            f"{round(pick['probability'] * 100, 1)}%"
        )
        st.write(f"Confidence Score: {pick['score']}")

        st.write(
            f"Reason: {pick['reason']}"
        )

        st.divider()

    st.success(
        f"Total Ticket Odds: {round(ticket_odds, 2)}"
    )