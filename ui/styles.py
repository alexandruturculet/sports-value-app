"""Global CSS injection — the entire design system lives in assets/styles.css."""
from pathlib import Path

import streamlit as st

_CSS_PATH = Path(__file__).resolve().parent.parent / "assets" / "styles.css"


def inject_global_css() -> None:
    """Load assets/styles.css once per rerun. Call right after set_page_config."""
    try:
        css = _CSS_PATH.read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
