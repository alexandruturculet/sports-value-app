# models/v7/team_context.py

from services.football_api import (
    get_standings_for_leagues
)


_cache = {}


def fetch_team_stats(team_name, league):

    cache_key = f"{league}_{team_name}"

    if cache_key in _cache:
        return _cache[cache_key]

    standings = get_standings_for_leagues([league])

    table = standings.get(league, [])

    for team in table:

        if team["team"]["name"] == team_name:

            stats = {
                "name": team_name,

                # REAL DATA
                "position": team.get("position", 10),
                "played": team.get("playedGames", 0),

                "goals_for": team.get("goalsFor", 1),
                "goals_against": team.get("goalsAgainst", 1),

                "won": team.get("won", 0),
                "draw": team.get("draw", 0),
                "lost": team.get("lost", 0),

                "points": team.get("points", 0),

                # REAL strength score
                "strength":
                    (
                        team.get("goalsFor", 1) * 1.5
                        -
                        team.get("goalsAgainst", 1)
                        +
                        team.get("points", 0) * 0.3
                    )
            }

            _cache[cache_key] = stats

            return stats

    # SAFE fallback
    return {
        "name": team_name,
        "goals_for": 1,
        "goals_against": 1,
        "strength": 1,
        "points": 0
    }