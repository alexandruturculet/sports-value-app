"""football-data.org API — standings, matches, scorers.

All functions are raw (no Streamlit cache) and thread-safe; callers cache at
the orchestrator level (see sections/sports.py). Free tier: 10 req/min —
keep parallelism capped via config.FOOTBALL_DATA_WORKERS.
"""
import requests
import os
import logging
import time
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

API_KEY = os.getenv("football-data-api-key")

HEADERS = {"X-Auth-Token": API_KEY}

BASE_URL = "https://api.football-data.org/v4"


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


# ── Raw fetch helpers (no Streamlit cache — safe to call from worker threads) ──

def fetch_league_scorers(league_code: str) -> list:
    """Top scorers list for a competition (up to 100 entries)."""
    url = f"{BASE_URL}/competitions/{league_code}/scorers?limit=100"
    data = make_request(url)
    if not data or "scorers" not in data:
        logger.warning("No scorers data for league: %s", league_code)
        return []
    return data["scorers"]


def fetch_league_standings(league_code: str) -> list:
    url = f"{BASE_URL}/competitions/{league_code}/standings"
    data = make_request(url)

    if not data or "standings" not in data:
        logger.warning("No standings data for league code: %s", league_code)
        return []

    # Leagues return [TOTAL, HOME, AWAY]; cups (e.g. World Cup) return one
    # TOTAL entry per group — concatenate all groups into a single table.
    standings = [
        team
        for block in data["standings"]
        if block.get("type", "TOTAL") == "TOTAL"
        for team in block.get("table", [])
    ]

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


def fetch_league_matches(league_code: str, date_from: str, date_to: str) -> list:
    """Scheduled/live matches for a competition within a date window."""
    url = f"{BASE_URL}/competitions/{league_code}/matches?dateFrom={date_from}&dateTo={date_to}"
    data = make_request(url)
    if not data or "matches" not in data:
        return []
    return [
        m for m in data["matches"]
        if m["status"] in ("SCHEDULED", "TIMED", "IN_PLAY", "LIVE")
    ]


def fetch_live_matches(league_codes: tuple) -> list:
    """Currently in-play matches across competitions — ONE request.
    /matches defaults to today's window; we filter live statuses client-side."""
    codes = ",".join(league_codes)
    data = make_request(f"{BASE_URL}/matches?competitions={codes}")
    if not data or "matches" not in data:
        return []
    out = []
    for m in data["matches"]:
        if m.get("status") not in ("IN_PLAY", "PAUSED", "LIVE"):
            continue
        score = m.get("score", {}).get("fullTime", {})
        out.append({
            "home": m["homeTeam"]["name"],
            "away": m["awayTeam"]["name"],
            "home_crest": m["homeTeam"].get("crest", ""),
            "away_crest": m["awayTeam"].get("crest", ""),
            "home_goals": score.get("home") if score.get("home") is not None else 0,
            "away_goals": score.get("away") if score.get("away") is not None else 0,
            "minute": m.get("minute"),
            "status": m.get("status", ""),
        })
    return out


def fetch_h2h(fixture_id: int, limit: int = 5) -> list:
    """Past head-to-head meetings for a fixture (football-data /head2head)."""
    data = make_request(f"{BASE_URL}/matches/{fixture_id}/head2head?limit={limit}")
    if not data or "matches" not in data:
        return []
    out = []
    for m in data["matches"]:
        if m.get("status") != "FINISHED":
            continue
        score = m.get("score", {}).get("fullTime", {})
        out.append({
            "date": (m.get("utcDate") or "")[:10],
            "home": m["homeTeam"]["name"],
            "away": m["awayTeam"]["name"],
            "home_goals": score.get("home"),
            "away_goals": score.get("away"),
            "competition": m.get("competition", {}).get("name", ""),
        })
    return out


def fetch_match_score(fixture_id: int) -> tuple[int, int] | None:
    """Returns (home_goals, away_goals) if finished, else None."""
    data = make_request(f"{BASE_URL}/matches/{fixture_id}")
    if not data or data.get("status") != "FINISHED":
        return None
    score = data.get("score", {}).get("fullTime", {})
    h, a = score.get("home"), score.get("away")
    if h is None or a is None:
        return None
    return (int(h), int(a))


def top_scorer_from_list(scorers: list, team_name: str) -> tuple:
    """Return (player_name, wiki_name, goals, assists) for the team's leading scorer."""
    for entry in scorers:
        if entry.get("team", {}).get("name") == team_name:
            name = entry["player"]["name"]
            goals = entry.get("goals", 0) or 0
            assists = entry.get("assists", 0) or 0
            return name, name, goals, assists
    return None, None, 0, 0
