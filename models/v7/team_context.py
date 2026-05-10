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

        # SAFETY: structure guard
        if not isinstance(team, dict):
            continue

        if "team" not in team:
            continue

        if team["team"].get("name") != team_name:
            continue

        played = team.get("playedGames", 1)
        if played is None or played == 0:
            played = 1

        goals_for = team.get("goalsFor", 1)
        goals_against = team.get("goalsAgainst", 1)

        points = team.get("points", 0)

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

            "points": points,

            # PER GAME METRICS (IMPORTANT FOR V7 STABILITY)
            "goals_for_pg": goals_for / played,
            "goals_against_pg": goals_against / played,
            "points_pg": points / played,

            # REALISTIC TEAM STRENGTH MODEL
            "strength": (
                (goals_for / played) * 2.0
                - (goals_against / played)
                + (points / played) * 1.2
            ),

            # DEBUG RAW SCORE (optional analysis)
            "raw_strength": (
                goals_for * 1.5
                - goals_against
                + points * 0.3
            )
        }

        _cache[cache_key] = stats

        return stats

    # =========================
    # SAFE FALLBACK (CRITICAL)
    # =========================

    fallback = {
        "name": team_name,

        "position": 10,
        "played": 1,

        "goals_for": 1,
        "goals_against": 1,

        "won": 0,
        "draw": 0,
        "lost": 0,

        "points": 0,

        "goals_for_pg": 1,
        "goals_against_pg": 1,
        "points_pg": 0,

        "strength": 1,
        "raw_strength": 1
    }

    _cache[cache_key] = fallback

    return fallback