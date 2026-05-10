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


def predict_btts_probability(home_goals_avg, away_goals_avg):
    """Probability both teams score at least 1 goal using Poisson distribution"""
    from scipy.stats import poisson

    home_score_prob = 1 - poisson.cdf(0, home_goals_avg)
    away_score_prob = 1 - poisson.cdf(0, away_goals_avg)

    return home_score_prob * away_score_prob


def predict_over_under_probability(home_goals_avg, away_goals_avg, threshold=1.5):
    """Probability total goals exceed threshold using Poisson distribution"""
    from scipy.stats import poisson

    expected_goals = home_goals_avg + away_goals_avg
    return 1 - poisson.cdf(threshold - 0.5, expected_goals)


def predict_first_half_probability(home_goals_avg, away_goals_avg):
    """Probability Over 0.5 goals in first half (35% of season average)"""
    from scipy.stats import poisson

    home_fh_avg = home_goals_avg * 0.35
    away_fh_avg = away_goals_avg * 0.35
    expected_fh_goals = home_fh_avg + away_fh_avg

    return 1 - poisson.cdf(0, expected_fh_goals)


def predict_second_half_probability(home_goals_avg, away_goals_avg):
    """Probability Over 0.5 goals in second half (65% of season average)"""
    from scipy.stats import poisson

    home_sh_avg = home_goals_avg * 0.65
    away_sh_avg = away_goals_avg * 0.65
    expected_sh_goals = home_sh_avg + away_sh_avg

    return 1 - poisson.cdf(0, expected_sh_goals)


def calculate_btts_score(btts_probability, home_attack, away_attack):
    """Calculate confidence score for BTTS prediction"""
    score = 0

    if 0.4 <= btts_probability <= 0.7:
        score += 3

    if home_attack >= 1 and away_attack >= 1:
        score += 2

    score += btts_probability * 10

    return score


def calculate_over_under_score(ou_probability, threshold):
    """Calculate confidence score for Over/Under prediction"""
    score = 0

    if 0.35 <= ou_probability <= 0.65:
        score += 2

    if threshold == 1.5 and 0.4 <= ou_probability <= 0.6:
        score += 2

    score += ou_probability * 8

    return score