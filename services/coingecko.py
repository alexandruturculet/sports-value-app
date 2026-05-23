import logging
import requests
import streamlit as st

logger = logging.getLogger(__name__)

_CG_BASE = "https://api.coingecko.com/api/v3"
_FNG_URL = "https://api.alternative.me/fng/"

_DEPIN_IDS = [
    "helium", "render-token", "akash-network",
    "iotex", "filecoin", "io-net",
]


def _get(url: str, params: dict = None) -> dict | list:
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 429:
            logger.warning("CoinGecko rate limited")
            return {}
        if r.status_code != 200:
            logger.error("CoinGecko error %s for %s", r.status_code, url)
            return {}
        return r.json()
    except Exception as e:
        logger.exception("CoinGecko request failed: %s", e)
        return {}


@st.cache_data(ttl=300)
def get_market_overview(coin_ids: tuple, include_sparkline: bool = False) -> list:
    """Price + 24h/7d change for a specific list of coin ids."""
    params = {
        "vs_currency": "usd",
        "ids": ",".join(coin_ids),
        "price_change_percentage": "24h,7d",
        "order": "market_cap_desc",
        "per_page": len(coin_ids),
        "page": 1,
    }
    if include_sparkline:
        params["sparkline"] = "true"
    data = _get(f"{_CG_BASE}/coins/markets", params=params)
    return data if isinstance(data, list) else []


@st.cache_data(ttl=300)
def get_top_coins(limit: int = 200) -> list:
    """Top N coins by market cap with 24h and 7d change (max 250 per CoinGecko free tier)."""
    per_page = min(limit, 250)
    data = _get(f"{_CG_BASE}/coins/markets", params={
        "vs_currency": "usd",
        "price_change_percentage": "24h,7d",
        "order": "market_cap_desc",
        "per_page": per_page,
        "page": 1,
    })
    return data if isinstance(data, list) else []


@st.cache_data(ttl=600)
def get_depin_coins() -> list:
    return get_market_overview(tuple(_DEPIN_IDS))


@st.cache_data(ttl=1800)
def get_trending() -> list:
    data = _get(f"{_CG_BASE}/search/trending")
    return data.get("coins", []) if isinstance(data, dict) else []


@st.cache_data(ttl=1800)
def get_fear_greed() -> dict:
    data = _get(_FNG_URL, params={"limit": 1})
    if isinstance(data, dict) and data.get("data"):
        return data["data"][0]
    return {}


@st.cache_data(ttl=3600)
def get_fear_greed_history(days: int = 30) -> list:
    data = _get(_FNG_URL, params={"limit": days})
    if isinstance(data, dict) and data.get("data"):
        return [int(d["value"]) for d in reversed(data["data"])]
    return []
