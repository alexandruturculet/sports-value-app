"""
Unit tests for the v7 prediction engines and ticket evaluation logic.
Run with: pytest tests/
"""
import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.v7.xg_engine import estimate_xg
from models.v7.poisson_model import poisson, goal_distribution, poisson_signals
from models.v7.elo_model import get_elo, update_elo, get_elo_strength, DEFAULT_ELO, team_elo_cache


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


# ─── poisson_model ────────────────────────────────────────────────────────────

class TestPoisson:
    def test_probabilities_sum_to_one(self):
        lmbda = 1.5
        total = sum(poisson(lmbda, k) for k in range(20))
        assert abs(total - 1.0) < 1e-6

    def test_zero_goals_with_zero_lambda(self):
        # P(k=0 | lambda=0) should be 1
        assert abs(poisson(0.0001, 0) - 1.0) < 0.01

    def test_returns_float(self):
        result = poisson(1.5, 2)
        assert isinstance(result, float)

    def test_non_negative(self):
        for k in range(10):
            assert poisson(2.0, k) >= 0


class TestGoalDistribution:
    def test_returns_two_lists(self):
        home, away = goal_distribution(1.5, 1.2)
        assert isinstance(home, list) and isinstance(away, list)

    def test_each_list_has_six_elements(self):
        home, away = goal_distribution(1.5, 1.2)
        assert len(home) == 6
        assert len(away) == 6

    def test_all_probabilities_positive(self):
        home, away = goal_distribution(1.5, 1.2)
        assert all(p >= 0 for p in home + away)


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


# ─── elo_model ────────────────────────────────────────────────────────────────

class TestEloModel:
    def setup_method(self):
        team_elo_cache.clear()

    def test_unknown_team_returns_default(self):
        assert get_elo("Unknown FC") == DEFAULT_ELO

    def test_get_elo_strength_returns_expected_keys(self):
        result = get_elo_strength("Team A", "Team B")
        assert "home_elo" in result
        assert "away_elo" in result
        assert "elo_diff" in result

    def test_equal_teams_have_zero_diff(self):
        result = get_elo_strength("Team X", "Team Y")
        assert result["elo_diff"] == 0.0

    def test_winner_elo_increases(self):
        before = get_elo("Arsenal")
        update_elo("Arsenal", "Chelsea", goals_a=2, goals_b=0)
        assert get_elo("Arsenal") > before

    def test_loser_elo_decreases(self):
        before = get_elo("Chelsea")
        update_elo("Arsenal", "Chelsea", goals_a=2, goals_b=0)
        assert get_elo("Chelsea") < before

    def test_draw_moves_ratings_toward_each_other(self):
        # Give Arsenal higher ELO first
        team_elo_cache["Arsenal"] = 1600
        team_elo_cache["Chelsea"] = 1400
        update_elo("Arsenal", "Chelsea", goals_a=1, goals_b=1)
        # After a draw, the favourite (Arsenal) should lose points
        assert get_elo("Arsenal") < 1600
        assert get_elo("Chelsea") > 1400

    def test_elo_diff_sign_reflects_advantage(self):
        team_elo_cache["Strong FC"] = 1700
        team_elo_cache["Weak FC"] = 1300
        result = get_elo_strength("Strong FC", "Weak FC")
        assert result["elo_diff"] > 0

    def test_elo_conservation(self):
        # Total ELO should be conserved after update
        team_elo_cache["A"] = 1500
        team_elo_cache["B"] = 1500
        total_before = get_elo("A") + get_elo("B")
        update_elo("A", "B", goals_a=2, goals_b=1)
        total_after = get_elo("A") + get_elo("B")
        assert abs(total_before - total_after) < 1e-9


# ─── _pick_won (ticket evaluation) ───────────────────────────────────────────

# Import directly from the app module — we test the function in isolation
import importlib.util, types

def _load_pick_won():
    """Load _pick_won from value.s_app without executing Streamlit UI code."""
    src_path = os.path.join(os.path.dirname(__file__), "..", "value.s_app.py")
    src = open(src_path, encoding="utf-8").read()
    # Extract only the _pick_won function definition
    lines = src.splitlines()
    fn_lines = []
    inside = False
    for line in lines:
        if line.startswith("def _pick_won("):
            inside = True
        if inside:
            fn_lines.append(line)
            if inside and line == "" and len(fn_lines) > 2:
                break
            if inside and fn_lines and len(fn_lines) > 1 and line.startswith("def ") and not line.startswith("def _pick_won"):
                fn_lines.pop()
                break
    code = "\n".join(fn_lines)
    ns: dict = {}
    exec(compile(code, src_path, "exec"), ns)
    return ns["_pick_won"]

_pick_won = _load_pick_won()


class TestPickWon:
    # 1X2
    def test_1_home_win(self):
        assert _pick_won("1", 2, 0) is True

    def test_1_away_win(self):
        assert _pick_won("1", 0, 2) is False

    def test_1_draw(self):
        assert _pick_won("1", 1, 1) is False

    def test_2_away_win(self):
        assert _pick_won("2", 0, 1) is True

    def test_2_home_win(self):
        assert _pick_won("2", 2, 0) is False

    def test_x_draw(self):
        assert _pick_won("X", 1, 1) is True

    def test_x_home_win(self):
        assert _pick_won("X", 2, 1) is False

    # Double chance
    def test_1x_home_win(self):
        assert _pick_won("1X", 2, 0) is True

    def test_1x_draw(self):
        assert _pick_won("1X", 0, 0) is True

    def test_1x_away_win(self):
        assert _pick_won("1X", 0, 2) is False

    def test_x2_away_win(self):
        assert _pick_won("X2", 0, 1) is True

    def test_x2_draw(self):
        assert _pick_won("X2", 1, 1) is True

    def test_x2_home_win(self):
        assert _pick_won("X2", 2, 0) is False

    # BTTS
    def test_btts_both_score(self):
        assert _pick_won("BTTS", 1, 2) is True

    def test_btts_only_home(self):
        assert _pick_won("BTTS", 2, 0) is False

    def test_btts_only_away(self):
        assert _pick_won("BTTS", 0, 1) is False

    def test_btts_no_goals(self):
        assert _pick_won("BTTS", 0, 0) is False

    # Over/Under 2.5
    def test_over_2_5_three_goals(self):
        assert _pick_won("Over 2.5", 2, 1) is True

    def test_over_2_5_two_goals(self):
        assert _pick_won("Over 2.5", 2, 0) is False

    def test_under_2_5_two_goals(self):
        assert _pick_won("Under 2.5", 1, 1) is True

    def test_under_2_5_three_goals(self):
        assert _pick_won("Under 2.5", 2, 1) is False
