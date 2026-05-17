import logging
import requests
import streamlit as st

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "sports-value-app/1.0 (educational project)"}


@st.cache_data(ttl=86400)
def get_player_image_url(wikipedia_title: str) -> str | None:
    """Return Wikipedia thumbnail URL for a player, or None if unavailable."""
    if not wikipedia_title:
        return None
    try:
        slug = wikipedia_title.replace(" ", "_")
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}"
        r = requests.get(url, headers=_HEADERS, timeout=6)
        if r.status_code != 200:
            logger.debug("Wikipedia summary not found for: %s", wikipedia_title)
            return None
        thumbnail = r.json().get("thumbnail", {})
        src = thumbnail.get("source")
        # Request a slightly larger thumbnail (300px wide)
        if src:
            src = src.replace("/200px-", "/300px-").replace("/220px-", "/300px-")
        return src
    except Exception as e:
        logger.warning("Failed to fetch Wikipedia image for %s: %s", wikipedia_title, e)
        return None
