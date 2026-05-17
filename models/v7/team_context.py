import logging
import time
from services.football_api import get_standings_for_leagues
from models.v7.team_resolver import resolve_team

logger = logging.getLogger(__name__)

# TTL-aware cache: {key: (data, expires_at)}
_CACHE_TTL = 3600
_cache: dict = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and time.monotonic() < entry[1]:
        return entry[0]
    return None


def _cache_set(key: str, value: dict) -> None:
    _cache[key] = (value, time.monotonic() + _CACHE_TTL)


def fetch_team_stats(team_name: str, league: str) -> dict:
    resolved_name = resolve_team(team_name)
    cache_key = f"{league}_{resolved_name}"

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        standings = get_standings_for_leagues([league])
    except Exception as e:
        logger.exception("Failed to fetch standings for %s: %s", league, e)
        return _fallback(team_name)

    table = standings.get(league, [])

    for team in table:
        if not isinstance(team, dict) or "team" not in team:
            continue

        api_name = team["team"].get("name", "")
        if resolve_team(api_name) != resolved_name:
            continue

        played = team.get("playedGames") or 1
        goals_for = team.get("goalsFor", 1)
        goals_against = team.get("goalsAgainst", 1)
        points = team.get("points", 0)

        stats = {
            "name": team_name,
            "position": team.get("position", 10),
            "played": played,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "won": team.get("won", 0),
            "draw": team.get("draw", 0),
            "lost": team.get("lost", 0),
            "points": points,
            "goals_for_pg": goals_for / played,
            "goals_against_pg": goals_against / played,
            "points_pg": points / played,
            "strength": (
                (goals_for / played) * 2.0
                - (goals_against / played)
                + (points / played) * 1.2
            ),
            "raw_strength": goals_for * 1.5 - goals_against + points * 0.3,
        }

        _cache_set(cache_key, stats)
        return stats

    logger.warning("Team '%s' (resolved: '%s') not found in %s standings — using fallback", team_name, resolved_name, league)
    fallback = _fallback(team_name)
    _cache_set(cache_key, fallback)
    return fallback


def _fallback(team_name: str) -> dict:
    return {
        "name": team_name,
        "position": 10,
        "played": 1,
        "goals_for": 1,
        "goals_against": 1,
        "won": 0,
        "draw": 0,
        "lost": 0,
        "points": 0,
        "goals_for_pg": 1.0,
        "goals_against_pg": 1.0,
        "points_pg": 0.0,
        "strength": 1.0,
        "raw_strength": 1.0,
        "is_fallback": True,
    }
