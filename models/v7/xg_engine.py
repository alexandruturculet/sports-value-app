def estimate_xg(team_stats, opponent_strength):

    if not isinstance(team_stats, dict):
        return 1.0

    gf = team_stats.get("goals_for", 1)
    ga = team_stats.get("goals_against", 1)

    played = team_stats.get("played")

    # SAFE NORMALIZATION (CRITICAL FIX)
    if played is None or played == 0:
        played = 1

    # per game values (REALISTIC xG BASE)
    attack = gf / played
    defense = ga / played

    opponent_factor = max(0.7, opponent_strength / 20)

    xg = (attack * 1.4) / opponent_factor

    # slight defensive correction
    xg = xg * (1.05 - (defense * 0.15))

    return round(max(0.4, min(3.2, xg)), 2)