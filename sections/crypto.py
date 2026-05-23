import json
import streamlit as st
import streamlit.components.v1 as components
from services.coingecko import get_market_overview, get_top_coins, get_fear_greed
from services.cryptopanic import get_news

# ── Personal watchlist (CoinGecko IDs) ───────────────────────────────────────
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

# ── Portfolio holdings ────────────────────────────────────────────────────────
_PORTFOLIO = {
    "render-token":     {"qty": 877.33,  "symbol": "RENDER"},
    "fetch-ai":         {"qty": 3110.19, "symbol": "FET",   "staking_apy": 4.60},
    "peaq-2":           {"qty": 15220,   "symbol": "PEAQ"},
    "aioz-network":     {"qty": 6497,    "symbol": "AIOZ"},
    "celestia":         {"qty": 212.87,  "symbol": "TIA",   "staked": True},
    "spectral":         {"qty": 558,     "symbol": "SPEC"},
    "pyth-network":     {"qty": 1005,    "symbol": "PYTH"},
    "io-net":           {"qty": 278,     "symbol": "IO"},
    "heroes-of-mavia":  {"qty": 1084,    "symbol": "MAVIA"},
    "echelon-prime":    {"qty": 49.31,   "symbol": "PRIME"},
    "verasity":         {"qty": 736300,  "symbol": "VRA"},
    "crypto-com-chain": {"qty": 30,      "symbol": "CRO"},
}

_PORTFOLIO_IDS = tuple(_PORTFOLIO.keys())

_SIG_STYLE = {
    "STRONG BUY":  ("#0d2b0d", "#4caf50", "▲▲"),
    "BUY":         ("#0d1f0d", "#81c784", "▲"),
    "HOLD":        ("#1a1a1a", "#9e9e9e", "—"),
    "SELL":        ("#2b0d0d", "#ef5350", "▼"),
    "STRONG SELL": ("#1f0d0d", "#b71c1c", "▼▼"),
}
_SIG_ORDER = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "STRONG SELL": 4}

# ── TradingView symbol map ────────────────────────────────────────────────────
_TV_SYMBOLS = {
    "render-token":     "BINANCE:RENDERUSDT",
    "fetch-ai":         "BINANCE:FETUSDT",
    "peaq-2":           "KUCOIN:PEAQUSDT",
    "aioz-network":     "BINANCE:AIOZUSDT",
    "celestia":         "BINANCE:TIAUSDT",
    "spectral":         "MEXC:SPECUSDT",
    "pyth-network":     "BINANCE:PYTHUSDT",
    "io-net":           "BINANCE:IOUSDT",
    "heroes-of-mavia":  "BINANCE:MAVIAUSDT",
    "echelon-prime":    "COINBASE:PRIMEUSDT",
    "verasity":         "KUCOIN:VRAUSDT",
    "crypto-com-chain": "KRAKEN:CROUSD",
}

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


