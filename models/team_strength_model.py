# =========================
# TEAM STRENGTH MODEL V4
# =========================

def get_team_strength(standings, team_name):

    team = next(
        (t for t in standings if t["team"]["name"] == team_name),
        None
    )

    if not team:
        return {
    "attack": 1.2,
    "defense": 1.2,
    "form": 0.5,
    "elo": 1500,
    "rank": 10
}

    rank = team["rank"]

    # Elo proxy (simplified)
    elo = 2000 - (rank * 25)

    # Attack / Defense curves based on rank
    attack = max(0.7, 2.0 - (rank * 0.04))
    defense = max(0.7, 2.0 - (rank * 0.035))

    # Form simulation (based on rank stability)
    form = max(0.3, 1.2 - (rank * 0.03))

    return {
        "attack": round(attack, 2),
        "defense": round(defense, 2),
        "form": round(form, 2),
        "elo": round(elo, 0),
        "rank": rank
    }


# =========================
# MATCH EXPECTED GOALS (REAL MODEL)
# =========================

def expected_goals(home, away):

    home_xg = (home["attack"] * away["defense"]) * home["form"]
    away_xg = (away["attack"] * home["defense"]) * away["form"]

    return round(home_xg, 2), round(away_xg, 2)