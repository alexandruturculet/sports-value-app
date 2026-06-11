"""The Odds API — real bookmaker odds (https://the-odds-api.com).

Free tier: 500 credits/month. One odds call costs (#markets × #regions)
credits, so h2h+totals+btts in one EU-region request = 3 credits per league.
Raw + thread-safe (no Streamlit cache); callers cache at the batch level.
"""
import os
import re
import logging
import requests
from dotenv import load_dotenv

from services._memo import TTLMemo

load_dotenv()

logger = logging.getLogger(__name__)

_BASE = "https://api.the-odds-api.com/v4"
# Featured markets only — additional markets (btts, double_chance…) are
# event-endpoint-only on The Odds API and would 422 the bulk league call.
# BTTS picks simply keep the model EV (no real odds available in bulk).
_MARKETS = "h2h,totals"
_REGION = "eu"

_memo = TTLMemo()
_requests_remaining: str | None = None


def _get_key() -> str | None:
    key = os.getenv("ODDS_API_KEY")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("ODDS_API_KEY")
        except Exception:
            pass
    return key


def odds_requests_remaining() -> str | None:
    return _requests_remaining


def _norm(name: str) -> str:
    n = name.lower()
    for t in (" fc", " cf", " ac", " sc", " fk", " afc", " rfc", " cd", " ud"):
        n = n.replace(t, " ")
    return re.sub(r"\s+", " ", n).strip()


def _match(a: str, b: str) -> bool:
    x, y = _norm(a), _norm(b)
    return x == y or x in y or y in x


def fetch_league_odds(sport_key: str) -> list:
    """All upcoming events with h2h/totals/btts odds for one competition."""
    return _memo.get_or_set(("odds", sport_key), 1500, lambda: _fetch_league_odds_raw(sport_key))


def _fetch_league_odds_raw(sport_key: str) -> list:
    global _requests_remaining
    api_key = _get_key()
    if not api_key:
        logger.debug("ODDS_API_KEY not set — skipping odds fetch")
        return []
    url = (
        f"{_BASE}/sports/{sport_key}/odds"
        f"?apiKey={api_key}&regions={_REGION}&markets={_MARKETS}&oddsFormat=decimal"
    )
    try:
        r = requests.get(url, timeout=10)
        _requests_remaining = r.headers.get("x-requests-remaining")
        if r.status_code != 200:
            logger.warning("Odds API error %s for %s: %s", r.status_code, sport_key, r.text[:200])
            return []
        return r.json()
    except Exception as e:
        logger.exception("Odds API request failed for %s: %s", sport_key, e)
        return []


def _best_price(event: dict, market_key: str, outcome_filter) -> tuple[float, str] | None:
    """Best (highest) decimal price across bookmakers for one outcome."""
    best: tuple[float, str] | None = None
    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market.get("key") != market_key:
                continue
            for outcome in market.get("outcomes", []):
                if not outcome_filter(outcome):
                    continue
                price = outcome.get("price")
                if price and (best is None or price > best[0]):
                    best = (float(price), bm.get("title", ""))
    return best


def extract_market_odds(event: dict, home: str, away: str) -> dict:
    """Best available odds per prediction market for one event.

    Returns {market: (decimal_odds, bookmaker)}. Double-chance (1X/X2) is
    derived from the two h2h prices (fair combined price — slightly generous
    vs. a real DC line, flagged with '~' in the bookmaker name).
    """
    out: dict = {}

    o1 = _best_price(event, "h2h", lambda o: _match(o.get("name", ""), home))
    o2 = _best_price(event, "h2h", lambda o: _match(o.get("name", ""), away))
    ox = _best_price(event, "h2h", lambda o: o.get("name") == "Draw")
    if o1:
        out["1"] = o1
    if o2:
        out["2"] = o2
    if ox:
        out["X"] = ox

    # Derived double chance from h2h component prices
    if o1 and ox:
        p = 1 / o1[0] + 1 / ox[0]
        if p > 0:
            out["1X"] = (round(1 / p, 2), "~derived")
    if o2 and ox:
        p = 1 / o2[0] + 1 / ox[0]
        if p > 0:
            out["X2"] = (round(1 / p, 2), "~derived")

    over = _best_price(
        event, "totals",
        lambda o: o.get("name") == "Over" and float(o.get("point") or 0) == 2.5,
    )
    under = _best_price(
        event, "totals",
        lambda o: o.get("name") == "Under" and float(o.get("point") or 0) == 2.5,
    )
    if over:
        out["Over 2.5"] = over
    if under:
        out["Under 2.5"] = under

    btts_yes = _best_price(event, "btts", lambda o: o.get("name") == "Yes")
    if btts_yes:
        out["BTTS"] = btts_yes

    return out


def find_event_odds(events: list, home: str, away: str) -> dict:
    """Locate the event for a fixture by team names and extract market odds."""
    for ev in events:
        if _match(home, ev.get("home_team", "")) and _match(away, ev.get("away_team", "")):
            return extract_market_odds(ev, home, away)
    return {}
