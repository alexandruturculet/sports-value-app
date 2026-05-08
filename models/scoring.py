def implied_probability(odds):
    return 1 / odds


def get_motivation_score(rank):

    score = 0

    # Title race
    if rank <= 4:
        score += 3

    # European spots
    elif rank <= 7:
        score += 2

    # Relegation battle
    elif rank >= 16:
        score += 3

    # Mid-table with no objective
    else:
        score -= 1

    return score


def calculate_match_score(
    home_odds,
    motivation_score,
    form_score,
    attack_score,
    defense_score
):

    score = 0

    # odds logic
    if 1.50 <= home_odds <= 2.20:
        score += 3

    if home_odds < 1.30:
        score -= 2

    if home_odds > 2.80:
        score -= 1

    # motivation
    score += motivation_score

    # form
    score += form_score

    # attack strength
    score += attack_score

    # defensive weakness (important!)
    score += defense_score

    return score