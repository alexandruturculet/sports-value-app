"""V7 EDGE ENGINE — entry point.

Page config + global styling + tab orchestration only.
All section logic lives in sections/ (sports, crypto, markets).
"""
import logging
import os

import streamlit as st
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
load_dotenv()

st.set_page_config(page_title="V7 EDGE ENGINE", page_icon="⚡", layout="wide")

from ui.styles import inject_global_css
from ui.components import gradient_title

inject_global_css()

if not os.getenv("football-data-api-key"):
    st.error(
        "**API key missing.** Set `football-data-api-key` in Streamlit Cloud → "
        "Manage app → Settings → Secrets.",
        icon="🔑",
    )
    st.stop()

gradient_title("V7 REAL EDGE ENGINE", subtitle="Value betting · Crypto · Markets — one dashboard")

tab_sports, tab_crypto, tab_markets = st.tabs(["⚽ Sports Betting", "₿ Crypto", "📈 Markets"])

with tab_sports:
    from sections.sports import render as render_sports
    render_sports()
with tab_crypto:
    from sections.crypto import render as render_crypto
    render_crypto()
with tab_markets:
    from sections.markets import render as render_markets
    render_markets()
