import os
import re
import logging
import requests
import urllib.parse
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"

_LEAGUE_IDS = {
    "PL": 39, "PD": 140, "SA": 135, "BL1": 78,
    "FL1": 61, "PPL": 94, "DED": 88, "ELC": 40, "BSA": 144,
}

def _current_season() -> int:
    from datetime import date
    today = date.today()
    return today.year - 1 if today.month < 7 else today.year


def _get_key() -> str | None:
    """Read API key at call time so Streamlit secrets are always available."""
    key = os.getenv("FOOTBALL_API_KEY")
    if not key:
        try:
            key = st.secrets.get("FOOTBALL_API_KEY")
        except Exception:
            pass
    return key


_api_rate_limited = False


def _get(url: str) -> dict:
    global _api_rate_limited
    api_key = _get_key()
    if not api_key:
        logger.debug("FOOTBALL_API_KEY not set — skipping API-Football call")
        return {}
    headers = {"x-apisports-key": api_key}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        remaining = r.headers.get("x-ratelimit-requests-remaining")
        if remaining is not None:
            logger.info("API-Football requests remaining today: %s", remaining)
        if r.status_code == 429 or remaining == "0":
            logger.warning("API-Football rate limit hit for %s", url)
            _api_rate_limited = True
            return {}
        _api_rate_limited = False
        if r.status_code != 200:
            logger.error("API-Football error %s for %s", r.status_code, url)
            return {}
        return r.json()
    except Exception as e:
        logger.exception("API-Football request failed for %s: %s", url, e)
        return {}


def is_api_rate_limited() -> bool:
    return _api_rate_limited


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
    """All API-Football fixtures for a date (global, no league filter)."""
    data = _get(f"{BASE_URL}/fixtures?date={date_str}")
    return data.get("response", [])


@st.cache_data(ttl=3600)
def get_fixtures_for_date_league(date_str: str, competition_code: str) -> list:
    """API-Football fixtures filtered by league — fewer results, better matching."""
    league_id = _LEAGUE_IDS.get(competition_code)
    if not league_id:
        return get_fixtures_for_date(date_str)
    season = _current_season()
    data = _get(f"{BASE_URL}/fixtures?date={date_str}&league={league_id}&season={season}")
    return data.get("response", [])


def find_api_fixture_id(home_team: str, away_team: str, date_str: str,
                        competition_code: str = "") -> int | None:
    """Match football-data.org team names to an API-Football fixture ID."""
    fixtures = (
        get_fixtures_for_date_league(date_str, competition_code)
        if competition_code else
        get_fixtures_for_date(date_str)
    )
    for fixture in fixtures:
        teams = fixture.get("teams", {})
        api_home = teams.get("home", {}).get("name", "")
        api_away = teams.get("away", {}).get("name", "")
        if _names_match(home_team, api_home) and _names_match(away_team, api_away):
            return fixture["fixture"]["id"]
    return None


@st.cache_data(ttl=1800)
def get_fixture_injuries(home_team: str, away_team: str, date_str: str,
                         competition_code: str = "") -> dict:
    """Return {"home": [...], "away": [...]} absent-player lists for a fixture."""
    fixture_id = find_api_fixture_id(home_team, away_team, date_str, competition_code)
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


# ── Season stats (cards + corners) ───────────────────────────────────────────

@st.cache_data(ttl=604800)
def _get_team_id(team_name: str, competition_code: str) -> int | None:
    league_id = _LEAGUE_IDS.get(competition_code)
    if not league_id:
        return None
    season = _current_season()
    normalized = _normalize(team_name).title()
    # search= is fuzzy; try normalized name first, then first word
    for search_term in [normalized, team_name.split()[0]]:
        enc = urllib.parse.quote(search_term)
        data = _get(f"{BASE_URL}/teams?search={enc}&league={league_id}&season={season}")
        for t in data.get("response", []):
            if _names_match(team_name, t["team"]["name"]):
                return t["team"]["id"]
    return None


@st.cache_data(ttl=86400)
def get_team_season_stats(team_name: str, competition_code: str) -> dict:
    """Season avg yellow/red cards + avg corners FT (last 10 matches). Returns {} on failure."""
    team_id = _get_team_id(team_name, competition_code)
    if not team_id:
        return {}
    league_id = _LEAGUE_IDS.get(competition_code)
    season = _current_season()

    result = {}

    # Cards — season totals from teams/statistics
    sdata = _get(f"{BASE_URL}/teams/statistics?team={team_id}&league={league_id}&season={season}")
    resp = sdata.get("response", {})
    if resp:
        played = resp.get("fixtures", {}).get("played", {}).get("total", 1) or 1
        cards = resp.get("cards", {})
        yellow = sum((v.get("total") or 0) for v in cards.get("yellow", {}).values())
        red = sum((v.get("total") or 0) for v in cards.get("red", {}).values())
        result["avg_yellow"] = round(yellow / played, 2)
        result["avg_red"] = round(red / played, 2)
        result["played"] = played

    # Corners — avg from last 10 finished fixtures
    fdata = _get(f"{BASE_URL}/fixtures?team={team_id}&last=10&season={season}&league={league_id}&status=FT")
    corners = []
    for f in fdata.get("response", []):
        fid = f["fixture"]["id"]
        fsdata = _get(f"{BASE_URL}/fixtures/statistics?fixture={fid}&team={team_id}")
        for block in fsdata.get("response", []):
            if block.get("team", {}).get("id") != team_id:
                continue
            for stat in block.get("statistics", []):
                if stat.get("type") == "Corner Kicks":
                    try:
                        corners.append(int(stat["value"]))
                    except (TypeError, ValueError):
                        pass
    if corners:
        result["avg_corners_ft"] = round(sum(corners) / len(corners), 1)

    return result
