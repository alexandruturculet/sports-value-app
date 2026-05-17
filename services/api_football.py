import os
import re
import logging
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"


def _get_key() -> str | None:
    """Read API key at call time so Streamlit secrets are always available."""
    key = os.getenv("FOOTBALL_API_KEY")
    if not key:
        try:
            key = st.secrets.get("FOOTBALL_API_KEY")
        except Exception:
            pass
    return key


def _get(url: str) -> dict:
    api_key = _get_key()
    if not api_key:
        logger.debug("FOOTBALL_API_KEY not set — skipping API-Football call")
        return {}
    headers = {"x-apisports-key": api_key}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 429:
            logger.warning("API-Football rate limit hit for %s", url)
            return {}
        if r.status_code != 200:
            logger.error("API-Football error %s for %s", r.status_code, url)
            return {}
        return r.json()
    except Exception as e:
        logger.exception("API-Football request failed for %s: %s", url, e)
        return {}


def _normalize(name: str) -> str:
    """Strip common club suffixes so both APIs' names can be compared."""
    n = name.lower()
    for tok in (" fc", " cf", " ac", " sc", " fk", " afc", " rfc", " cd", " ud",
                " rc", " sd", " sv", " vfb", " rb", " sg", "fc ", "as ", "ss "):
        n = n.replace(tok, " ")
    return re.sub(r"\s+", " ", n).strip()


def _names_match(n1: str, n2: str) -> bool:
    a, b = _normalize(n1), _normalize(n2)
    return a == b or a in b or b in a


@st.cache_data(ttl=3600)
def get_fixtures_for_date(date_str: str) -> list:
    """One call per date — returns all API-Football fixtures for that day."""
    data = _get(f"{BASE_URL}/fixtures?date={date_str}")
    return data.get("response", [])


def find_api_fixture_id(home_team: str, away_team: str, date_str: str) -> int | None:
    """Match football-data.org team names to an API-Football fixture ID."""
    for fixture in get_fixtures_for_date(date_str):
        teams = fixture.get("teams", {})
        api_home = teams.get("home", {}).get("name", "")
        api_away = teams.get("away", {}).get("name", "")
        if _names_match(home_team, api_home) and _names_match(away_team, api_away):
            return fixture["fixture"]["id"]
    return None


@st.cache_data(ttl=1800)
def get_fixture_injuries(home_team: str, away_team: str, date_str: str) -> dict:
    """Return {"home": [...], "away": [...]} absent-player lists for a fixture."""
    fixture_id = find_api_fixture_id(home_team, away_team, date_str)
    if not fixture_id:
        return {"home": [], "away": []}

    data = _get(f"{BASE_URL}/injuries?fixture={fixture_id}")
    home_out, away_out = [], []
    for entry in data.get("response", []):
        team_name = entry.get("team", {}).get("name", "")
        pl = entry.get("player", {})
        record = {
            "name": pl.get("name", "Unknown"),
            "type": pl.get("type", ""),
            "reason": pl.get("reason", ""),
        }
        if _names_match(home_team, team_name):
            home_out.append(record)
        elif _names_match(away_team, team_name):
            away_out.append(record)

    return {"home": home_out, "away": away_out}


_API_POS_MAP = {"G": "Goalkeeper", "D": "Defender", "M": "Midfielder", "F": "Forward"}


def _parse_api_lineup(team_data: dict) -> dict:
    def _p(entry):
        pl = entry.get("player", {})
        return {
            "name": pl.get("name", ""),
            "shirtNumber": pl.get("number") or "",
            "position": _API_POS_MAP.get((pl.get("pos") or "").upper(), ""),
        }
    return {
        "lineup": [_p(e) for e in team_data.get("startXI", [])],
        "bench": [_p(e) for e in team_data.get("substitutes", [])],
    }


@st.cache_data(ttl=1800)
def get_lineups_for_fixture(home_team: str, away_team: str, date_str: str) -> dict:
    """Confirmed lineup + team IDs from API-Football for a fixture."""
    _empty = {
        "home": {"lineup": [], "bench": []},
        "away": {"lineup": [], "bench": []},
        "home_id": None,
        "away_id": None,
    }
    fixture_row = None
    for f in get_fixtures_for_date(date_str):
        t = f.get("teams", {})
        if (_names_match(home_team, t.get("home", {}).get("name", "")) and
                _names_match(away_team, t.get("away", {}).get("name", ""))):
            fixture_row = f
            break
    if not fixture_row:
        return _empty

    home_id = fixture_row["teams"]["home"]["id"]
    away_id = fixture_row["teams"]["away"]["id"]
    fixture_id = fixture_row["fixture"]["id"]

    result = {
        "home": {"lineup": [], "bench": []},
        "away": {"lineup": [], "bench": []},
        "home_id": home_id,
        "away_id": away_id,
    }
    data = _get(f"{BASE_URL}/fixtures/lineups?fixture={fixture_id}")
    for td in data.get("response", []):
        side = "home" if td.get("team", {}).get("id") == home_id else "away"
        result[side] = _parse_api_lineup(td)
    return result


@st.cache_data(ttl=86400)
def get_last_match_lineup_for_team(team_id: int) -> dict:
    """Last match lineup for a team from API-Football."""
    _empty = {"lineup": [], "bench": []}
    data = _get(f"{BASE_URL}/fixtures?team={team_id}&last=1")
    fixtures = data.get("response", [])
    if not fixtures:
        return _empty
    last_fid = fixtures[0]["fixture"]["id"]
    lineup_data = _get(f"{BASE_URL}/fixtures/lineups?fixture={last_fid}")
    for td in lineup_data.get("response", []):
        if td.get("team", {}).get("id") == team_id:
            return _parse_api_lineup(td)
    return _empty


# ── Stubs kept for context_engine compatibility ───────────────────────────────

def get_lineups(team_name: str, fixture_id) -> dict:
    return {"confirmed": [], "expected": []}


def get_injuries(team_name: str) -> list:
    return []
