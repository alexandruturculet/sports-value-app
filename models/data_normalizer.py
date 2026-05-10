# models/data_normalizer.py

LEAGUE_MAP = {
    "Premier League": "Premier League",
    "La Liga": "Primera Division",
    "Serie A": "Serie A",
    "Bundesliga": "Bundesliga",
    "Ligue 1": "Ligue 1"
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