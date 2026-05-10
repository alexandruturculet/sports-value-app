def compute_edge(xg_home, xg_away, confidence):

    total_xg = xg_home + xg_away

    ev = (confidence / 100) * total_xg - 1

    kelly = max(0, ev / 2)

    fake_favorite = confidence < 45 and total_xg > 2.2

    return {
        "ev": round(ev, 3),
        "kelly": round(kelly, 3),
        "value_bet": ev > 0,
        "fake_favorite": fake_favorite
    }