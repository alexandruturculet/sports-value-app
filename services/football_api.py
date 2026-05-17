import requests
import os
import logging
import time
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

API_KEY = os.getenv("football-data-api-key")

HEADERS = {"X-Auth-Token": API_KEY}

LEAGUE_CODES = {
    "Premier League": "PL",
    "La Liga": "PD",
    "Serie A": "SA",
    "Bundesliga": "BL1",
    "Ligue 1": "FL1",
    "Liga Portugal": "PPL",
    "Eredivisie": "DED",
    "Championship": "ELC",
    "Belgian Pro League": "BSA",
}

BASE_URL = "https://api.football-data.org/v4"

_SEARCH_LEAGUES = ["PL", "PD", "SA", "BL1", "FL1", "PPL", "DED"]


def make_request(url: str, max_retries: int = 3):
    delay = 1.0
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", delay))
                logger.warning("Rate limited by football-data.org — waiting %ds", retry_after)
                time.sleep(retry_after)
                delay *= 2
                continue

            response.raise_for_status()
            return response.json()

        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            if attempt < max_retries - 1:
                logger.warning("Connection error (attempt %d/%d): %s", attempt + 1, max_retries, e)
                time.sleep(delay)
                delay *= 2
                continue
            logger.error("API failed after %d retries: %s", max_retries, e)
            return None

        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error for %s: %s", url, e)
            return None

        except Exception as e:
            logger.exception("Unexpected error for %s: %s", url, e)
            return None

    return None


@st.cache_data(ttl=3600)
def get_league_scorers(league_code: str) -> list:
    """Return top scorers list for a competition (up to 100 entries)."""
    url = f"{BASE_URL}/competitions/{league_code}/scorers?limit=100"
    data = make_request(url)
    if not data or "scorers" not in data:
        logger.warning("No scorers data for league: %s", league_code)
        return []
    return data["scorers"]


def get_top_scorer_for_team(team_name: str, competition_code: str) -> tuple:
    """Return (player_name, player_name) for the team's leading scorer, or (None, None)."""
    scorers = get_league_scorers(competition_code)
    for entry in scorers:
        if entry.get("team", {}).get("name") == team_name:
            name = entry["player"]["name"]
            return name, name
    return None, None


@st.cache_data(ttl=3600)
def get_standings_for_leagues(leagues):
    all_standings = {}
    for league in leagues:
        league_code = LEAGUE_CODES.get(league, "PL")
        standings = get_league_standings(league_code)
        if standings:
            all_standings[league] = standings
    return all_standings


@st.cache_data(ttl=3600)
def get_league_standings(league_code: str):
    url = f"{BASE_URL}/competitions/{league_code}/standings"
    data = make_request(url)

    if not data or "standings" not in data:
        logger.warning("No standings data for league code: %s", league_code)
        return []

    standings = data["standings"][0]["table"]

    return [
        {
            "rank": team["position"],
            "team": {"name": team["team"]["name"]},
            "points": team["points"],
            "playedGames": team.get("playedGames", 1),
            "goalsFor": team.get("goalsFor", 0),
            "goalsAgainst": team.get("goalsAgainst", 0),
            "won": team.get("won", 0),
            "draw": team.get("draw", 0),
            "lost": team.get("lost", 0),
            "position": team["position"],
        }
        for team in standings
    ]


@st.cache_data(ttl=3600)
def get_premier_league_standings():
    return get_league_standings("PL")


@st.cache_data(ttl=1800)
def get_match_lineup(fixture_id) -> dict:
    """Return confirmed lineup from football-data.org /matches/{id} endpoint."""
    _empty = {"home": {"lineup": [], "bench": []}, "away": {"lineup": [], "bench": []}}
    if not fixture_id:
        return _empty
    url = f"{BASE_URL}/matches/{fixture_id}"
    data = make_request(url)
    if not data:
        return _empty
    home = data.get("homeTeam", {})
    away = data.get("awayTeam", {})
    return {
        "home": {"lineup": home.get("lineup", []), "bench": home.get("bench", [])},
        "away": {"lineup": away.get("lineup", []), "bench": away.get("bench", [])},
    }


@st.cache_data(ttl=3600)
def get_team_form(team_name: str):
    for league_code in _SEARCH_LEAGUES:
        url = f"{BASE_URL}/competitions/{league_code}/matches?status=FINISHED&limit=100"
        data = make_request(url)

        if not data or "matches" not in data:
            continue

        wins = 0
        match_count = 0

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
def get_team_goals(team_name: str):
    for league_code in _SEARCH_LEAGUES:
        url = f"{BASE_URL}/competitions/{league_code}/teams"
        data = make_request(url)

        if not data or "teams" not in data:
            continue

        for team in data["teams"]:
            if team["name"] == team_name:
                team_id = team["id"]
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
def get_team_last5_form(team_name: str):
    for league_code in _SEARCH_LEAGUES:
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
def get_h2h_matches(home_team_name: str, away_team_name: str):
    h2h_matches = []

    for league_code in _SEARCH_LEAGUES:
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
                    "away_goals": match["score"]["fullTime"]["away"],
                })

        if len(h2h_matches) >= 5:
            break

    return h2h_matches[:5]
