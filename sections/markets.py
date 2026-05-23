import xml.etree.ElementTree as ET
import logging
import requests
import streamlit as st
from services.yfinance_client import get_quotes, get_signals, get_sector_performance

logger = logging.getLogger(__name__)

_OVERVIEW_TICKERS = ("SPY", "QQQ", "DIA", "IWM", "VIX")
_OVERVIEW_NAMES = {
    "SPY": "S&P 500 ETF", "QQQ": "Nasdaq 100 ETF",
    "DIA": "Dow Jones ETF", "IWM": "Russell 2000 ETF", "VIX": "Volatility Index",
}

_SECTORS = ("XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLB", "XLP", "XLU", "XLRE")
_SECTOR_NAMES = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
    "XLV": "Health Care", "XLY": "Consumer Disc.", "XLI": "Industrials",
    "XLB": "Materials", "XLP": "Consumer Stap.", "XLU": "Utilities",
    "XLRE": "Real Estate",
}

_DEFAULT_WATCHLIST = "AAPL,MSFT,NVDA,TSLA,AMZN,META,GOOGL"

_SIG_STYLE = {
    "STRONG BUY":  ("#0d2b0d", "#4caf50", "▲▲"),
    "BUY":         ("#0d1f0d", "#81c784", "▲"),
    "HOLD":        ("#1a1a1a", "#9e9e9e", "—"),
    "SELL":        ("#2b0d0d", "#ef5350", "▼"),
    "STRONG SELL": ("#1f0d0d", "#b71c1c", "▼▼"),
}

_NEWS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY,QQQ,AAPL,MSFT,NVDA"


@st.cache_data(ttl=900)
def _get_market_news() -> list:
    try:
        r = requests.get(_NEWS_URL, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()[:16]
            if title and link:
                items.append({"title": title, "url": link, "published": pub})
        return items[:10]
    except Exception as e:
        logger.warning("Market news RSS failed: %s", e)
        return []


def _chg_badge(pct: float) -> str:
    color = "#4caf50" if pct >= 0 else "#f44336"
    arrow = "▲" if pct >= 0 else "▼"
    return f'<span style="color:{color};font-weight:600">{arrow} {abs(pct):.2f}%</span>'


def render():
    st.markdown("## 📈 Markets Dashboard")

    # ── Market Overview ───────────────────────────────────────────────────────
    st.markdown("### Market Overview")
    with st.spinner("Loading index data…"):
        quotes = get_quotes(_OVERVIEW_TICKERS)

    if quotes:
        cols = st.columns(len(_OVERVIEW_TICKERS))
        for col, ticker in zip(cols, _OVERVIEW_TICKERS):
            q = quotes.get(ticker)
            if not q:
                col.markdown(f"**{ticker}**\n\n_N/A_")
                continue
            name = _OVERVIEW_NAMES.get(ticker, ticker)
            price = q["price"]
            pct = q["change_pct"]
            badge = _chg_badge(pct)
            col.markdown(f"""
<div style="background:#111;border:1px solid #222;border-radius:10px;padding:14px;text-align:center;margin-bottom:8px">
  <div style="color:#555;font-size:11px">{name}</div>
  <div style="font-size:20px;font-weight:800">{price:,.2f}</div>
  <div style="font-size:13px;margin-top:4px">{badge}</div>
</div>""", unsafe_allow_html=True)
    else:
        st.info("Market data unavailable. yfinance may be rate-limited — try again shortly.")

    # ── Sector Rotation ───────────────────────────────────────────────────────
    st.markdown("### Sector Rotation (1-Week)")
    with st.spinner("Loading sector data…"):
        sector_perf = get_sector_performance(_SECTORS)

    if sector_perf:
        sorted_sectors = sorted(sector_perf.items(), key=lambda x: x[1], reverse=True)
        max_abs = max(abs(v) for v in sector_perf.values()) or 1
        for ticker, pct in sorted_sectors:
            name = _SECTOR_NAMES.get(ticker, ticker)
            bar_width = int(abs(pct) / max_abs * 60)
            color = "#4caf50" if pct >= 0 else "#f44336"
            arrow = "▲" if pct >= 0 else "▼"
            st.markdown(f"""
<div style="display:flex;align-items:center;gap:12px;margin-bottom:6px">
  <div style="width:130px;color:#aaa;font-size:13px">{name}</div>
  <div style="width:{bar_width + 60}px;background:{color};height:8px;border-radius:4px;opacity:0.7"></div>
  <div style="color:{color};font-weight:600;font-size:13px">{arrow} {abs(pct):.2f}%</div>
</div>""", unsafe_allow_html=True)
    else:
        st.info("Sector data unavailable.")

    # ── AI Trade Signals ──────────────────────────────────────────────────────
    st.markdown("### AI Trade Signals")
    raw_watchlist = st.text_input(
        "Watchlist tickers (comma-separated)",
        value=_DEFAULT_WATCHLIST,
        help="Enter any US stock/ETF tickers separated by commas",
    )
    tickers = tuple(t.strip().upper() for t in raw_watchlist.split(",") if t.strip())

    if tickers:
        with st.spinner(f"Computing signals for {', '.join(tickers)}…"):
            signals = get_signals(tickers)

        if signals:
            for ticker, data in signals.items():
                sig = data["signal"]
                bg, color, icon = _SIG_STYLE[sig]
                rsi = data["rsi"]
                ma_diff = data["ma_diff_pct"]
                price = data["price"]
                st.markdown(f"""
<div style="background:{bg};border:1px solid {color}44;border-radius:8px;
            padding:12px 18px;margin-bottom:8px;display:flex;
            align-items:center;justify-content:space-between">
  <div>
    <span style="font-weight:800;font-size:16px">{ticker}</span>
    <span style="color:#555;font-size:12px;margin-left:8px">${price:,.2f}</span>
  </div>
  <div style="display:flex;gap:20px;align-items:center">
    <div style="text-align:center">
      <div style="color:#888;font-size:10px">RSI-14</div>
      <div style="font-weight:700;font-size:14px">{rsi}</div>
    </div>
    <div style="text-align:center">
      <div style="color:#888;font-size:10px">MA5 vs MA20</div>
      <div style="font-weight:700;font-size:14px;color:{'#4caf50' if ma_diff >= 0 else '#f44336'}">{'+' if ma_diff >= 0 else ''}{ma_diff}%</div>
    </div>
    <span style="background:{color};color:#000;font-weight:700;font-size:12px;
                 padding:4px 12px;border-radius:4px">{icon} {sig}</span>
  </div>
</div>""", unsafe_allow_html=True)
        else:
            st.info("Signal computation failed — tickers may be invalid or yfinance is rate-limited.")

    # ── Financial News ────────────────────────────────────────────────────────
    st.markdown("### Market News")
    with st.spinner("Loading headlines…"):
        news = _get_market_news()

    if news:
        for item in news:
            title = item["title"]
            url = item["url"]
            pub = item["published"]
            st.markdown(f"""
<div style="border-left:3px solid #333;padding:8px 14px;margin-bottom:8px">
  <a href="{url}" target="_blank" style="color:#e0e0e0;text-decoration:none;font-weight:600;font-size:14px">{title}</a>
  <div style="color:#555;font-size:11px;margin-top:3px">Yahoo Finance · {pub}</div>
</div>""", unsafe_allow_html=True)
    else:
        st.info("News unavailable.")
