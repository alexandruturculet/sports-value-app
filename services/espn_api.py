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


def _parse_roster(roster_entry: dict) -> dict:
    lineup, bench = [], []
    for a in roster_entry.get("roster", []):
        pos = a.get("position", {})
        p = {
            "name": a.get("athlete", {}).get("displayName", ""),
            "shirtNumber": a.get("jersey", "") or "",
            "position": pos.get("displayName", "") or pos.get("abbreviation", ""),
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


@st.cache_data(ttl=86400)
def get_espn_last_lineup(team_name: str, league_code: str) -> dict:
    """Probable XI from team's most recent match via ESPN (looks back up to 7 days)."""
    _empty = {"lineup": [], "bench": []}
    slug = _SLUGS.get(league_code)
    if not slug:
        return _empty
    today = datetime.now(timezone.utc).date()
    for days_back in range(1, 8):
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
