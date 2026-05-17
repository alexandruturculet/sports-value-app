import requests
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

API_KEY = os.getenv("ODDS_API_KEY")

LEAGUE_CODES = {
    "Premier League": "soccer_epl",
    "La Liga": "soccer_spain_la_liga",
    "Serie A": "soccer_italy_serie_a",
    "Bundesliga": "soccer_germany_bundesliga",
    "Ligue 1": "soccer_france_ligue_1",
    "Liga Portugal": "soccer_portugal",
    "Eredivisie": "soccer_netherlands_eredivisie",
}


def get_matches(leagues=None):
    if leagues is None:
        leagues = ["Premier League"]

    if not API_KEY:
        logger.warning("ODDS_API_KEY not set — skipping odds fetch")
        return []

    all_matches = []

    for league in leagues:
        sport_code = LEAGUE_CODES.get(league, "soccer_epl")
        url = f"https://api.the-odds-api.com/v4/sports/{sport_code}/odds"

        params = {
            "apiKey": API_KEY,
            "regions": "eu",
            "markets": "h2h,totals,halftime",
            "oddsFormat": "decimal",
        }

        try:
            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 429:
                logger.warning("[%s] Odds API rate limit hit", league)
                continue

            if response.status_code != 200:
                logger.error("[%s] Odds API error %s", league, response.status_code)
                continue

            matches = response.json()
            logger.info("[%s] Odds API returned %d matches", league, len(matches))
            all_matches.extend(matches)

        except Exception as e:
            logger.exception("[%s] Odds API request failed: %s", league, e)
            continue

    return all_matches
