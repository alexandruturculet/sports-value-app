import logging
import os

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5"
_MAX_STANDINGS_ROWS = 20

_MOTIVATION_TOOL = {
    "name": "report_motivation",
    "description": (
        "Report the motivation level for each team in an upcoming match, based on "
        "league standings and contextual factors (relegation battle, European places, "
        "title race, derby, dead rubber, etc.)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "home_motivation": {
                "type": "string",
                "enum": ["HIGH", "MEDIUM", "LOW"],
                "description": "Motivation level for the home team.",
            },
            "away_motivation": {
                "type": "string",
                "enum": ["HIGH", "MEDIUM", "LOW"],
                "description": "Motivation level for the away team.",
            },
            "home_factors": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
                "description": "Up to 3 short reasons driving the home team's motivation (e.g. 'fighting relegation', 'chasing top 4', 'derby').",
            },
            "away_factors": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
                "description": "Up to 3 short reasons driving the away team's motivation.",
            },
            "summary": {
                "type": "string",
                "description": "One-sentence summary of the motivational dynamic in this match. Max 200 chars.",
            },
        },
        "required": ["home_motivation", "away_motivation", "home_factors", "away_factors", "summary"],
    },
}


def _get_client():
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("ANTHROPIC_API_KEY")
        except Exception:
            pass
    if not key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=key)
    except Exception as e:
        logger.error("Failed to create Anthropic client: %s", e)
        return None


def is_configured() -> bool:
    if os.getenv("ANTHROPIC_API_KEY"):
        return True
    try:
        import streamlit as st
        return bool(st.secrets.get("ANTHROPIC_API_KEY"))
    except Exception:
        return False


def _format_standings(standings: list, home: str, away: str) -> str:
    if not standings:
        return "(no standings available)"
    total = len(standings)
    rows = standings[:_MAX_STANDINGS_ROWS]
    lines = [f"Total teams in league: {total}", "Pos | Team | P | W-D-L | GD | Pts"]
    for row in rows:
        pos = row.get("position", "?")
        team = row.get("name") or row.get("team", "?")
        played = row.get("played", "?")
        won = row.get("won", "?")
        draw = row.get("draw", "?")
        lost = row.get("lost", "?")
        gd = row.get("goal_difference")
        if gd is None:
            gf = row.get("goals_for", 0) or 0
            ga = row.get("goals_against", 0) or 0
            gd = gf - ga
        pts = row.get("points", "?")
        marker = "  <-- HOME" if team == home else ("  <-- AWAY" if team == away else "")
        lines.append(f"{pos:>3} | {team} | {played} | {won}-{draw}-{lost} | {gd:+d} | {pts}{marker}")
    return "\n".join(lines)


def analyze_match_motivation(
    home: str,
    away: str,
    league: str,
    standings: list,
    match_date: str,
) -> dict | None:
    client = _get_client()
    if client is None:
        return None

    standings_block = _format_standings(standings, home, away)
    prompt = (
        f"Analyze the motivation level of both teams for this upcoming match.\n\n"
        f"League: {league}\n"
        f"Match: {home} (home) vs {away} (away)\n"
        f"Match date: {match_date}\n\n"
        f"Current standings:\n{standings_block}\n\n"
        f"Consider:\n"
        f"- Relegation battle (teams near the bottom fight harder)\n"
        f"- European places race (top 4-7 depending on league)\n"
        f"- Title race (top 2-3)\n"
        f"- Local derby or historic rivalry (use your knowledge of the teams)\n"
        f"- Dead rubber (mid-table with nothing to play for late in season)\n"
        f"- Stage of season implied by games played\n\n"
        f"Call the report_motivation tool with your assessment. Be honest: if neither team "
        f"has strong motivation, return LOW for both."
    )

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            tools=[_MOTIVATION_TOOL],
            tool_choice={"type": "tool", "name": "report_motivation"},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        logger.error("Anthropic call failed for %s vs %s: %s", home, away, e)
        return None

    for block in response.content:
        if block.type == "tool_use" and block.name == "report_motivation":
            return dict(block.input)

    logger.error("No tool_use block in motivation response for %s vs %s", home, away)
    return None
