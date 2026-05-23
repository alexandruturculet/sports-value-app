import streamlit as st
from services.coingecko import get_market_overview, get_top_coins, get_fear_greed
from services.cryptopanic import get_news

# ── Personal watchlist (CoinGecko IDs) ───────────────────────────────────────
# Watchlist 1: GRASS, SUPER, PENDLE, LPT, ARKM, ATH, AERO, ARB, AITECH, RSS3,
#              S (Sonic), NOS, GLMR, MINA, TAO, HFT, BEAM, VIRTUAL, CHEX, FLUX, VET
# Favorites:   PHA, AIOZ, MAVIA, PEAQ, PYTH, ETH, TIA, RENDER, FET, IO, PRIME, AKT
_WATCHLIST_IDS = (
    "ethereum", "arbitrum", "vechain",
    "bittensor", "celestia", "render-token", "fetch-ai", "io-net", "akash-network",
    "pendle", "aerodrome-finance", "pyth-network",
    "virtual-protocol", "peaq-2", "grass",
    "livepeer", "arkham", "aethir", "solidus-ai-tech", "rss3",
    "sonic-3", "moonbeam", "mina-protocol", "hashflow", "beam-2",
    "chex-token", "flux", "phala-network", "aioz-network",
    "heroes-of-mavia", "echelon-prime", "nosana", "superverse",
)

_WATCHLIST_ID_SET = set(_WATCHLIST_IDS)

_SIG_STYLE = {
    "STRONG BUY":  ("#0d2b0d", "#4caf50", "▲▲"),
    "BUY":         ("#0d1f0d", "#81c784", "▲"),
    "HOLD":        ("#1a1a1a", "#9e9e9e", "—"),
    "SELL":        ("#2b0d0d", "#ef5350", "▼"),
    "STRONG SELL": ("#1f0d0d", "#b71c1c", "▼▼"),
}
_SIG_ORDER = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "STRONG SELL": 4}

_FNG_RANGES = [
    (range(0, 26),   "Extreme Fear",  "#f44336"),
    (range(26, 46),  "Fear",          "#ff9800"),
    (range(46, 56),  "Neutral",       "#9e9e9e"),
    (range(56, 76),  "Greed",         "#8bc34a"),
    (range(76, 101), "Extreme Greed", "#4caf50"),
]


def _fng_label(value: int):
    for r, label, color in _FNG_RANGES:
        if value in r:
            return label, color
    return "Neutral", "#9e9e9e"


def _pct(pct: float | None, small: bool = False) -> str:
    if pct is None:
        return '<span style="color:#555">—</span>'
    color = "#4caf50" if pct >= 0 else "#f44336"
    arrow = "▲" if pct >= 0 else "▼"
    fs = "10px" if small else "12px"
    return f'<span style="color:{color};font-weight:600;font-size:{fs}">{arrow} {abs(pct):.1f}%</span>'


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


def _price_fmt(price: float) -> str:
    if price < 0.01:
        return f"${price:.6f}"
    if price < 1:
        return f"${price:.4f}"
    if price < 1000:
        return f"${price:,.2f}"
    return f"${price:,.0f}"


def _mcap_fmt(mcap: float | None) -> str:
    if not mcap:
        return "—"
    if mcap >= 1_000_000_000:
        return f"${mcap / 1_000_000_000:.2f}B"
    if mcap >= 1_000_000:
        return f"${mcap / 1_000_000:.1f}M"
    return f"${mcap:,.0f}"


def _locked_pct(coin: dict) -> str:
    circ = coin.get("circulating_supply")
    total = coin.get("total_supply")
    if not circ or not total or total <= 0:
        return "—"
    locked = (total - circ) / total * 100
    if locked < 0.5:
        return "~0%"
    color = "#f44336" if locked > 50 else "#ff9800" if locked > 25 else "#9e9e9e"
    return f'<span style="color:{color}">{locked:.1f}%</span>'


def _watchlist_card(coin: dict) -> str:
    symbol = (coin.get("symbol") or "").upper()
    price = coin.get("current_price", 0)
    p24 = coin.get("price_change_percentage_24h_in_currency")
    p7d = coin.get("price_change_percentage_7d_in_currency")
    mcap = coin.get("market_cap")
    img = coin.get("image", "")
    sig = _compute_signal(coin)
    _, col_sig, icon_sig = _SIG_STYLE[sig]
    img_tag = f'<img src="{img}" style="width:18px;height:18px;border-radius:50%;margin-right:5px;vertical-align:middle">' if img else ""
    locked = _locked_pct(coin)
    return (
        f'<div style="background:#111;border:1px solid #1e1e1e;border-radius:8px;padding:9px 11px;margin-bottom:5px;">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">'
        f'<div>{img_tag}<span style="font-weight:700;font-size:13px;">{symbol}</span></div>'
        f'<span style="background:{col_sig};color:#000;font-weight:700;font-size:9px;padding:2px 5px;border-radius:3px;">{icon_sig} {sig}</span>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
        f'<span style="font-weight:700;font-size:12px;">{_price_fmt(price)}</span>'
        f'<div style="display:flex;gap:8px;font-size:10px;">{_pct(p24, True)}'
        f'<span style="color:#444">7d {_pct(p7d, True)}</span></div>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;font-size:10px;color:#555;border-top:1px solid #1e1e1e;padding-top:4px;">'
        f'<span>MCap {_mcap_fmt(mcap)}</span>'
        f'<span>Locked {locked}</span>'
        f'</div></div>'
    )


