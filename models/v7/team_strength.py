# models/v7/team_strength.py

def compute_team_strength(team_stats: dict):

    gf = team_stats.get("goals_for", 1.0)
    ga = team_stats.get("goals_against", 1.0)

    home_factor = team_stats.get("home_factor", 1.0)
    away_factor = team_stats.get("away_factor", 1.0)

    attack = gf / 1.5
    defense = 1.5 / (ga + 0.1)

    strength = (attack * 0.6 + defense * 0.4)

    return round(min(max(strength * home_factor * away_factor, 0.3), 2.2), 3)