def _sparkline_svg(prices: list, width: int = 80, height: int = 28) -> str:
    if not prices or len(prices) < 2:
        return f'<div style="width:{width}px;height:{height}px;flex-shrink:0;"></div>'
    step = max(1, len(prices) // 50)
    sampled = prices[::step]
    if len(sampled) < 2:
        return f'<div style="width:{width}px;height:{height}px;flex-shrink:0;"></div>'
    mn, mx = min(sampled), max(sampled)
    if mn == mx:
        return f'<div style="width:{width}px;height:{height}px;flex-shrink:0;"></div>'
    pad = 2
    n = len(sampled)
    x_step = (width - pad * 2) / (n - 1)
    pts = []
    for i, p in enumerate(sampled):
        x = round(pad + i * x_step, 1)
        y = round(height - pad - (p - mn) / (mx - mn) * (height - pad * 2), 1)
        pts.append(f"{x},{y}")
    color = "#2ea043" if sampled[-1] >= sampled[0] else "#da3633"
    return (
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="flex-shrink:0;overflow:visible;">'
        f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" '
        f'stroke-dasharray="1000" stroke-dashoffset="1000">'
        f'<animate attributeName="stroke-dashoffset" from="1000" to="0" dur="1.2s" '
        f'fill="freeze" calcMode="spline" keySplines="0.4 0 0.2 1" keyTimes="0;1"/>'
        f'</polyline>'
        f'</svg>'
    )


def _render_portfolio_rows(rows: list, total_value: float) -> None:
    tv_safe = {cid.replace("-", "_"): sym for cid, sym in _TV_SYMBOLS.items()}
    cards_html = ""
    for coin_id, cd, _ in rows:
        sparkline_prices = (cd.get("sparkline_in_7d") or {}).get("price") or [] if cd else []
        cards_html += _portfolio_row(coin_id, cd, total_value, sparkline_prices)
        if coin_id in _TV_SYMBOLS:
            safe_id = coin_id.replace("-", "_")
            cards_html += (
                f'<div id="chart_{safe_id}" style="display:none;margin-bottom:6px;">'
                f'<div id="tv_{safe_id}" style="height:440px;"></div>'
                f'</div>'
            )
    tv_json = json.dumps(tv_safe)
    html = f"""<!DOCTYPE html><html><head>
<style>
  body{{background:#0d1117;margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#e0e0e0;}}
  [data-chart-id]{{cursor:pointer;}}
  [data-chart-id]:hover svg polyline{{opacity:0.75;}}
</style></head><body>
{cards_html}
<script src="https://s3.tradingview.com/tv.js"></script>
<script>
var TV={tv_json},loaded={{}},active=null;
document.addEventListener('click',function(e){{
  var el=e.target.closest('[data-chart-id]');
  if(!el)return;
  toggleChart(el.dataset.chartId);
}});
function toggleChart(id){{
  var c=document.getElementById('chart_'+id);
  if(!c)return;
  if(active&&active!==id){{var p=document.getElementById('chart_'+active);if(p)p.style.display='none';}}
  if(c.style.display==='none'){{
    c.style.display='block';active=id;
    if(!loaded[id]&&TV[id]){{
      new TradingView.widget({{width:'100%',height:440,symbol:TV[id],interval:'D',timezone:'Europe/Bucharest',theme:'dark',style:'1',locale:'en',allow_symbol_change:true,container_id:'tv_'+id}});
      loaded[id]=true;
    }}
  }}else{{c.style.display='none';active=null;}}
}}
</script></body></html>"""
    components.html(html, height=len(rows) * 72 + 460, scrolling=False)


_PIE_COLORS = [
    "#4caf50", "#2196f3", "#ff9800", "#e91e63", "#9c27b0",
    "#00bcd4", "#8bc34a", "#ff5722", "#607d8b", "#795548",
    "#f44336", "#3f51b5",
]


def _render_allocation_pie(rows: list, total_value: float) -> None:
    import plotly.graph_objects as go

    labels, values, colors = [], [], []
    for i, (coin_id, cd, value) in enumerate(rows):
        if value > 0:
            labels.append(_PORTFOLIO[coin_id]["symbol"])
            values.append(round(value, 2))
            colors.append(_PIE_COLORS[i % len(_PIE_COLORS)])

    if not values:
        return

    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        hole=0.55,
        marker=dict(colors=colors, line=dict(color="#0d1117", width=2)),
        textinfo="label+percent",
        textfont=dict(size=11),
        hovertemplate="%{label}<br>$%{value:,.2f}<br>%{percent}<extra></extra>",
        sort=False,
    ))
    fig.add_annotation(
        text=f"<b>${total_value:,.0f}</b>",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=15, color="#e0e0e0"),
    )
    fig.update_layout(
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117",
        margin=dict(t=10, b=10, l=10, r=10),
        height=300,
        showlegend=False,
        font=dict(color="#e0e0e0", family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


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


def _portfolio_row(coin_id: str, coin_data: dict | None, total_value: float, sparkline_prices: list = None) -> str:
    meta = _PORTFOLIO[coin_id]
    qty = meta["qty"]
    symbol = meta["symbol"]
    staking_apy = meta.get("staking_apy")
    staked = meta.get("staked")

    price = (coin_data.get("current_price") or 0) if coin_data else 0
    p24 = (coin_data.get("price_change_percentage_24h_in_currency")) if coin_data else None
    img = (coin_data.get("image") or "") if coin_data else ""

    value = qty * price
    pct_of_total = (value / total_value * 100) if total_value > 0 and value > 0 else 0

    p24_val = p24 or 0
    border_col = "#2ea043" if p24_val > 0 else "#da3633" if p24_val < 0 else "#30363d"
    bar_color  = "#2ea043" if p24_val > 0 else "#da3633" if p24_val < 0 else "#444"

    img_tag = (
        f'<img src="{img}" style="width:26px;height:26px;border-radius:50%;flex-shrink:0">'
        if img else
        '<div style="width:26px;height:26px;border-radius:50%;background:#222;flex-shrink:0"></div>'
    )

    staking_badge = ""
    if staking_apy:
        staking_badge = (
            f'<span style="background:#0d2b0d;color:#4caf50;font-size:8px;'
            f'padding:2px 5px;border-radius:3px;margin-left:6px;font-weight:700;'
            f'vertical-align:middle;letter-spacing:0.3px">⚡ {staking_apy}% APY</span>'
        )
    elif staked:
        staking_badge = (
            '<span style="background:#051929;color:#29b6f6;font-size:8px;'
            'padding:2px 5px;border-radius:3px;margin-left:6px;font-weight:700;'
            'vertical-align:middle;letter-spacing:0.3px">⚡ STAKED</span>'
        )

    qty_str = f"{qty:,.0f}" if qty % 1 == 0 else f"{qty:,.2f}"
    value_str = f"${value:,.2f}" if price else "—"
    pct_str = f"{pct_of_total:.1f}%" if price else "—"
    price_str = _price_fmt(price) if price else "—"

    alloc_bar = (
        f'<div style="margin-top:8px;height:2px;background:#1a1a1a;border-radius:1px;">'
        f'<div style="height:2px;width:{min(pct_of_total, 100):.1f}%;background:{bar_color};'
        f'border-radius:1px;"></div></div>'
    ) if price else ""

    spark = _sparkline_svg(sparkline_prices or [])
    safe_id = coin_id.replace("-", "_")

    return (
        f'<div style="background:#0a0a0a;border:1px solid #1c1c1c;border-left:3px solid {border_col};'
        f'border-radius:8px;padding:11px 14px;margin-bottom:5px;">'
        f'<div style="display:flex;align-items:center;gap:12px;">'
        f'<div style="display:flex;align-items:center;gap:9px;flex:1;min-width:0;">'
        f'{img_tag}'
        f'<div>'
        f'<div style="font-size:13px;font-weight:700;display:flex;align-items:center;">'
        f'{symbol}{staking_badge}</div>'
        f'<div style="color:#4a4a4a;font-size:10px;margin-top:2px;">{qty_str} tokens</div>'
        f'</div>'
        f'</div>'
        f'<div data-chart-id="{safe_id}" title="Click to open TradingView chart" style="flex-shrink:0;">{spark}</div>'
        f'<div style="text-align:center;flex-shrink:0;min-width:76px;">'
        f'<div style="font-size:11px;color:#666;margin-bottom:2px;">{price_str}</div>'
        f'{_pct(p24, True)}'
        f'</div>'
        f'<div style="text-align:right;flex-shrink:0;min-width:95px;">'
        f'<div style="font-weight:700;font-size:13px;">{value_str}</div>'
        f'<div style="font-size:10px;color:#444;margin-top:2px;">{pct_str} of total</div>'
        f'</div>'
        f'</div>'
        f'{alloc_bar}'
        f'</div>'
    )


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

    # ── Portfolio ──────────────────────────────────────────────────────────────
    st.markdown("### My Portfolio")
    with st.spinner("Loading portfolio…"):
        portfolio_coins = get_market_overview(_PORTFOLIO_IDS, include_sparkline=True)

    if portfolio_coins:
        lookup = {c["id"]: c for c in portfolio_coins}

        rows = []
        total_value = 0.0
        total_24h_pnl = 0.0
        perfs = []

        for coin_id, meta in _PORTFOLIO.items():
            cd = lookup.get(coin_id)
            price = (cd.get("current_price") or 0) if cd else 0
            p24 = (cd.get("price_change_percentage_24h_in_currency") or 0) if cd else 0
            qty = meta["qty"]
            value = qty * price
            total_value += value
            if price and p24:
                prev_price = price / (1 + p24 / 100)
                total_24h_pnl += (price - prev_price) * qty
            if cd and p24 != 0:
                perfs.append((meta["symbol"], p24))
            rows.append((coin_id, cd, value))

        rows.sort(key=lambda x: x[2], reverse=True)

        prev_total = total_value - total_24h_pnl
        pct_24h = (total_24h_pnl / prev_total * 100) if prev_total > 0 else 0
        col_24h = "#4caf50" if total_24h_pnl >= 0 else "#f44336"
        arrow_24h = "▲" if total_24h_pnl >= 0 else "▼"
        sign = "+" if total_24h_pnl >= 0 else ""

        best = max(perfs, key=lambda x: x[1]) if perfs else None
        worst = min(perfs, key=lambda x: x[1]) if perfs else None

        n_positions = sum(1 for _, cd, v in rows if v > 0)

        insights_html = ""
        if best and worst and best[0] != worst[0]:
            insights_html = (
                f'<div style="margin-top:14px;padding-top:12px;border-top:1px solid #1e1e1e;'
                f'display:flex;justify-content:space-between;">'
                f'<div>'
                f'<div style="font-size:9px;color:#444;text-transform:uppercase;letter-spacing:1.2px;margin-bottom:3px;">Best Today</div>'
                f'<div style="font-size:12px;color:#2ea043;font-weight:700;">{best[0]}&nbsp;▲&nbsp;{best[1]:.1f}%</div>'
                f'</div>'
                f'<div style="text-align:right;">'
                f'<div style="font-size:9px;color:#444;text-transform:uppercase;letter-spacing:1.2px;margin-bottom:3px;">Worst Today</div>'
                f'<div style="font-size:12px;color:#da3633;font-weight:700;">{worst[0]}&nbsp;▼&nbsp;{abs(worst[1]):.1f}%</div>'
                f'</div>'
                f'</div>'
            )

        st.markdown(
            f'<div style="background:linear-gradient(135deg,#0d1117 0%,#0f1923 100%);'
            f'border:1px solid #30363d;border-radius:12px;padding:20px 24px;margin-bottom:16px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">'
            f'<div style="font-size:10px;color:#444;text-transform:uppercase;letter-spacing:1.5px;">Total Portfolio Value</div>'
            f'<div style="font-size:10px;color:#444;">{n_positions} positions</div>'
            f'</div>'
            f'<div style="font-size:30px;font-weight:900;line-height:1.1;margin-bottom:8px;">${total_value:,.2f}</div>'
            f'<div style="color:{col_24h};font-size:14px;font-weight:700;">'
            f'{arrow_24h} {sign}${abs(total_24h_pnl):,.2f} today'
            f'<span style="font-size:11px;font-weight:400;opacity:0.7;margin-left:6px;">({sign}{pct_24h:.1f}%)</span>'
            f'</div>'
            f'{insights_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

        _render_allocation_pie(rows, total_value)
        _render_portfolio_rows(rows, total_value)
    else:
        st.info("Portfolio data unavailable — CoinGecko may be rate-limited. Try again in a moment.")

    st.divider()

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