def _discovery_card(coin: dict) -> str:
    name = coin.get("name", "")
    symbol = (coin.get("symbol") or "").upper()
    price = coin.get("current_price", 0)
    p24 = coin.get("price_change_percentage_24h_in_currency")
    p7d = coin.get("price_change_percentage_7d_in_currency")
    rank = coin.get("market_cap_rank") or "—"
    img = coin.get("image", "")
    img_tag = f'<img src="{img}" style="width:22px;height:22px;border-radius:50%;margin-right:8px">' if img else ""
    return (
        f'<div style="background:#0d1117;border:1px solid #21262d;border-radius:8px;'
        f'padding:10px 16px;margin-bottom:7px;display:flex;align-items:center;justify-content:space-between;">'
        f'<div style="display:flex;align-items:center;">{img_tag}'
        f'<div><div style="font-weight:700;font-size:14px;">{symbol} '
        f'<span style="color:#555;font-size:10px;">#{rank}</span></div>'
        f'<div style="color:#555;font-size:11px;">{name}</div></div></div>'
        f'<div style="text-align:right;">'
        f'<div style="font-weight:700;font-size:13px;">{_price_fmt(price)}</div>'
        f'<div style="display:flex;gap:8px;justify-content:flex-end;">{_pct(p24)}'
        f'<span style="color:#444;font-size:10px;">7d {_pct(p7d, True)}</span></div>'
        f'</div></div>'
    )


def render():
    st.markdown("## ₿ Crypto Dashboard")

    # ── Fear & Greed ──────────────────────────────────────────────────────────
    fng = get_fear_greed()
    if fng:
        val = int(fng.get("value", 50))
        label, color = _fng_label(val)
        st.markdown(
            f'<div style="background:#111;border:1px solid {color}44;border-radius:10px;'
            f'padding:12px 20px;display:flex;align-items:center;gap:20px;margin-bottom:18px;">'
            f'<div style="font-size:34px;font-weight:900;color:{color}">{val}</div>'
            f'<div><div style="font-size:15px;font-weight:700;color:{color}">{label}</div>'
            f'<div style="color:#555;font-size:11px;">Fear &amp; Greed Index</div></div></div>',
            unsafe_allow_html=True,
        )

    # ── Watchlist ──────────────────────────────────────────────────────────────
    st.markdown("### My Watchlist")
    with st.spinner("Loading watchlist…"):
        coins = get_market_overview(_WATCHLIST_IDS)

    if coins:
        sorted_coins = sorted(coins, key=lambda c: _SIG_ORDER[_compute_signal(c)])
        buy_count = sum(1 for c in sorted_coins if _compute_signal(c) in ("STRONG BUY", "BUY"))
        if buy_count:
            st.markdown(
                f'<div style="color:#4caf50;font-size:12px;margin-bottom:8px;">'
                f'▲ {buy_count} buy signal{"s" if buy_count > 1 else ""} in your watchlist right now</div>',
                unsafe_allow_html=True,
            )
        col_a, col_b = st.columns(2)
        for i, coin in enumerate(sorted_coins):
            (col_a if i % 2 == 0 else col_b).markdown(_watchlist_card(coin), unsafe_allow_html=True)
    else:
        st.info("Watchlist data unavailable — CoinGecko may be rate-limited. Try again in a moment.")

    # ── New Discoveries ────────────────────────────────────────────────────────
    st.markdown("### 🔍 New Discoveries")
    st.caption("Top performers outside your watchlist — from top 200 coins by market cap")

    with st.spinner("Scanning top 200 coins…"):
        top200 = get_top_coins(200)

    if top200:
        watchlist_syms = {(c.get("symbol") or "").upper() for c in (coins or [])}
        discoveries = [
            c for c in top200
            if c.get("id") not in _WATCHLIST_ID_SET
            and (c.get("symbol") or "").upper() not in watchlist_syms
            and (c.get("price_change_percentage_24h_in_currency") or 0) > 2
        ]
        discoveries.sort(key=lambda c: c.get("price_change_percentage_24h_in_currency") or 0, reverse=True)
        if discoveries:
            for coin in discoveries[:8]:
                st.markdown(_discovery_card(coin), unsafe_allow_html=True)
        else:
            st.info("No strong performers outside your watchlist right now — market may be broadly down.")
    else:
        st.info("Discovery data unavailable.")

    # ── Crypto News ───────────────────────────────────────────────────────────
    st.markdown("### Crypto News")
    with st.spinner("Loading headlines…"):
        news = get_news(12)

    if news:
        for item in news:
            title = item.get("title", "")
            url = item.get("url", "")
            source = item.get("source", "")
            pub = item.get("published", "")[:16]
            st.markdown(
                f'<div style="border-left:3px solid #333;padding:8px 14px;margin-bottom:8px">'
                f'<a href="{url}" target="_blank" style="color:#e0e0e0;text-decoration:none;'
                f'font-weight:600;font-size:14px">{title}</a>'
                f'<div style="color:#555;font-size:11px;margin-top:3px">{source} · {pub}</div></div>',
                unsafe_allow_html=True,
            )
    else:
        st.info("News unavailable.")
