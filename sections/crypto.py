import streamlit as st
from services.coingecko import (
    get_market_overview, get_top_coins, get_depin_coins,
    get_trending, get_fear_greed,
)
from services.cryptopanic import get_news

_OVERVIEW_IDS = ("bitcoin", "ethereum", "solana", "binancecoin")

_DEPIN_NAMES = {
    "helium": "Helium",
    "render-token": "Render",
    "akash-network": "Akash",
    "iotex": "IoTeX",
    "filecoin": "Filecoin",
    "io-net": "IO.net",
}

_SIG_STYLE = {
    "STRONG BUY":  ("#0d2b0d", "#4caf50", "▲▲"),
    "BUY":         ("#0d1f0d", "#81c784", "▲"),
    "HOLD":        ("#1a1a1a", "#9e9e9e", "—"),
    "SELL":        ("#2b0d0d", "#ef5350", "▼"),
    "STRONG SELL": ("#1f0d0d", "#b71c1c", "▼▼"),
}

_FNG_LABEL = {
    range(0, 26):  ("Extreme Fear",  "#f44336"),
    range(26, 46): ("Fear",          "#ff9800"),
    range(46, 56): ("Neutral",       "#9e9e9e"),
    range(56, 76): ("Greed",         "#8bc34a"),
    range(76, 101):("Extreme Greed", "#4caf50"),
}


def _fng_label(value: int):
    for r, (label, color) in _FNG_LABEL.items():
        if value in r:
            return label, color
    return "Neutral", "#9e9e9e"


def _pct_badge(pct: float | None) -> str:
    if pct is None:
        return '<span style="color:#555">—</span>'
    color = "#4caf50" if pct >= 0 else "#f44336"
    arrow = "▲" if pct >= 0 else "▼"
    return f'<span style="color:{color};font-weight:600">{arrow} {abs(pct):.2f}%</span>'


def _price_card(coin: dict) -> str:
    name = coin.get("name", "")
    symbol = (coin.get("symbol") or "").upper()
    price = coin.get("current_price", 0)
    pct24 = coin.get("price_change_percentage_24h_in_currency")
    img = coin.get("image", "")
    img_tag = f'<img src="{img}" style="width:28px;height:28px;border-radius:50%;margin-right:8px">' if img else ""
    badge = _pct_badge(pct24)
    price_fmt = f"${price:,.4f}" if price < 1 else f"${price:,.2f}"
    return f"""
<div style="background:#111;border:1px solid #222;border-radius:10px;padding:14px 18px;display:flex;
            align-items:center;justify-content:space-between;margin-bottom:8px">
  <div style="display:flex;align-items:center">{img_tag}
    <div>
      <div style="font-weight:700;font-size:15px">{name}</div>
      <div style="color:#555;font-size:12px">{symbol}</div>
    </div>
  </div>
  <div style="text-align:right">
    <div style="font-size:16px;font-weight:700">{price_fmt}</div>
    <div style="font-size:13px">{badge} <span style="color:#555;font-size:11px">24h</span></div>
  </div>
</div>"""


def _compute_signal(coin: dict) -> str:
    p24 = coin.get("price_change_percentage_24h_in_currency") or 0
    p7d = coin.get("price_change_percentage_7d_in_currency") or 0
    if p24 < -8 and p7d < -20:
        return "STRONG BUY"
    if -8 <= p24 < -4 and p7d < 0:
        return "BUY"
    if p24 > 12 and p7d > 30:
        return "STRONG SELL"
    if p24 > 8 and p7d > 20:
        return "SELL"
    return "HOLD"


def _signal_row(coin: dict, signal: str) -> str:
    bg, color, icon = _SIG_STYLE[signal]
    name = coin.get("name", "")
    symbol = (coin.get("symbol") or "").upper()
    price = coin.get("current_price", 0)
    p24 = coin.get("price_change_percentage_24h_in_currency") or 0
    p7d = coin.get("price_change_percentage_7d_in_currency") or 0
    price_fmt = f"${price:,.4f}" if price < 1 else f"${price:,.2f}"
    return f"""
<div style="background:{bg};border:1px solid {color}33;border-radius:8px;
            padding:10px 16px;margin-bottom:6px;display:flex;
            align-items:center;justify-content:space-between">
  <div>
    <span style="font-weight:700">{name}</span>
    <span style="color:#555;font-size:12px;margin-left:6px">{symbol}</span>
  </div>
  <div style="display:flex;gap:20px;align-items:center">
    <span style="font-size:13px">{price_fmt}</span>
    <span style="font-size:12px;color:#888">24h {_pct_badge(p24)}</span>
    <span style="font-size:12px;color:#888">7d {_pct_badge(p7d)}</span>
    <span style="background:{color};color:#000;font-weight:700;font-size:11px;
                 padding:3px 8px;border-radius:4px">{icon} {signal}</span>
  </div>
</div>"""


