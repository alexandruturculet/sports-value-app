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
        if not isinstance(row, dict):
            continue
        team = str(row.get("name") or row.get("team") or "").lower()
        if team == name_l:
            return row
    for row in standings:
        if not isinstance(row, dict):
            continue
        team = str(row.get("name") or row.get("team") or "").lower()
        if name_l in team or team in name_l:
            return row
    return None


def _pts_at_position(standings: list, target_pos: int) -> int | None:
    """Return the points of the team at target_pos, or None if not found."""
    for row in standings:
        if isinstance(row, dict) and row.get("position") == target_pos:
            return row.get("points") or 0
    return None


def _row_at_position(standings: list, target_pos: int) -> dict | None:
    for row in standings:
        if isinstance(row, dict) and row.get("position") == target_pos:
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
    pts = row.get("points") or 0
    stage = _season_progress(played, total)

    full_season = (total - 1) * 2
    games_left = max(0, full_season - played)
    max_pts = pts + games_left * 3

    # Reference points — used for mathematical checks
    safety_pts     = _pts_at_position(standings, rel_start - 1)  # last safe team
    _rel_row       = _row_at_position(standings, rel_start)       # top relegated team row
    rel_top_pts    = (_rel_row.get("points") or 0) if _rel_row else None
    _rel_played    = (_rel_row.get("played") or played) if _rel_row else played
    _rel_games_left = max(0, full_season - _rel_played)
    leader_pts     = _pts_at_position(standings, 1)
    eur_cutoff_pts = _pts_at_position(standings, eur_end)        # last European spot
    eur_next_pts   = _pts_at_position(standings, eur_end + 1)    # first team outside Europe

    level = 1  # MEDIUM by default
    factors = []

    # ── Mathematical relegation: in the zone AND can no longer catch safety line ──
    if pos >= rel_start and safety_pts is not None and max_pts < safety_pts:
        return "LOW", [f"Already relegated (P{pos})"]

    # ── Relegation pressure (points-gap based, not position-based) ──────────────
    if pos >= rel_start:
        # Still in the zone and mathematically alive
        factors.append(f"Relegation battle (P{pos})")
        level = max(level, 2)
    elif rel_top_pts is not None:
        # Use relegation team's own games left, not assessed team's
        rel_zone_max = rel_top_pts + _rel_games_left * 3
        if rel_zone_max >= pts:
            pts_gap = pts - rel_top_pts
            if pts_gap <= 3:
                factors.append(f"Relegation danger (P{pos}, {pts_gap}pt gap)")
                level = max(level, 2 if stage >= 0.4 else 1)
            elif pos >= rel_start - 4:
                # Only flag teams close enough to the zone to be realistically threatened
                factors.append(f"Watching relegation zone (P{pos})")
    elif pos >= rel_start - 2:
        # Fallback when points data missing
        factors.append(f"Near relegation (P{pos})")
        level = max(level, 2 if stage >= 0.7 else 1)

    # ── Title race ───────────────────────────────────────────────────────────────
    if pos == 1:
        factors.append("Title leaders")
        level = max(level, 2)
    elif pos <= 3 and stage >= 0.4:
        if leader_pts is None or max_pts >= leader_pts:
            factors.append(f"Title contender (P{pos})")
            level = max(level, 2)

    # ── CL / European spots ──────────────────────────────────────────────────────
    if 3 < pos <= eur_end:
        # Currently IN a European spot — check if it can be taken away
        if eur_next_pts is not None and eur_next_pts + games_left * 3 >= pts:
            spot_label = "CL" if pos <= 4 else "European"
            pts_gap = pts - eur_next_pts
            factors.append(f"{spot_label} place at stake (P{pos}, {pts_gap}pt lead)")
            level = max(level, 2 if stage >= 0.5 else 1)
        else:
            factors.append(f"European spot secured (P{pos})")
            level = max(level, 1)
    elif pos <= eur_end + 2 and eur_cutoff_pts is not None and max_pts >= eur_cutoff_pts:
        # Just outside Europe but can still reach it
        factors.append(f"Chasing European spot (P{pos})")
        level = max(level, 2 if stage >= 0.6 else 1)

    # ── Dead rubber: safe from rel AND mathematically can't reach Europe ─────────
    rel_safe = rel_top_pts is not None and (rel_top_pts + _rel_games_left * 3) < pts
    cant_europe = eur_cutoff_pts is not None and max_pts < eur_cutoff_pts
    if rel_safe and cant_europe and level <= 1:
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
