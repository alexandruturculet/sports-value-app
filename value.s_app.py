import streamlit as st

from services.odds_api import get_matches
from services.football_api import (
    get_premier_league_standings,
    get_team_form,
    get_team_goals
)
from models.scoring import (
    implied_probability,
    calculate_match_score,
    get_motivation_score
)

st.set_page_config(page_title="Value Bet Finder")

st.title("🔥 Value Bet Finder")
standings = get_premier_league_standings()

st.header("Premier League Standings")

if standings:

    for team in standings[:5]:

        st.write(
            f"{team['rank']}. "
            f"{team['team']['name']} "
            f"- {team['points']} pts"
        )

else:

    st.error("No standings found")

matches = get_matches()
team_rankings = {}

for team in standings:

    team_name = team["team"]["name"]
    rank = team["rank"]

    team_rankings[team_name] = rank

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
                "reason": reason
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