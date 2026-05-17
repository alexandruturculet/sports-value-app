import re
import logging
import requests
import streamlit as st
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

_SLUGS = {
    "PL": "eng.1", "PD": "esp.1", "SA": "ita.1", "BL1": "ger.1",
    "FL1": "fra.1", "PPL": "por.1", "DED": "ned.1", "ELC": "eng.2", "BSA": "bel.1",
}


def _get(url: str) -> dict:
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "sports-value-app/1.0"})
        return r.json() if r.status_code == 200 else {}
    except Exception as e:
        logger.warning("ESPN request failed for %s: %s", url, e)
        return {}


def _norm(name: str) -> str:
    n = name.lower()
    for t in (" fc", " cf", " ac", " sc", " fk", " afc", " rfc"):
        n = n.replace(t, " ")
    return re.sub(r"\s+", " ", n).strip()


def _match(a: str, b: str) -> bool:
    x, y = _norm(a), _norm(b)
    return x == y or x in y or y in x


@st.cache_data(ttl=86400)
def _scoreboard(slug: str, ymd: str) -> list:
    return _get(f"{_BASE}/{slug}/scoreboard?dates={ymd}").get("events", [])


@st.cache_data(ttl=1800)
def _summary(slug: str, event_id: str) -> dict:
    return _get(f"{_BASE}/{slug}/summary?event={event_id}")


_ESPN_POS_MAP = {
    "GK": "Goalkeeper", "G": "Goalkeeper",
    "CB": "Centre-Back", "LCB": "Centre-Back", "RCB": "Centre-Back",
    "LB": "Left-Back", "LWB": "Left-Back",
    "RB": "Right-Back", "RWB": "Right-Back",
    "D": "Defender",
    "DM": "Defensive Midfield", "CDM": "Defensive Midfield",
    "CM": "Central Midfield", "LCM": "Central Midfield", "RCM": "Central Midfield",
    "AM": "Attacking Midfield", "CAM": "Attacking Midfield",
    "LM": "Left Midfield", "RM": "Right Midfield",
    "M": "Midfielder",
    "LW": "Left Winger", "RW": "Right Winger",
    "CF": "Centre-Forward", "SS": "Centre-Forward",
    "ST": "Striker", "F": "Forward",
}


def _parse_roster(roster_entry: dict) -> dict:
    lineup, bench = [], []
    for a in roster_entry.get("roster", []):
        pos = a.get("position", {})
        abbr = pos.get("abbreviation", "").upper()
        display = pos.get("displayName", "")
        position = _ESPN_POS_MAP.get(abbr) or display
        p = {
            "name": a.get("athlete", {}).get("displayName", ""),
            "shirtNumber": a.get("jersey", "") or "",
            "position": position,
        }
        (lineup if a.get("starter") else bench).append(p)
    return {"lineup": lineup, "bench": bench}


@st.cache_data(ttl=1800)
def get_espn_lineups(home_team: str, away_team: str, league_code: str, date_str: str) -> dict:
    """Confirmed lineup from ESPN for a fixture. No API key required."""
    _empty = {"home": {"lineup": [], "bench": []}, "away": {"lineup": [], "bench": []}}
    slug = _SLUGS.get(league_code)
    if not slug:
        return _empty
    ymd = date_str.replace("-", "")
    for event in _scoreboard(slug, ymd):
        comps = event.get("competitions", [{}])
        competitors = comps[0].get("competitors", []) if comps else []
        h = next((c["team"]["name"] for c in competitors if c.get("homeAway") == "home"), "")
        a = next((c["team"]["name"] for c in competitors if c.get("homeAway") == "away"), "")
        if _match(home_team, h) and _match(away_team, a):
            data = _summary(slug, event["id"])
            result = {"home": {"lineup": [], "bench": []}, "away": {"lineup": [], "bench": []}}
            for entry in data.get("rosters", []):
                side = entry.get("homeAway", "")
                if side in ("home", "away"):
                    result[side] = _parse_roster(entry)
            if result["home"]["lineup"] or result["away"]["lineup"]:
                return result
    return _empty


@st.cache_data(ttl=1800)
def _espn_league_injuries(slug: str) -> list:
    """All current injuries for a league — powers espn.com/soccer/injuries page."""
    data = _get(f"{_BASE}/{slug}/injuries")
    out = []
    # Structure A: flat list under "injuries"
    for item in data.get("injuries", []):
        team_obj = item.get("team") or {}
        team_name = team_obj.get("displayName") or team_obj.get("name", "")
        athlete = item.get("athlete") or {}
        if not athlete.get("displayName"):
            continue
        reason = (item.get("type") or {}).get("text", "") or item.get("status", "") or "Unavailable"
        out.append({
            "team": team_name,
            "name": athlete["displayName"],
            "type": "injury",
            "reason": reason,
        })
    # Structure B: list under each team entry in "teams"
    for team_entry in data.get("teams", []):
        team_obj = team_entry.get("team") or {}
        team_name = team_obj.get("displayName") or team_obj.get("name", "")
        for item in team_entry.get("injuries", []):
            athlete = item.get("athlete") or {}
            if not athlete.get("displayName"):
                continue
            reason = (item.get("type") or {}).get("text", "") or item.get("status", "") or "Unavailable"
            out.append({
                "team": team_name,
                "name": athlete["displayName"],
                "type": "injury",
                "reason": reason,
            })
    return out


