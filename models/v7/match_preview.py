def generate_preview(home_name: str, away_name: str, market: str, breakdown: dict, confidence: float) -> str:
    xg = breakdown.get("xg", {})
    form = breakdown.get("form", {})
    elo = breakdown.get("elo", {})
    poisson = breakdown.get("poisson", {})
    context = breakdown.get("context", {})

    xg_home = xg.get("home", 1.2)
    xg_away = xg.get("away", 1.2)
    home_trend = form.get("home", {}).get("trend", "neutral")
    away_trend = form.get("away", {}).get("trend", "neutral")
    elo_diff = elo.get("elo_diff", 0)
    btts = poisson.get("btts_prob", 0)
    over25 = poisson.get("over_2_5_prob", 0)

    sentences = []

    # xG narrative
    diff = xg_home - xg_away
    if diff > 0.5:
        sentences.append(
            f"{home_name} carry a clear attacking edge, projecting {xg_home:.1f} xG against "
            f"{xg_away:.1f} for {away_name}."
        )
    elif diff < -0.5:
        sentences.append(
            f"{away_name} are the stronger attacking side here, projecting {xg_away:.1f} xG "
            f"against {xg_home:.1f} for {home_name}."
        )
    else:
        sentences.append(
            f"An evenly matched fixture — both sides project similar threat "
            f"({xg_home:.1f} vs {xg_away:.1f} xG)."
        )

    # Form + ELO narrative
    if home_trend == "strong" and away_trend != "strong":
        sentences.append(f"{home_name} arrive in strong recent form, which adds further weight to the home edge.")
    elif away_trend == "strong" and home_trend != "strong":
        sentences.append(f"{away_name} are in strong form and could be underestimated in this fixture.")
    elif home_trend == "weak" and away_trend != "weak":
        sentences.append(f"{home_name}'s poor recent form is a concern the model accounts for.")
    elif away_trend == "weak" and home_trend != "weak":
        sentences.append(f"{away_name} have been struggling and face an uphill task here.")

    if abs(elo_diff) > 120:
        stronger = home_name if elo_diff > 0 else away_name
        sentences.append(f"A {abs(elo_diff)}-point ELO gap confirms {stronger} as the significantly stronger side on paper.")

    # Market rationale
    if market == "BTTS":
        sentences.append(
            f"Both attacks look capable of scoring — BTTS lands at {round(btts * 100)}% probability, "
            f"making it the model's preferred market."
        )
    elif market == "Over 2.5":
        sentences.append(
            f"Combined xG of {xg_home + xg_away:.1f} drives a {round(over25 * 100)}% Over 2.5 chance — "
            f"expect an open, goal-heavy game."
        )
    elif market in ("1", "1X"):
        sentences.append(
            f"The model backs {home_name} — superior xG output and home advantage point to at least a home result."
        )
    elif market in ("2", "X2"):
        sentences.append(
            f"The model backs {away_name}, whose attacking metrics are stronger in this matchup."
        )
    elif market == "X":
        sentences.append(
            f"With minimal xG separation and balanced form, a draw is the most likely outcome."
        )

    # Injury note
    home_out = len(context.get("home", {}).get("injuries", []))
    away_out = len(context.get("away", {}).get("injuries", []))
    if home_out >= 2:
        sentences.append(f"{home_name} are missing {home_out} players, adding volatility to this pick.")
    if away_out >= 2:
        sentences.append(f"{away_name} are missing {away_out} players, which could affect their output.")

    return " ".join(sentences[:3])