def render():
    st.markdown("## ₿ Crypto Dashboard")

    # ── Fear & Greed ──────────────────────────────────────────────────────────
    with st.spinner("Loading market sentiment…"):
        fng = get_fear_greed()

    if fng:
        val = int(fng.get("value", 50))
        label, color = _fng_label(val)
        st.markdown(f"""
<div style="background:#111;border:1px solid {color}44;border-radius:12px;
            padding:16px 24px;display:flex;align-items:center;gap:24px;margin-bottom:16px">
  <div style="font-size:42px;font-weight:900;color:{color}">{val}</div>
  <div>
    <div style="font-size:18px;font-weight:700;color:{color}">{label}</div>
    <div style="color:#555;font-size:12px">Fear &amp; Greed Index · updated {fng.get("timestamp","")[:10]}</div>
  </div>
</div>""", unsafe_allow_html=True)

    # ── Market Overview ───────────────────────────────────────────────────────
    st.markdown("### Market Overview")
    with st.spinner("Loading prices…"):
        overview = get_market_overview(_OVERVIEW_IDS)

    if overview:
        cols = st.columns(len(overview))
        for col, coin in zip(cols, overview):
            col.markdown(_price_card(coin), unsafe_allow_html=True)
    else:
        st.info("Price data unavailable (CoinGecko rate limit). Try again in a moment.")

    # ── AI Momentum Signals ───────────────────────────────────────────────────
    st.markdown("### AI Momentum Signals")
    with st.spinner("Computing signals for top 50 coins…"):
        top = get_top_coins(50)

    if top:
        signals = [(c, _compute_signal(c)) for c in top]
        buys = [(c, s) for c, s in signals if s in ("STRONG BUY", "BUY")]
        sells = [(c, s) for c, s in signals if s in ("STRONG SELL", "SELL")]

        with st.expander(f"🟢 Buy Opportunities ({len(buys)} coins)", expanded=True):
            if buys:
                for coin, sig in buys[:10]:
                    st.markdown(_signal_row(coin, sig), unsafe_allow_html=True)
            else:
                st.markdown('<div style="color:#555;padding:8px">No strong buy signals right now — market is neutral or overbought.</div>', unsafe_allow_html=True)

        with st.expander(f"🔴 Overbought / Take Profit ({len(sells)} coins)"):
            if sells:
                for coin, sig in sells[:5]:
                    st.markdown(_signal_row(coin, sig), unsafe_allow_html=True)
            else:
                st.markdown('<div style="color:#555;padding:8px">No overbought signals right now.</div>', unsafe_allow_html=True)
    else:
        st.info("Signal data unavailable.")

    # ── DePIN Tracker ─────────────────────────────────────────────────────────
    st.markdown("### DePIN Tracker")
    with st.spinner("Loading DePIN tokens…"):
        depin = get_depin_coins()

    if depin:
        for coin in depin:
            cid = coin.get("id", "")
            name = _DEPIN_NAMES.get(cid, coin.get("name", ""))
            symbol = (coin.get("symbol") or "").upper()
            price = coin.get("current_price", 0)
            rank = coin.get("market_cap_rank") or "—"
            p24 = coin.get("price_change_percentage_24h_in_currency")
            p7d = coin.get("price_change_percentage_7d_in_currency")
            price_fmt = f"${price:,.4f}" if price < 1 else f"${price:,.2f}"
            st.markdown(f"""
<div style="background:#0d0d14;border:1px solid #1a1a2e;border-radius:8px;
            padding:10px 18px;margin-bottom:6px;display:flex;align-items:center;
            justify-content:space-between">
  <div>
    <span style="font-weight:700;color:#8a5df5">{name}</span>
    <span style="color:#444;font-size:12px;margin-left:6px">{symbol}</span>
    <span style="color:#333;font-size:11px;margin-left:10px">#{rank}</span>
  </div>
  <div style="display:flex;gap:20px;align-items:center">
    <span style="font-weight:700">{price_fmt}</span>
    <span style="font-size:12px">24h {_pct_badge(p24)}</span>
    <span style="font-size:12px">7d {_pct_badge(p7d)}</span>
  </div>
</div>""", unsafe_allow_html=True)
    else:
        st.info("DePIN data unavailable.")

    # ── Trending Today ────────────────────────────────────────────────────────
    st.markdown("### Trending Today")
    with st.spinner("Loading trending coins…"):
        trending = get_trending()

    if trending:
        cols = st.columns(min(len(trending), 4))
        for i, entry in enumerate(trending[:7]):
            item = entry.get("item", {})
            name = item.get("name", "")
            symbol = item.get("symbol", "")
            rank = item.get("market_cap_rank") or "—"
            score = round(item.get("score", 0), 1)
            thumb = item.get("thumb", "")
            img_tag = f'<img src="{thumb}" style="width:22px;height:22px;border-radius:50%;margin-right:6px">' if thumb else ""
            col = cols[i % 4]
            col.markdown(f"""
<div style="background:#111;border:1px solid #222;border-radius:8px;padding:10px;margin-bottom:6px;text-align:center">
  <div style="display:flex;align-items:center;justify-content:center">{img_tag}<span style="font-weight:700">{name}</span></div>
  <div style="color:#555;font-size:12px">{symbol} · #{rank}</div>
  <div style="color:#f5d45d;font-size:11px">Score {score}</div>
</div>""", unsafe_allow_html=True)
    else:
        st.info("Trending data unavailable.")

    # ── Crypto News ───────────────────────────────────────────────────────────
    st.markdown("### Crypto News")
    with st.spinner("Loading headlines…"):
        news = get_news(15)

    if news:
        for item in news:
            title = item.get("title", "")
            url = item.get("url", "")
            source = item.get("source", "")
            pub = item.get("published", "")[:16]
            st.markdown(f"""
<div style="border-left:3px solid #333;padding:8px 14px;margin-bottom:8px">
  <a href="{url}" target="_blank" style="color:#e0e0e0;text-decoration:none;font-weight:600;font-size:14px">{title}</a>
  <div style="color:#555;font-size:11px;margin-top:3px">{source} · {pub}</div>
</div>""", unsafe_allow_html=True)
    else:
        st.info("News unavailable.")
