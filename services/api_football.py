import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

API_KEY = os.getenv("FOOTBALL_API_KEY")
BASE_URL = "https://v3.football.api-sports.io"

HEADERS = {"x-apisports-key": API_KEY}


def _get(url: str) -> dict:
    if not API_KEY:
        logger.warning("FOOTBALL_API_KEY not set — skipping API-Football call")
        return {}
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 429:
            logger.warning("API-Football rate limit hit for %s", url)
            return {}
        if r.status_code != 200:
            logger.error("API-Football error %s for %s", r.status_code, url)
            return {}
        return r.json()
    except Exception as e:
        logger.exception("API-Football request failed for %s: %s", url, e)
        return {}


def get_lineups(team_name: str, fixture_id) -> dict:
    if not fixture_id:
        return {"confirmed": [], "expected": []}

    data = _get(f"{BASE_URL}/fixtures/lineups?fixture={fixture_id}")
    response = data.get("response", [])
    return {"confirmed": response, "expected": []}


def get_injuries(team_name: str) -> list:
    if not team_name:
        return []

    data = _get(f"{BASE_URL}/injuries?team={team_name}")
    return data.get("response", [])
