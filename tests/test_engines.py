"""
Unit tests for the v7 prediction engines and ticket evaluation logic.
Run with: pytest tests/
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.v7.xg_engine import estimate_xg
from models.v7.poisson_engine import poisson_prob, poisson_signals
from models.v7.elo_engine import get_elo_strength
from models.v7.ticket_eval import pick_won


# ─── xg_engine ────────────────────────────────────────────────────────────────

class TestEstimateXg:
    def test_returns_float(self):
        stats = {"goals_for": 40, "goals_against": 20, "played": 20}
        result = estimate_xg(stats, opponent_strength=10)
        assert isinstance(result, float)

    def test_clamped_to_minimum(self):
        # Very weak attack should still return at least 0.4
        stats = {"goals_for": 1, "goals_against": 50, "played": 30}
        result = estimate_xg(stats, opponent_strength=20)
        assert result >= 0.4

    def test_clamped_to_maximum(self):
        # Very strong attack against weak opponent stays <= 3.2
        stats = {"goals_for": 100, "goals_against": 5, "played": 20}
        result = estimate_xg(stats, opponent_strength=1)
        assert result <= 3.2

    def test_invalid_stats_returns_default(self):
        assert estimate_xg(None, opponent_strength=10) == 1.0
        assert estimate_xg("bad", opponent_strength=10) == 1.0

    def test_zero_played_does_not_crash(self):
        stats = {"goals_for": 10, "goals_against": 5, "played": 0}
        result = estimate_xg(stats, opponent_strength=10)
        assert 0.4 <= result <= 3.2

    def test_none_played_does_not_crash(self):
        stats = {"goals_for": 10, "goals_against": 5, "played": None}
        result = estimate_xg(stats, opponent_strength=10)
        assert 0.4 <= result <= 3.2

    def test_stronger_attack_gives_higher_xg(self):
        weak = {"goals_for": 10, "goals_against": 10, "played": 10}
        strong = {"goals_for": 30, "goals_against": 10, "played": 10}
        assert estimate_xg(strong, 10) > estimate_xg(weak, 10)

    def test_stronger_opponent_reduces_xg(self):
        stats = {"goals_for": 20, "goals_against": 10, "played": 10}
        xg_vs_easy = estimate_xg(stats, opponent_strength=5)
        xg_vs_hard = estimate_xg(stats, opponent_strength=20)
        assert xg_vs_easy > xg_vs_hard


# ─── poisson_engine ───────────────────────────────────────────────────────────

class TestPoissonProb:
    def test_probabilities_sum_to_one(self):
        lmbda = 1.5
        total = sum(poisson_prob(lmbda, k) for k in range(20))
        assert abs(total - 1.0) < 1e-6

    def test_zero_goals_with_zero_lambda(self):
        # P(k=0 | lambda≈0) should be ~1
        assert abs(poisson_prob(0.0001, 0) - 1.0) < 0.01

    def test_returns_float(self):
        result = poisson_prob(1.5, 2)
        assert isinstance(result, float)

    def test_non_negative(self):
        for k in range(10):
            assert poisson_prob(2.0, k) >= 0


class TestPoissonSignals:
    def test_returns_dict_with_expected_keys(self):
        result = poisson_signals(1.5, 1.2)
        assert "btts_prob" in result
        assert "over_2_5_prob" in result

    def test_btts_prob_between_0_and_1(self):
        result = poisson_signals(1.5, 1.2)
        assert 0 <= result["btts_prob"] <= 1

    def test_over_2_5_prob_between_0_and_1(self):
        result = poisson_signals(1.5, 1.2)
        assert 0 <= result["over_2_5_prob"] <= 1

    def test_high_xg_gives_high_btts(self):
        low = poisson_signals(0.5, 0.5)
        high = poisson_signals(2.5, 2.5)
        assert high["btts_prob"] > low["btts_prob"]

    def test_high_xg_gives_high_over_2_5(self):
        low = poisson_signals(0.5, 0.5)
        high = poisson_signals(2.5, 2.5)
        assert high["over_2_5_prob"] > low["over_2_5_prob"]


# ─── elo_engine ───────────────────────────────────────────────────────────────

class TestEloEngine:
    def test_returns_expected_keys(self):
        result = get_elo_strength({"points": 30}, {"points": 30})
        assert "home_elo" in result
        assert "away_elo" in result
        assert "elo_diff" in result

    def test_equal_points_give_zero_diff(self):
        result = get_elo_strength({"points": 30}, {"points": 30})
        assert result["elo_diff"] == 0

    def test_more_points_give_positive_diff(self):
        result = get_elo_strength({"points": 50}, {"points": 20})
        assert result["elo_diff"] > 0

    def test_fewer_points_give_negative_diff(self):
        result = get_elo_strength({"points": 10}, {"points": 40})
        assert result["elo_diff"] < 0

    def test_diff_consistent_with_elos(self):
        result = get_elo_strength({"points": 45}, {"points": 28})
        assert result["elo_diff"] == result["home_elo"] - result["away_elo"]


# ─── pick_won (ticket evaluation) ─────────────────────────────────────────────

class TestPickWon:
    # 1X2
    def test_1_home_win(self):
        assert pick_won("1", 2, 0) is True

    def test_1_away_win(self):
        assert pick_won("1", 0, 2) is False

    def test_1_draw(self):
        assert pick_won("1", 1, 1) is False

    def test_2_away_win(self):
        assert pick_won("2", 0, 1) is True

    def test_2_home_win(self):
        assert pick_won("2", 2, 0) is False

    def test_x_draw(self):
        assert pick_won("X", 1, 1) is True

    def test_x_home_win(self):
        assert pick_won("X", 2, 1) is False

    # Double chance
    def test_1x_home_win(self):
        assert pick_won("1X", 2, 0) is True

    def test_1x_draw(self):
        assert pick_won("1X", 0, 0) is True

    def test_1x_away_win(self):
        assert pick_won("1X", 0, 2) is False

    def test_x2_away_win(self):
        assert pick_won("X2", 0, 1) is True

    def test_x2_draw(self):
        assert pick_won("X2", 1, 1) is True

    def test_x2_home_win(self):
        assert pick_won("X2", 2, 0) is False

    # BTTS
    def test_btts_both_score(self):
        assert pick_won("BTTS", 1, 2) is True

    def test_btts_only_home(self):
        assert pick_won("BTTS", 2, 0) is False

    def test_btts_only_away(self):
        assert pick_won("BTTS", 0, 1) is False

    def test_btts_no_goals(self):
        assert pick_won("BTTS", 0, 0) is False

    # Over/Under 2.5
    def test_over_2_5_three_goals(self):
        assert pick_won("Over 2.5", 2, 1) is True

    def test_over_2_5_two_goals(self):
        assert pick_won("Over 2.5", 2, 0) is False

    def test_under_2_5_two_goals(self):
        assert pick_won("Under 2.5", 1, 1) is True

    def test_under_2_5_three_goals(self):
        assert pick_won("Under 2.5", 2, 1) is False
