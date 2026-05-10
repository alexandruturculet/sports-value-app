from .poisson_engine import poisson_signals


def select_market(xg_home, xg_away):

    poisson = poisson_signals(xg_home, xg_away)

    total = xg_home + xg_away
    diff = abs(xg_home - xg_away)

    if poisson["btts_prob"] > 0.52:
        return "BTTS"

    if poisson["over_2_5_prob"] > 0.50:
        return "Over 2.5"

    if total >= 2.6:
        return "Over 1.5"

    if diff < 0.3:
        return "1X"

    if xg_home > xg_away + 0.7:
        return "1"

    if xg_away > xg_home + 0.7:
        return "2"

    return "1X"