def get_form(team_stats):

    points = team_stats.get("points", 0)
    played = max(team_stats.get("played", 1), 1)

    ratio = points / (played * 3)

    if ratio >= 0.7:
        trend = "strong"
    elif ratio >= 0.45:
        trend = "neutral"
    else:
        trend = "weak"

    return {
        "score": round(ratio, 2),
        "trend": trend
    }