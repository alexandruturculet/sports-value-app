import logging
from models.v7.xg_engine import estimate_xg
from models.v7.elo_engine import get_elo_strength
from models.v7.form_engine import get_form
from models.v7.poisson_engine import poisson_signals
from models.v7.team_context import fetch_team_stats
from models.v7.context_engine import build_context

logger = logging.getLogger(__name__)

# ── Market selection thresholds ──────────────────────────────────────────────
XG_STRONG_DIFF = 0.65       # xG gap required to pick a winner outright
ELO_STRONG_DIFF = 80        # ELO gap required to confirm strong favorite
BTTS_MIN_PROB = 0.52        # minimum BTTS probability to select BTTS market
OVER25_MIN_PROB = 0.55      # minimum Over 2.5 probability to select that market
XG_MODERATE_DIFF = 0.35     # xG gap for moderate favorite (1X / X2)
XG_DRAW_THRESHOLD = 0.15    # max xG diff to suggest a draw

# ── Confidence thresholds ────────────────────────────────────────────────────
CONF_BASE = 45
CONF_XG_WEIGHT = 18         # multiplied by absolute xG diff
CONF_ELO_WEIGHT = 25        # ELO diff is divided by this
CONF_ELO_CAP = 18           # max ELO contribution to confidence
CONF_MIN = 38
CONF_MAX = 92

# ── EV formula ───────────────────────────────────────────────────────────────
EV_XG_WEIGHT = 0.25
EV_BASELINE = 0.55          # juice/vigorish assumption

# ── Motivation adjustment ────────────────────────────────────────────────────
MOTIVATION_SCORE = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}
MOTIVATION_MAX_ADJUST = 5.0


def apply_motivation_adjustment(confidence: float, motivation: dict, market: str) -> tuple[float, float]:
    """Return (adjusted_confidence, adjustment). Adjustment ∈ [-5, +5], confidence clamped to [CONF_MIN, CONF_MAX]."""
    home = MOTIVATION_SCORE.get(motivation.get("home_motivation", "MEDIUM"), 1)
    away = MOTIVATION_SCORE.get(motivation.get("away_motivation", "MEDIUM"), 1)

    if market in ("1", "1X"):
        adjustment = 2.5 * (home - away)
    elif market in ("2", "X2"):
        adjustment = 2.5 * (away - home)
    elif market == "X":
        if home == away:
            adjustment = 5.0  # both equally engaged or both equally checked-out → draw more likely
        else:
            adjustment = -5.0  # mismatched intent breaks the draw
    elif market in ("BTTS", "Over 2.5"):
        if home >= 2 and away >= 2:
            adjustment = 5.0
        elif home == 0 or away == 0:
            adjustment = -3.0
        else:
            adjustment = 0.0
    else:
        adjustment = 0.0

    adjustment = max(-MOTIVATION_MAX_ADJUST, min(MOTIVATION_MAX_ADJUST, adjustment))
    adjusted = max(CONF_MIN, min(CONF_MAX, confidence + adjustment))
    return round(adjusted, 2), round(adjustment, 2)


def select_market(xg_home: float, xg_away: float, poisson: dict, elo_diff: float, context=None) -> str:
    diff = xg_home - xg_away
    abs_diff = abs(diff)

    if context:
        home_absences = len(context["home"].get("injuries", []))
        away_absences = len(context["away"].get("injuries", []))
        if home_absences >= 2 or away_absences >= 2:
            if poisson["over_2_5_prob"] > 0.50:
                return "Over 2.5"
            if poisson["btts_prob"] > 0.50:
                return "BTTS"

    if diff > XG_STRONG_DIFF and elo_diff > ELO_STRONG_DIFF:
        return "1"
    if diff < -XG_STRONG_DIFF and elo_diff < -ELO_STRONG_DIFF:
        return "2"
    if poisson["btts_prob"] >= BTTS_MIN_PROB and abs_diff < XG_STRONG_DIFF:
        return "BTTS"
    if poisson["over_2_5_prob"] >= OVER25_MIN_PROB:
        return "Over 2.5"
    if diff > XG_MODERATE_DIFF:
        return "1X"
    if diff < -XG_MODERATE_DIFF:
        return "X2"
    if abs_diff <= XG_DRAW_THRESHOLD:
        return "X"
    return "1X" if diff > 0 else "X2"


def calculate_confidence(xg_home: float, xg_away: float, elo: dict, context=None) -> float:
    diff = abs(xg_home - xg_away)
    elo_diff = abs(elo["elo_diff"])

    base = CONF_BASE
    base += diff * CONF_XG_WEIGHT
    base += min(elo_diff / CONF_ELO_WEIGHT, CONF_ELO_CAP)

    if context:
        total_absences = (
            len(context["home"].get("injuries", []))
            + len(context["away"].get("injuries", []))
        )
        if total_absences >= 3:
            base += 5

    return round(max(CONF_MIN, min(CONF_MAX, base)), 2)


