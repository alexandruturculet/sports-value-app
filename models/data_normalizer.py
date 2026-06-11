# models/data_normalizer.py

LEAGUE_MAP = {
    # football-data.org returns these API names; map to sidebar display names
    "Primera Division": "La Liga",
    "Primeira Liga": "Liga Portugal",
    "FIFA World Cup": "World Cup 2026",
    # Ensure display names pass through unchanged even if used directly
    "La Liga": "La Liga",
    "Liga Portugal": "Liga Portugal",
    "World Cup 2026": "World Cup 2026",
}


def normalize_league(name: str) -> str:
    return LEAGUE_MAP.get(name, name)


# optional fallback stats registry
TEAM_STATS = {}


def register_team_stats(team_name, league, stats):
    TEAM_STATS[team_name] = {
        "league": league,
        "stats": stats
    }


def get_team_stats(team_name):
    return TEAM_STATS.get(team_name, None)