@st.cache_data(ttl=1800)
def get_espn_injuries(home_team: str, away_team: str, league_code: str, date_str: str) -> dict:
    """Fetch absent/injured players via ESPN: league list → roster flags → per-team endpoint."""
    _empty = {"home": [], "away": []}
    slug = _SLUGS.get(league_code)
    if not slug:
        return _empty

    # ── Tier 1: league-wide injury list (pre-match, works any time) ──────────
    league_inj = _espn_league_injuries(slug)
    if league_inj:
        home_out = [
            {"name": i["name"], "type": i["type"], "reason": i["reason"]}
            for i in league_inj if _match(home_team, i["team"])
        ]
        away_out = [
            {"name": i["name"], "type": i["type"], "reason": i["reason"]}
            for i in league_inj if _match(away_team, i["team"])
        ]
        if home_out or away_out:
            return {"home": home_out, "away": away_out}

    # ── Tier 2: event summary roster flags (post-lineup-confirmation) ─────────
    ymd = date_str.replace("-", "")
    home_id = away_id = None
    home_out, away_out = [], []

    for event in _scoreboard(slug, ymd):
        comps = event.get("competitions", [{}])
        competitors = comps[0].get("competitors", []) if comps else []
        h = next((c["team"]["name"] for c in competitors if c.get("homeAway") == "home"), "")
        a = next((c["team"]["name"] for c in competitors if c.get("homeAway") == "away"), "")
        if not (_match(home_team, h) and _match(away_team, a)):
            continue

        home_id = next((c["team"]["id"] for c in competitors if c.get("homeAway") == "home"), None)
        away_id = next((c["team"]["id"] for c in competitors if c.get("homeAway") == "away"), None)

        data = _summary(slug, event["id"])
        for entry in data.get("rosters", []):
            side = entry.get("homeAway", "")
            if side not in ("home", "away"):
                continue
            out = home_out if side == "home" else away_out
            for athlete in entry.get("roster", []):
                if athlete.get("injured") or not athlete.get("active", True):
                    pl = athlete.get("athlete", {})
                    injury = athlete.get("injury") or {}
                    reason = (
                        injury.get("type", {}).get("text", "")
                        or injury.get("description", "")
                        or "Unavailable"
                    )
                    out.append({
                        "name": pl.get("displayName", "Unknown"),
                        "type": "injury" if athlete.get("injured") else "unavailable",
                        "reason": reason,
                    })
        break

    if home_out or away_out:
        return {"home": home_out, "away": away_out}

    # ── Tier 3: per-team endpoint (last resort) ───────────────────────────────
    def _team_report(team_id: str) -> list:
        data = _get(f"{_BASE}/{slug}/teams/{team_id}/injuries")
        out = []
        for item in data.get("injuries", []):
            athlete = item.get("athlete") or {}
            reason = (item.get("type") or {}).get("text", "") or item.get("status", "") or "Unavailable"
            if athlete.get("displayName"):
                out.append({"name": athlete["displayName"], "type": "injury", "reason": reason})
        # Also check roster athletes with injury status
        if not out:
            roster = _get(f"{_BASE}/{slug}/teams/{team_id}/roster")
            for group in roster.get("athletes", []):
                items = group.get("items", [group]) if isinstance(group, dict) and "items" in group else [group]
                for a in items:
                    for inj in a.get("injuries", []):
                        reason = inj.get("longComment") or inj.get("shortComment") or "Unavailable"
                        if a.get("displayName"):
                            out.append({"name": a["displayName"], "type": "injury", "reason": reason})
        return out

    return {
        "home": _team_report(str(home_id)) if home_id else [],
        "away": _team_report(str(away_id)) if away_id else [],
    }


@st.cache_data(ttl=86400)
def get_espn_last_lineup(team_name: str, league_code: str) -> dict:
    """Probable XI from team's most recent match via ESPN (looks back up to 7 days)."""
    _empty = {"lineup": [], "bench": []}
    slug = _SLUGS.get(league_code)
    if not slug:
        return _empty
    today = datetime.now(timezone.utc).date()
    for days_back in range(1, 15):
        ymd = (today - timedelta(days=days_back)).strftime("%Y%m%d")
        for event in _scoreboard(slug, ymd):
            comps = event.get("competitions", [{}])
            competitors = comps[0].get("competitors", []) if comps else []
            for c in competitors:
                if _match(team_name, c.get("team", {}).get("name", "")):
                    side = c.get("homeAway", "home")
                    data = _summary(slug, event["id"])
                    for entry in data.get("rosters", []):
                        if entry.get("homeAway") == side:
                            parsed = _parse_roster(entry)
                            if parsed["lineup"]:
                                return parsed
    return _empty
