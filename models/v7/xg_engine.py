def estimate_xg(team_stats, opponent_strength):

    gf = team_stats["goals_for"]
    ga = team_stats["goals_against"]

    attack_power = gf / max(team_stats["played"], 1)

    defensive_factor = max(0.7, opponent_strength / 20)

    xg = attack_power * 1.35 / defensive_factor

    return round(max(0.4, min(3.5, xg)), 2)