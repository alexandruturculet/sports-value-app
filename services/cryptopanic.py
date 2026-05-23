import logging
import xml.etree.ElementTree as ET
import requests
import streamlit as st
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
]


def _parse_rss(source: str, url: str) -> list:
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            if title and link:
                items.append({"title": title, "url": link, "source": source, "published": pub})
        return items
    except Exception as e:
        logger.warning("RSS fetch failed for %s: %s", source, e)
        return []


@st.cache_data(ttl=600)
def get_news(limit: int = 15) -> list:
    """Latest crypto news from CoinDesk + CoinTelegraph RSS (no API key required)."""
    all_items = []
    for source, url in _RSS_FEEDS:
        all_items.extend(_parse_rss(source, url))
    return all_items[:limit]
