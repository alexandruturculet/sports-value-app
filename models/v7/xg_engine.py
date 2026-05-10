def estimate_xg(team_stats, opponent_strength):

    gf = team_stats.get("goals_for", 1)
    ga = team_stats.get("goals_against", 1)

    played = team_stats.get("played", 0)

    # SAFETY FIX (CRITICAL)
    if played is None or played == 0:
        played = 1

    attack_power = gf / played

    defensive_factor = max(0.7, opponent_strength / 20)

    xg = (attack_power * 1.35) / defensive_factor

    return round(max(0.4, min(3.5, xg)), 2)