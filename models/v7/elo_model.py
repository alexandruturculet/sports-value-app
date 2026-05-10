import math

# =========================
# INITIAL ELO DEFAULT
# =========================

DEFAULT_ELO = 1500


team_elo_cache = {}


def get_elo(team_name):

    return team_elo_cache.get(team_name, DEFAULT_ELO)


def update_elo(team_a, team_b, goals_a, goals_b, k=20):

    elo_a = get_elo(team_a)
    elo_b = get_elo(team_b)

    # expected score
    exp_a = 1 / (1 + 10 ** ((elo_b - elo_a) / 400))
    exp_b = 1 - exp_a

    # actual score
    if goals_a > goals_b:
        score_a, score_b = 1, 0
    elif goals_a < goals_b:
        score_a, score_b = 0, 1
    else:
        score_a, score_b = 0.5, 0.5

    team_elo_cache[team_a] = elo_a + k * (score_a - exp_a)
    team_elo_cache[team_b] = elo_b + k * (score_b - exp_b)


def get_elo_strength(home, away):

    h = get_elo(home)
    a = get_elo(away)

    diff = (h - a) / 400

    return {
        "home_elo": h,
        "away_elo": a,
        "elo_diff": diff
    }