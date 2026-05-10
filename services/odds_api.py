import requests
import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")

# Sports API codes for different leagues
LEAGUE_CODES = {
    "Premier League": "soccer_epl",
    "La Liga": "soccer_spain_la_liga",
    "Serie A": "soccer_italy_serie_a",
    "Bundesliga": "soccer_germany_bundesliga",
    "Ligue 1": "soccer_france_ligue_1",
    "Liga Portugal": "soccer_portugal",
    "Eredivisie": "soccer_netherlands_eredivisie"
}

def get_matches(leagues=None):
    """
    Fetch matches from specified leagues
    Args:
        leagues: List of league names (e.g., ["Premier League", "La Liga"])
                 If None, defaults to Premier League only
    """
    if leagues is None:
        leagues = ["Premier League"]

    print(f"\n=== ODDS API DEBUG ===")
    print(f"API Key set: {bool(API_KEY)}")
    print(f"API Key value: {API_KEY[:20]}..." if API_KEY else "NO KEY")
    print(f"Leagues requested: {leagues}")

    all_matches = []

    for league in leagues:
        sport_code = LEAGUE_CODES.get(league, "soccer_epl")
        url = f"https://api.the-odds-api.com/v4/sports/{sport_code}/odds"

        params = {
            "apiKey": API_KEY,
            "regions": "eu",
            "markets": "h2h,totals,halftime",
            "oddsFormat": "decimal"
        }

        print(f"\n[{league}] Fetching: {url}")
        print(f"[{league}] Sport code: {sport_code}")
        try:
            response = requests.get(url, params=params, timeout=10)
            print(f"[{league}] Status: {response.status_code}")
            print(f"[{league}] Headers: {response.headers}")
            print(f"[{league}] Response: {response.text[:500]}")

            if response.status_code != 200:
                print(f"[{league}] Error response: {response.text[:200]}")
                continue

            matches = response.json()
            print(f"[{league}] Matches returned: {len(matches)}")
            if matches:
                print(f"[{league}] Sample match: {matches[0].get('home_team')} vs {matches[0].get('away_team')}")
                all_matches.extend(matches)
        except Exception as e:
            print(f"[{league}] Exception: {str(e)}")
            continue

    print(f"Total matches collected: {len(all_matches)}\n")
    return all_matches