# models/v7/prediction_engine.py

from models.v7.xg_engine import estimate_xg
from models.v7.elo_engine import get_elo_strength
from models.v7.form_engine import get_form
from models.v7.poisson_engine import poisson_signals
from models.v7.team_context import fetch_team_stats


# =========================
# MARKET ENGINE
# =========================

def select_market(
    xg_home,
    xg_away,
    poisson,
    elo_diff
):

    diff = xg_home - xg_away
    abs_diff = abs(diff)

    # =========================
    # STRONG HOME FAVORITE
    # =========================

    if diff > 0.65 and elo_diff > 80:
        return "1"

    # =========================
    # STRONG AWAY FAVORITE
    # =========================

    if diff < -0.65 and elo_diff < -80:
        return "2"

    # =========================
    # BTTS SIGNAL
    # =========================

    if (
        poisson["btts_prob"] >= 0.52
        and abs_diff < 0.55
    ):
        return "BTTS"

    # =========================
    # OVER 2.5 SIGNAL
    # =========================

    if poisson["over_2_5_prob"] >= 0.55:
        return "Over 2.5"

    # =========================
    # MODERATE FAVORITE
    # =========================

    if diff > 0.35:
        return "1X"

    if diff < -0.35:
        return "X2"

    # =========================
    # DRAW ONLY IF VERY CLOSE
    # =========================

    if abs_diff <= 0.15:
        return "X"

    # =========================
    # LAST SAFE FALLBACK
    # =========================

    return "1X" if diff > 0 else "X2"


# =========================
# CONFIDENCE ENGINE
# =========================

def calculate_confidence(
    xg_home,
    xg_away,
    elo
):

    diff = abs(xg_home - xg_away)

    elo_diff = abs(elo["elo_diff"])

    base = 45

    # xG separation
    base += diff * 18

    # ELO separation
    base += min(elo_diff / 25, 18)

    return round(
        max(38, min(92, base)),
        2
    )


# =========================
# RISK ENGINE
# =========================

def calculate_risk(confidence):

    if confidence >= 72:
        return "LOW"

    if confidence >= 58:
        return "MEDIUM"

    return "HIGH"


# =========================
# REASON ENGINE
# =========================

def build_reason(
    xg_home,
    xg_away,
    form_home,
    form_away,
    market
):

    reasons = []

    if xg_home > xg_away + 0.4:
        reasons.append("Home attacking edge")

    if xg_away > xg_home + 0.4:
        reasons.append("Away attacking edge")

    if form_home["trend"] == "strong":
        reasons.append("Strong home form")

    if form_away["trend"] == "strong":
        reasons.append("Strong away form")

    if market == "BTTS":
        reasons.append("Both attacks project scoring")

    if market == "Over 2.5":
        reasons.append("High total xG")

    return " | ".join(reasons[:3])


# =========================
# MAIN ENGINE
# =========================

def generate_prediction(
    home_name,
    away_name,
    league
):

    # =========================
    # REAL TEAM DATA
    # =========================

    home_stats = fetch_team_stats(
        home_name,
        league
    )

    away_stats = fetch_team_stats(
        away_name,
        league
    )

    # =========================
    # ELO ENGINE
    # =========================

    elo = get_elo_strength(
        home_stats,
        away_stats
    )

    # =========================
    # TEAM STRENGTH
    # =========================

    home_strength = home_stats.get(
        "strength",
        1
    )

    away_strength = away_stats.get(
        "strength",
        1
    )

    # =========================
    # xG ENGINE
    # =========================

    xg_home = estimate_xg(
        home_stats,
        away_strength
    )

    xg_away = estimate_xg(
        away_stats,
        home_strength
    )

    # =========================
    # FORM ENGINE
    # =========================

    form_home = get_form(home_stats)

    form_away = get_form(away_stats)

    # =========================
    # POISSON
    # =========================

    poisson = poisson_signals(
        xg_home,
        xg_away
    )

    # =========================
    # MARKET
    # =========================

    market = select_market(
        xg_home,
        xg_away,
        poisson,
        elo["elo_diff"]
    )

    # =========================
    # CONFIDENCE
    # =========================

    confidence = calculate_confidence(
        xg_home,
        xg_away,
        elo
    )

    # =========================
    # REASONING
    # =========================

    reason = build_reason(
        xg_home,
        xg_away,
        form_home,
        form_away,
        market
    )

    # =========================
    # EV ENGINE
    # =========================

    ev = round(
        (
            (confidence / 100)
            +
            abs(xg_home - xg_away) * 0.25
        )
        - 0.55,
        3
    )

    # =========================
    # KELLY
    # =========================

    kelly = round(
        max(0, ev * (confidence / 100)),
        3
    )

    # =========================
    # EDGE
    # =========================

    edge = {
        "ev": ev,
        "kelly": kelly,
        "value_bet": ev > 0
    }

    # =========================
    # BREAKDOWN
    # =========================

    breakdown = {

        "xg": {
            "home": round(xg_home, 2),
            "away": round(xg_away, 2)
        },

        "strength": {
            "home": round(home_strength, 2),
            "away": round(away_strength, 2)
        },

        "elo": elo,

        "form": {
            "home": form_home,
            "away": form_away
        },

        "poisson": poisson,

        "market": market
    }

    return (
        market,
        reason,
        breakdown,
        edge,
        confidence
    )