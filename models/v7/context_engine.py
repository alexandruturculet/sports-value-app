import logging
from services.api_football import get_lineups, get_injuries

logger = logging.getLogger(__name__)

_EMPTY_SIDE = {"lineup": [], "confirmed": [], "injuries": []}


def build_context(home_team: str, away_team: str, fixture_id=None) -> dict:
    if not home_team or not away_team:
        logger.warning("build_context called with empty team name(s)")
        return {"home": _EMPTY_SIDE.copy(), "away": _EMPTY_SIDE.copy()}

    try:
        home_lineups = get_lineups(home_team, fixture_id)
        away_lineups = get_lineups(away_team, fixture_id)
    except Exception as e:
        logger.warning("Lineup fetch failed: %s", e)
        home_lineups = away_lineups = {"confirmed": [], "expected": []}

    try:
        home_injuries = get_injuries(home_team)
        away_injuries = get_injuries(away_team)
    except Exception as e:
        logger.warning("Injury fetch failed: %s", e)
        home_injuries = away_injuries = []

    return {
        "home": {
            "lineup": home_lineups.get("expected", []),
            "confirmed": home_lineups.get("confirmed", []),
            "injuries": home_injuries,
        },
        "away": {
            "lineup": away_lineups.get("expected", []),
            "confirmed": away_lineups.get("confirmed", []),
            "injuries": away_injuries,
        },
    }
