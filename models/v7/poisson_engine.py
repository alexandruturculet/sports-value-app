import math

def poisson_prob(lmbda, k):
    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)


def poisson_signals(xg_home, xg_away):

    home_no_goal = math.exp(-xg_home)
    away_no_goal = math.exp(-xg_away)

    btts = (1 - home_no_goal) * (1 - away_no_goal)

    total = xg_home + xg_away

    over_25 = 1 - (
        poisson_prob(total, 0) +
        poisson_prob(total, 1) +
        poisson_prob(total, 2)
    )

    return {
        "btts_prob": round(btts, 3),
        "over_2_5_prob": round(over_25, 3)
    }