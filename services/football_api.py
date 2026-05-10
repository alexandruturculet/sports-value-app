import requests
import os
import streamlit as st
from dotenv import load_dotenv
import time

load_dotenv()

API_KEY = os.getenv("football-data-api-key")

HEADERS = {
    "X-Auth-Token": API_KEY
}

LEAGUE_CODES = {
    "Premier League": "PL",
    "La Liga": "PD",
    "Serie A": "SA",
    "Bundesliga": "BL1",
    "Ligue 1": "FL1",
    "Liga Portugal": "PPL",
    "Eredivisie": "DED",
    "Championship": "ELC",
    "Belgian Pro League": "BSA"
}

BASE_URL = "https://api.football-data.org/v4"


def make_request(url, max_retries=3):
    """Make API request with retry logic for SSL errors"""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            else:
                print(f"API Error after {max_retries} retries: {e}")
                return None
        except Exception as e:
            print(f"API Error: {e}")
            return None


@st.cache_data(ttl=3600)
def get_standings_for_leagues(leagues):
    """Get standings for specified leagues"""
    all_standings = {}

    for league in leagues:
        league_code = LEAGUE_CODES.get(league, "PL")
        standings = get_league_standings(league_code)
        if standings:
            all_standings[league] = standings

    return all_standings


@st.cache_data(ttl=3600)
def get_league_standings(league_code):
    """Fetch standings for a specific league"""
    url = f"{BASE_URL}/competitions/{league_code}/standings"

    data = make_request(url)

    if not data or "standings" not in data:
        return []

    standings = data["standings"][0]["table"]

    # Convert to match old format for compatibility
    converted = []
    for team in standings:
        converted.append({
            "rank": team["position"],
            "team": {"name": team["team"]["name"]},
            "points": team["points"]
        })

    return converted


@st.cache_data(ttl=3600)
def get_premier_league_standings():
    return get_league_standings("PL")


@st.cache_data(ttl=3600)
def get_team_form(team_name):
    """Get wins in last 5 matches"""

    # Get team ID by searching in all competitions
    for league_code in ["PL", "LA", "SA", "BL1", "FL1", "PPL", "DED"]:
        url = f"{BASE_URL}/competitions/{league_code}/matches?status=FINISHED&limit=100"
        data = make_request(url)

        if not data or "matches" not in data:
            continue

        wins = 0
        match_count = 0

        # Search through matches for this team
        for match in data["matches"]:
            home = match["homeTeam"]["name"]
            away = match["awayTeam"]["name"]

            if home == team_name or away == team_name:
                match_count += 1

                if match_count > 5:
                    break

                home_goals = match["score"]["fullTime"]["home"]
                away_goals = match["score"]["fullTime"]["away"]

                if home == team_name and home_goals > away_goals:
                    wins += 1
                elif away == team_name and away_goals > home_goals:
                    wins += 1

        if match_count > 0:
            return wins

    return 0


@st.cache_data(ttl=900)
def get_team_goals(team_name):
    """Get goals for and against for a team"""

    # Search through all leagues for team stats
    for league_code in ["PL", "LA", "SA", "BL1", "FL1", "PPL", "DED"]:
        url = f"{BASE_URL}/competitions/{league_code}/teams"
        data = make_request(url)

        if not data or "teams" not in data:
            continue

        for team in data["teams"]:
            if team["name"] == team_name:
                team_id = team["id"]

                # Get team's matches
                matches_url = f"{BASE_URL}/teams/{team_id}/matches?status=FINISHED&limit=100"
                matches_data = make_request(matches_url)

                if not matches_data or "matches" not in matches_data:
                    return (0, 0)

                goals_for = 0
                goals_against = 0

                for match in matches_data["matches"]:
                    home_goals = match["score"]["fullTime"]["home"]
                    away_goals = match["score"]["fullTime"]["away"]

                    if match["homeTeam"]["id"] == team_id:
                        goals_for += home_goals
                        goals_against += away_goals
                    else:
                        goals_for += away_goals
                        goals_against += home_goals

                return (goals_for, goals_against)

    return (0, 0)


@st.cache_data(ttl=900)
def get_team_last5_form(team_name):
    """Get W/D/L breakdown for team's last 5 matches"""
    for league_code in ["PL", "LA", "SA", "BL1", "FL1", "PPL", "DED"]:
        url = f"{BASE_URL}/competitions/{league_code}/matches?status=FINISHED&limit=100"
        data = make_request(url)

        if not data or "matches" not in data:
            continue

        match_count = 0
        results = []

        for match in data["matches"]:
            home = match["homeTeam"]["name"]
            away = match["awayTeam"]["name"]

            if home == team_name or away == team_name:
                match_count += 1
                if match_count > 5:
                    break

                home_goals = match["score"]["fullTime"]["home"]
                away_goals = match["score"]["fullTime"]["away"]

                if home == team_name:
                    if home_goals > away_goals:
                        results.append("W")
                    elif home_goals == away_goals:
                        results.append("D")
                    else:
                        results.append("L")
                else:
                    if away_goals > home_goals:
                        results.append("W")
                    elif away_goals == home_goals:
                        results.append("D")
                    else:
                        results.append("L")

        if match_count >= 5:
            return "-".join(results)

    return "N/A"


@st.cache_data(ttl=900)
def get_h2h_matches(home_team_name, away_team_name):
    """Get last 5 H2H matches between two teams with scores"""
    h2h_matches = []

    for league_code in ["PL", "LA", "SA", "BL1", "FL1", "PPL", "DED"]:
        url = f"{BASE_URL}/competitions/{league_code}/matches?status=FINISHED&limit=200"
        data = make_request(url)

        if not data or "matches" not in data:
            continue

        for match in data["matches"]:
            home = match["homeTeam"]["name"]
            away = match["awayTeam"]["name"]

            if (home == home_team_name and away == away_team_name) or \
               (home == away_team_name and away == home_team_name):
                h2h_matches.append({
                    "home": home,
                    "away": away,
                    "home_goals": match["score"]["fullTime"]["home"],
                    "away_goals": match["score"]["fullTime"]["away"]
                })

        if len(h2h_matches) >= 5:
            break

    h2h_matches = h2h_matches[:5]
    return h2h_matches
