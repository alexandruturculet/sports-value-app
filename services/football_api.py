import requests
import os

from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("FOOTBALL_API_KEY")

HEADERS = {
    "x-apisports-key": API_KEY
}


def get_premier_league_standings():

    url = (
        "https://v3.football.api-sports.io/"
        "standings?league=39&season=2024"
    )

    response = requests.get(
        url,
        headers=HEADERS
    )

    data = response.json()

    print(data)

    if not data["response"]:
        return []

    standings = (
        data["response"][0]["league"]["standings"][0]
    )

    return standings
def get_team_form(team_name):

    url = (
        "https://v3.football.api-sports.io/"
        "teams?search="
        f"{team_name}"
    )

    response = requests.get(
        url,
        headers=HEADERS
    )

    data = response.json()

    if not data["response"]:
        return 0

    team_id = data["response"][0]["team"]["id"]

    fixtures_url = (
        "https://v3.football.api-sports.io/"
        f"fixtures?team={team_id}&last=5"
    )

    fixtures_response = requests.get(
        fixtures_url,
        headers=HEADERS
    )

    fixtures_data = fixtures_response.json()

    if not fixtures_data["response"]:
        return 0

    wins = 0

    for match in fixtures_data["response"]:

        teams = match["teams"]

        home_team = teams["home"]["name"]
        away_team = teams["away"]["name"]

        goals = match["goals"]

        home_goals = goals["home"]
        away_goals = goals["away"]

        if (
            home_team == team_name
            and home_goals > away_goals
        ):
            wins += 1

        elif (
            away_team == team_name
            and away_goals > home_goals
        ):
            wins += 1

    return wins
def get_team_goals(team_name):

    url = (
        "https://v3.football.api-sports.io/"
        "teams?search="
        f"{team_name}"
    )

    response = requests.get(url, headers=HEADERS)
    data = response.json()

    if not data["response"]:
        return (0, 0)

    team_id = data["response"][0]["team"]["id"]

    stats_url = (
        "https://v3.football.api-sports.io/"
        f"teams/statistics?team={team_id}&league=39&season=2024"
    )

    stats_response = requests.get(stats_url, headers=HEADERS)
    stats = stats_response.json()

    if not stats["response"]:
        return (0, 0)

    goals_for = stats["response"]["goals"]["for"]["total"]["total"]
    goals_against = stats["response"]["goals"]["against"]["total"]["total"]

    return (goals_for, goals_against)