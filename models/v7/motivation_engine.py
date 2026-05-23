import logging

logger = logging.getLogger(__name__)

_LEVEL_NAME = ["LOW", "MEDIUM", "HIGH"]


def _league_zones(total: int) -> tuple[int, int]:
    """Return (rel_start_pos, eur_end_pos) based on league size."""
    if total >= 20:
        return 18, 7
    if total >= 18:
        return 16, 6
    if total >= 16:
        return 14, 5
    return max(total - 1, total - 2), max(3, total // 3)


def _find_team_row(name: str, standings: list) -> dict | None:
    name_l = name.lower()
    for row in standings:
        team = (row.get("name") or row.get("team", "")).lower()
        if team == name_l:
            return row
    for row in standings:
        team = (row.get("name") or row.get("team", "")).lower()
        if name_l in team or team in name_l:
            return row
    return None


def _season_progress(played: int, total: int) -> float:
    if not played or total < 2:
        return 0.5
    return min(1.0, played / ((total - 1) * 2))


def _assess_team(name: str, standings: list, total: int, rel_start: int, eur_end: int) -> tuple[str, list[str]]:
    row = _find_team_row(name, standings)
    if row is None:
        return "MEDIUM", ["No standings data"]

    pos = row.get("position") or 0
    if not pos:
        return "MEDIUM", ["Position unavailable"]

    played = row.get("played") or 0
    stage = _season_progress(played, total)

    level = 1  # MEDIUM by default
    factors = []

    # Relegation pressure
    if pos >= total - 1:
        factors.append("In relegation zone")
        level = 2
    elif pos >= rel_start:
        factors.append(f"Relegation battle (P{pos})")
        level = max(level, 2 if stage >= 0.5 else 1)
    elif pos >= rel_start - 2:
        factors.append(f"Near relegation danger (P{pos})")
        level = max(level, 2 if stage >= 0.7 else 1)

    # Title race
    if pos == 1:
        factors.append("Title leaders")
        level = max(level, 2)
    elif pos <= 3 and stage >= 0.4:
        factors.append(f"Title contender (P{pos})")
        level = max(level, 2)

    # Champions League spot (position 4)
    if pos == 4 and stage >= 0.5:
        factors.append("Champions League race (P4)")
        level = max(level, 2 if stage >= 0.65 else 1)

    # Europa / Conference League
    if 4 < pos <= eur_end:
        factors.append(f"European race (P{pos})")
        level = max(level, 1)

    # Dead rubber: safely mid-table, late in season
    safe_from_rel = pos < rel_start - 3
    no_europe = pos > eur_end + 2
    if safe_from_rel and no_europe and stage >= 0.65 and level <= 1:
        factors.append("Nothing to play for")
        level = 0

    if not factors:
        factors.append(f"Mid-table (P{pos})")

    return _LEVEL_NAME[level], factors[:3]


def _build_summary(home: str, away: str, home_mot: str, away_mot: str) -> str:
    if home_mot == "HIGH" and away_mot == "HIGH":
        return "High-stakes clash — both sides have much to play for."
    if home_mot == "LOW" and away_mot == "LOW":
        return "Dead-rubber fixture — neither side has strong motivation."
    if home_mot == "HIGH" and away_mot == "LOW":
        return f"{home} are highly motivated; {away} have little on the line."
    if home_mot == "LOW" and away_mot == "HIGH":
        return f"{away} are highly motivated; {home} have little on the line."
    if home_mot == "HIGH":
        return f"{home} are highly motivated going into this match."
    if away_mot == "HIGH":
        return f"{away} are highly motivated going into this match."
    return "Evenly matched motivational context."


def analyze_motivation(home: str, away: str, league: str, standings: list) -> dict:
    """Rule-based motivation analysis from standings. Returns same structure as the LLM version."""
    total = len(standings)
    if total < 4:
        logger.warning("Too few standings rows (%d) for %s — defaulting MEDIUM", total, league)
        return {
            "home_motivation": "MEDIUM",
            "away_motivation": "MEDIUM",
            "home_factors": ["Insufficient standings data"],
            "away_factors": ["Insufficient standings data"],
            "summary": "Motivational context unavailable — standings data missing.",
        }

    rel_start, eur_end = _league_zones(total)
    home_mot, home_factors = _assess_team(home, standings, total, rel_start, eur_end)
    away_mot, away_factors = _assess_team(away, standings, total, rel_start, eur_end)

    return {
        "home_motivation": home_mot,
        "away_motivation": away_mot,
        "home_factors": home_factors,
        "away_factors": away_factors,
        "summary": _build_summary(home, away, home_mot, away_mot),
    }
