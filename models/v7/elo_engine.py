def get_elo_strength(home_stats, away_stats):

    home_elo = 1500 + (home_stats["points"] * 3)
    away_elo = 1500 + (away_stats["points"] * 3)

    return {
        "home_elo": round(home_elo),
        "away_elo": round(away_elo),
        "elo_diff": round(home_elo - away_elo)
    }