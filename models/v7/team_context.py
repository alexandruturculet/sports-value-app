# models/v7/team_context.py

from services.football_api import get_standings_for_leagues

_cache = {}


def fetch_team_stats(team_name, league):

    cache_key = f"{league}_{team_name}"

    if cache_key in _cache:
        return _cache[cache_key]

    standings = get_standings_for_leagues([league])

    table = standings.get(league, [])

    for team in table:

        if team["team"]["name"] == team_name:

            played = team.get("playedGames", 1)

            # SAFETY FIX (CRITICAL)
            if played is None or played == 0:
                played = 1

            goals_for = team.get("goalsFor", 1)
            goals_against = team.get("goalsAgainst", 1)

            stats = {
                "name": team_name,

                # BASIC STATS
                "position": team.get("position", 10),
                "played": played,

                "goals_for": goals_for,
                "goals_against": goals_against,

                "won": team.get("won", 0),
                "draw": team.get("draw", 0),
                "lost": team.get("lost", 0),

                "points": team.get("points", 0),

                # NORMALIZED FEATURES (IMPORTANT FOR STABILITY)
                "goals_for_pg": goals_for / played,
                "goals_against_pg": goals_against / played,
                "points_pg": team.get("points", 0) / played if played else 0,

                # REAL strength score (smoothed)
                "strength": (
                    (goals_for / played) * 2.0
                    - (goals_against / played)
                    + (team.get("points", 0) / played) * 1.2
                ),

                # optional debug
                "raw_strength": (
                    goals_for * 1.5
                    - goals_against
                    + team.get("points", 0) * 0.3
                )
            }

            _cache[cache_key] = stats

            return stats

    # SAFE fallback (VERY IMPORTANT FIX)
    fallback = {
        "name": team_name,
        "played": 1,

        "goals_for": 1,
        "goals_against": 1,

        "goals_for_pg": 1,
        "goals_against_pg": 1,
        "points_pg": 0,

        "strength": 1,
        "points": 0
    }

    _cache[cache_key] = fallback

    return fallback