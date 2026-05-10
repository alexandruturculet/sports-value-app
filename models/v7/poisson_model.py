import math


# =========================
# POISSON FUNCTION
# =========================

def poisson(lmbda, k):

    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)


# =========================
# GOAL PROBABILITY MODEL
# =========================

def goal_distribution(xg_home, xg_away):

    home_probs = [poisson(xg_home, i) for i in range(6)]
    away_probs = [poisson(xg_away, i) for i in range(6)]

    return home_probs, away_probs


# =========================
# MARKET SIGNALS
# =========================

def poisson_signals(xg_home, xg_away):

    home_probs, away_probs = goal_distribution(xg_home, xg_away)

    home_score_prob = sum(home_probs[1:])
    away_score_prob = sum(away_probs[1:])

    btts_prob = home_score_prob * away_score_prob

    over_2_5 = 0

    for i in range(3, 6):
        for j in range(0, 6):
            if i + j >= 3:
                over_2_5 += home_probs[i] * away_probs[j]

    return {
        "btts_prob": round(btts_prob, 3),
        "over_2_5_prob": round(over_2_5, 3)
    }