def calculate_risk(confidence: float) -> str:
    if confidence >= 72:
        return "LOW"
    if confidence >= 58:
        return "MEDIUM"
    return "HIGH"


def build_reason(xg_home: float, xg_away: float, form_home: dict, form_away: dict, market: str, context=None) -> str:
    reasons = []

    if xg_home > xg_away + 0.4:
        reasons.append("Home attacking edge")
    if xg_away > xg_home + 0.4:
        reasons.append("Away attacking edge")
    if form_home.get("trend") == "strong":
        reasons.append("Strong home form")
    if form_away.get("trend") == "strong":
        reasons.append("Strong away form")

    if context:
        home_out = len(context["home"].get("injuries", []))
        away_out = len(context["away"].get("injuries", []))
        if home_out > 0:
            reasons.append(f"Home missing {home_out} players")
        if away_out > 0:
            reasons.append(f"Away missing {away_out} players")

    if market == "BTTS":
        reasons.append("Both attacks project scoring")
    if market == "Over 2.5":
        reasons.append("High total xG")

    return " | ".join(reasons[:4])


def generate_prediction(home_name: str, away_name: str, league: str, fixture_id=None):
    try:
        home_stats = fetch_team_stats(home_name, league)
    except Exception as e:
        logger.exception("fetch_team_stats failed for %s: %s", home_name, e)
        home_stats = _neutral_stats(home_name)

    try:
        away_stats = fetch_team_stats(away_name, league)
    except Exception as e:
        logger.exception("fetch_team_stats failed for %s: %s", away_name, e)
        away_stats = _neutral_stats(away_name)

    try:
        context = build_context(home_name, away_name, fixture_id)
    except Exception as e:
        logger.warning("build_context failed for %s vs %s: %s", home_name, away_name, e)
        context = {"home": {"lineup": [], "confirmed": [], "injuries": []},
                   "away": {"lineup": [], "confirmed": [], "injuries": []}}

    try:
        elo = get_elo_strength(home_stats, away_stats)
    except Exception as e:
        logger.warning("get_elo_strength failed: %s", e)
        elo = {"home_elo": 1500, "away_elo": 1500, "elo_diff": 0}

    home_strength = home_stats.get("strength", 1.0)
    away_strength = away_stats.get("strength", 1.0)

    try:
        xg_home = estimate_xg(home_stats, away_strength)
        xg_away = estimate_xg(away_stats, home_strength)
    except Exception as e:
        logger.warning("estimate_xg failed: %s", e)
        xg_home, xg_away = 1.2, 1.2

    try:
        form_home = get_form(home_stats)
        form_away = get_form(away_stats)
    except Exception as e:
        logger.warning("get_form failed: %s", e)
        form_home = form_away = {"score": 0.5, "trend": "neutral"}

    try:
        poisson = poisson_signals(xg_home, xg_away)
    except Exception as e:
        logger.warning("poisson_signals failed: %s", e)
        poisson = {"btts_prob": 0.5, "over_2_5_prob": 0.5}

    market = select_market(xg_home, xg_away, poisson, elo["elo_diff"], context)
    confidence = calculate_confidence(xg_home, xg_away, elo, context)
    reason = build_reason(xg_home, xg_away, form_home, form_away, market, context)

    ev = round(
        ((confidence / 100) + abs(xg_home - xg_away) * EV_XG_WEIGHT) - EV_BASELINE,
        3,
    )
    kelly = round(max(0, ev * (confidence / 100)), 3)

    edge = {"ev": ev, "kelly": kelly, "value_bet": ev > 0}

    breakdown = {
        "xg": {"home": round(xg_home, 2), "away": round(xg_away, 2)},
        "strength": {"home": round(home_strength, 2), "away": round(away_strength, 2)},
        "elo": elo,
        "form": {"home": form_home, "away": form_away},
        "poisson": poisson,
        "market": market,
        "context": context,
        "is_fallback": home_stats.get("is_fallback") or away_stats.get("is_fallback"),
    }

    return market, reason, breakdown, edge, confidence


def _neutral_stats(name: str) -> dict:
    return {
        "name": name,
        "position": 10, "played": 1,
        "goals_for": 1, "goals_against": 1,
        "won": 0, "draw": 0, "lost": 0,
        "points": 0,
        "goals_for_pg": 1.0, "goals_against_pg": 1.0, "points_pg": 0.0,
        "strength": 1.0, "raw_strength": 1.0,
        "is_fallback": True,
    }
