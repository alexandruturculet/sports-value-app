import json
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components
from services.coingecko import (
    get_fear_greed, get_fear_greed_history, get_global, get_market_overview, get_top_coins,
)
from services.cryptopanic import get_news
from services.supabase_client import (
    delete_portfolio_coin, get_portfolio, get_portfolio_history,
    save_portfolio_snapshot, upsert_portfolio_coin,
)
from ui.components import (
    LOSS, SIG_STYLE, TEXT_FAINT, WARN, WIN,
    card_html, count_up, section_header,
)

# ── Personal watchlist (CoinGecko IDs) ───────────────────────────────────────
_WATCHLIST_IDS = (
    "ethereum", "arbitrum", "vechain",
    "bittensor", "celestia", "render-token", "fetch-ai", "io", "akash-network",
    "pendle", "aerodrome-finance", "pyth-network",
    "virtual-protocol", "peaq-2", "grass",
    "livepeer", "arkham", "aethir", "solidus-ai-tech", "rss3",
    "sonic-3", "moonbeam", "mina-protocol", "hashflow", "beam-2",
    "chex-token", "flux", "phala-network", "aioz-network",
    "heroes-of-mavia", "echelon-prime", "nosana", "superverse",
)

_WATCHLIST_ID_SET = set(_WATCHLIST_IDS)

# ── Default portfolio (used to seed DB on first run) ─────────────────────────
_DEFAULT_PORTFOLIO = {
    "render-token":     {"qty": 877.33,  "symbol": "RENDER"},
    "fetch-ai":         {"qty": 3110.19, "symbol": "FET",   "staking_apy": 4.60},
    "peaq-2":           {"qty": 15220,   "symbol": "PEAQ"},
    "aioz-network":     {"qty": 6497,    "symbol": "AIOZ"},
    "celestia":         {"qty": 212.87,  "symbol": "TIA",   "staked": True},
    "spectral":         {"qty": 558,     "symbol": "SPEC"},
    "pyth-network":     {"qty": 1005,    "symbol": "PYTH"},
    "io":               {"qty": 278,     "symbol": "IO"},
    "heroes-of-mavia":  {"qty": 1084,    "symbol": "MAVIA"},
    "echelon-prime":    {"qty": 49.31,   "symbol": "PRIME"},
    "verasity":         {"qty": 736300,  "symbol": "VRA"},
    "crypto-com-chain": {"qty": 30,      "symbol": "CRO"},
}

_DEFAULT_TV_SYMBOLS = {
    "render-token":     "BINANCE:RENDERUSDT",
    "fetch-ai":         "BINANCE:FETUSDT",
    "peaq-2":           "KUCOIN:PEAQUSDT",
    "aioz-network":     "BINANCE:AIOZUSDT",
    "celestia":         "BINANCE:TIAUSDT",
    "spectral":         "MEXC:SPECUSDT",
    "pyth-network":     "BINANCE:PYTHUSDT",
    "io":               "BYBIT:IOUSDT",
    "heroes-of-mavia":  "BINANCE:MAVIAUSDT",
    "echelon-prime":    "COINBASE:PRIMEUSDT",
    "verasity":         "KUCOIN:VRAUSDT",
    "crypto-com-chain": "KRAKEN:CROUSD",
}

# Extra name/alias keywords for news filtering (beyond ticker symbols)
_EXTRA_NEWS_KEYWORDS = {
    "render network", "render token",
    "fetch.ai", "fetch ai", "artificial superintelligence alliance", "asa",
    "celestia", "tia",
    "pyth network", "pyth",
    "peaq",
    "aioz network", "aioz",
    "heroes of mavia", "mavia",
    "echelon prime", "prime",
    "verasity", "vra",
    "crypto.com", "cronos", "cro",
    "io.net", "io net",
    "spectral",
}

_SIG_ORDER = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "STRONG SELL": 4}

_FNG_RANGES = [
    (range(0, 26),   "Extreme Fear",  LOSS),
    (range(26, 46),  "Fear",          WARN),
    (range(46, 56),  "Neutral",       "#9aa3b5"),
    (range(56, 76),  "Greed",         "#6ee7b7"),
    (range(76, 101), "Extreme Greed", WIN),
]


def _fng_label(value: int):
    for r, label, color in _FNG_RANGES:
        if value in r:
            return label, color
    return "Neutral", "#9aa3b5"


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
    color = WIN if sampled[-1] >= sampled[0] else LOSS
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


def _render_portfolio_rows(rows: list, total_value: float, portfolio: dict, tv_symbols: dict) -> None:
    tv_safe = {cid.replace("-", "_"): sym for cid, sym in tv_symbols.items()}
    cards_html = ""
    for coin_id, cd, _ in rows:
        sparkline_prices = (cd.get("sparkline_in_7d") or {}).get("price") or [] if cd else []
        cards_html += _portfolio_row(coin_id, cd, total_value, portfolio, sparkline_prices)
        if coin_id in tv_symbols:
            safe_id = coin_id.replace("-", "_")
            cards_html += (
                f'<div id="chart_{safe_id}" style="display:none;margin-bottom:6px;">'
                f'<div id="tv_{safe_id}" style="height:440px;"></div>'
                f'</div>'
            )
    tv_json = json.dumps(tv_safe)
    html = f"""<!DOCTYPE html><html><head>
<style>
  body{{background:transparent;margin:0;padding:0;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#e6e9f2;}}
  [data-chart-id]{{cursor:pointer;}}
  [data-chart-id]:hover svg polyline{{opacity:0.75;}}
  .pf-row{{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);
    border-radius:12px;padding:11px 14px;margin-bottom:5px;
    transition:border-color .25s, box-shadow .25s;}}
  .pf-row:hover{{border-color:rgba(167,139,250,0.35);box-shadow:0 0 20px rgba(124,108,240,0.12);}}
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


def _render_allocation_pie(rows: list, total_value: float, portfolio: dict) -> None:
    import plotly.graph_objects as go

    pie_rows = [
        (portfolio[cid]["symbol"], round(v, 2))
        for cid, _, v in rows if v > 0
    ]
    if not pie_rows:
        return

    labels = [r[0] for r in pie_rows]
    values = [r[1] for r in pie_rows]

    _PALETTE = [
        "#818CF8", "#34D399", "#FB923C", "#F472B6", "#60A5FA",
        "#FBBF24", "#A78BFA", "#4ADE80", "#F87171", "#38BDF8",
        "#E879F9", "#2DD4BF",
    ]
    colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(labels))]

    max_idx = values.index(max(values))
    pull = [0.05 if i == max_idx else 0 for i in range(len(labels))]

    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        hole=0.66,
        pull=pull,
        marker=dict(colors=colors, line=dict(color="#0a0d14", width=3)),
        textinfo="none",
        hovertemplate="<b>%{label}</b><br>$%{value:,.2f}<br><b>%{percent}</b><extra></extra>",
        sort=False,
    ))

    fig.add_annotation(
        text=f"<b>${total_value:,.0f}</b>",
        x=0.5, y=0.57, showarrow=False,
        font=dict(size=22, color="#f1f5f9"),
    )
    fig.add_annotation(
        text="TOTAL VALUE",
        x=0.5, y=0.43, showarrow=False,
        font=dict(size=9, color="#475569"),
    )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=16, b=16, l=0, r=200),
        height=360,
        showlegend=True,
        legend=dict(
            orientation="v",
            x=1.02, y=0.5,
            xanchor="left",
            yanchor="middle",
            font=dict(size=11, color="#94a3b8"),
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
            itemsizing="constant",
        ),
        hoverlabel=dict(
            bgcolor="#1e293b",
            bordercolor="#334155",
            font=dict(size=13, color="#f1f5f9"),
        ),
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def _pct(pct: float | None, small: bool = False) -> str:
    if pct is None:
        return '<span style="color:#555">—</span>'
    color = WIN if pct >= 0 else LOSS
    arrow = "▲" if pct >= 0 else "▼"
    fs = "10px" if small else "12px"
    return f'<span style="color:{color};font-weight:600;font-size:{fs}">{arrow} {abs(pct):.1f}%</span>'


def _ath_badge(ath_pct: float | None) -> str:
    if ath_pct is None:
        return ""
    color = LOSS if ath_pct > -20 else WARN if ath_pct > -50 else WIN
    return (
        f'<span style="background:rgba(255,255,255,0.06);color:{color};font-size:9px;'
        f'padding:2px 5px;border-radius:3px;font-weight:600;">'
        f'{ath_pct:.0f}% ATH</span>'
    )


def _compute_signal(coin: dict) -> str:
    p24      = coin.get("price_change_percentage_24h_in_currency") or 0
    p7d      = coin.get("price_change_percentage_7d_in_currency")  or 0
    ath_pct  = coin.get("ath_change_percentage") or 0
    vol      = coin.get("total_volume") or 0
    mcap     = coin.get("market_cap") or 1
    vol_ratio = vol / mcap

    deep_dip = ath_pct < -75
    high_vol  = vol_ratio > 0.12

    if p24 < -8 and p7d < -20:
        return "STRONG BUY"
    if p24 < -5 and p7d < -10 and deep_dip:
        return "BUY"
    if -8 <= p24 < -3 and p7d < 0:
        return "BUY"
    if p24 > 12 and p7d > 30 and high_vol:
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


def _portfolio_row(coin_id: str, coin_data: dict | None, total_value: float, portfolio: dict, sparkline_prices: list = None) -> str:
    meta = portfolio[coin_id]
    qty = meta["qty"]
    symbol = meta["symbol"]
    staking_apy = meta.get("staking_apy")
    staked = meta.get("staked")

    price   = (coin_data.get("current_price") or 0) if coin_data else 0
    p24     = (coin_data.get("price_change_percentage_24h_in_currency")) if coin_data else None
    ath_pct = (coin_data.get("ath_change_percentage")) if coin_data else None
    img     = (coin_data.get("image") or "") if coin_data else ""

    value = qty * price
    pct_of_total = (value / total_value * 100) if total_value > 0 and value > 0 else 0

    p24_val = p24 or 0
    border_col = WIN if p24_val > 0 else LOSS if p24_val < 0 else "rgba(255,255,255,0.15)"
    bar_color  = WIN if p24_val > 0 else LOSS if p24_val < 0 else "#444"

    img_tag = (
        f'<img src="{img}" style="width:26px;height:26px;border-radius:50%;flex-shrink:0">'
        if img else
        '<div style="width:26px;height:26px;border-radius:50%;background:#222;flex-shrink:0"></div>'
    )

    staking_badge = ""
    if staking_apy:
        staking_badge = (
            f'<span style="background:rgba(52,211,153,0.14);color:{WIN};font-size:8px;'
            f'padding:2px 5px;border-radius:3px;margin-left:6px;font-weight:700;'
            f'vertical-align:middle;letter-spacing:0.3px">⚡ {staking_apy}% APY</span>'
        )
    elif staked:
        staking_badge = (
            '<span style="background:rgba(34,211,238,0.14);color:#22d3ee;font-size:8px;'
            'padding:2px 5px;border-radius:3px;margin-left:6px;font-weight:700;'
            'vertical-align:middle;letter-spacing:0.3px">⚡ STAKED</span>'
        )

    qty_str = f"{qty:,.0f}" if qty % 1 == 0 else f"{qty:,.2f}"
    value_str = f"${value:,.2f}" if price else "—"
    pct_str = f"{pct_of_total:.1f}%" if price else "—"
    price_str = _price_fmt(price) if price else "—"

    # Unrealized PnL vs cost basis (needs avg_price from the editor)
    avg_buy = meta.get("avg_price")
    pnl_html = ""
    if avg_buy and price:
        invested = qty * avg_buy
        pnl = value - invested
        pnl_pct = (pnl / invested * 100) if invested > 0 else 0
        pnl_col = WIN if pnl >= 0 else LOSS
        pnl_sign = "+" if pnl >= 0 else "−"
        pnl_html = (
            f'<div style="font-size:10px;color:{pnl_col};font-weight:600;margin-top:2px;">'
            f'{pnl_sign}${abs(pnl):,.2f} ({pnl_sign}{abs(pnl_pct):.1f}%)</div>'
        )

    alloc_bar = (
        f'<div style="margin-top:8px;height:2px;background:rgba(255,255,255,0.07);border-radius:1px;">'
        f'<div style="height:2px;width:{min(pct_of_total, 100):.1f}%;background:{bar_color};'
        f'border-radius:1px;box-shadow:0 0 6px {bar_color};"></div></div>'
    ) if price else ""

    spark = _sparkline_svg(sparkline_prices or [])
    safe_id = coin_id.replace("-", "_")

    return (
        f'<div class="pf-row" style="border-left:3px solid {border_col};">'
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
        f'<div style="margin-top:3px;">{_ath_badge(ath_pct)}</div>'
        f'</div>'
        f'<div style="text-align:right;flex-shrink:0;min-width:95px;">'
        f'<div style="font-weight:700;font-size:13px;">{value_str}</div>'
        f'<div style="font-size:10px;color:#444;margin-top:2px;">{pct_str} of total</div>'
        f'{pnl_html}'
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
    ath_pct = coin.get("ath_change_percentage")
    sig = _compute_signal(coin)
    bg_sig, col_sig, icon_sig = SIG_STYLE[sig]
    img_tag = f'<img src="{img}" style="width:18px;height:18px;border-radius:50%;margin-right:5px;vertical-align:middle">' if img else ""
    return (
        f'<div class="sv-card" style="padding:9px 11px;margin-bottom:5px;">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">'
        f'<div>{img_tag}<span style="font-weight:700;font-size:13px;">{symbol}</span></div>'
        f'<span style="background:{bg_sig};color:{col_sig};font-weight:700;font-size:9px;padding:2px 6px;border-radius:10px;">{icon_sig} {sig}</span>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
        f'<span class="sv-mono" style="font-weight:700;font-size:12px;">{_price_fmt(price)}</span>'
        f'<div style="display:flex;gap:8px;font-size:10px;">{_pct(p24, True)}'
        f'<span style="color:#444">7d {_pct(p7d, True)}</span></div>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;align-items:center;font-size:10px;color:#555;border-top:1px solid rgba(255,255,255,0.07);padding-top:4px;">'
        f'<span>MCap {_mcap_fmt(mcap)}</span>'
        f'{_ath_badge(ath_pct)}'
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
        f'<div class="sv-card" style="padding:10px 16px;margin-bottom:7px;'
        f'display:flex;align-items:center;justify-content:space-between;">'
        f'<div style="display:flex;align-items:center;">{img_tag}'
        f'<div><div style="font-weight:700;font-size:14px;">{symbol} '
        f'<span style="color:#555;font-size:10px;">#{rank}</span></div>'
        f'<div style="color:#555;font-size:11px;">{name}</div></div></div>'
        f'<div style="text-align:right;">'
        f'<div class="sv-mono" style="font-weight:700;font-size:13px;">{_price_fmt(price)}</div>'
        f'<div style="display:flex;gap:8px;justify-content:flex-end;">{_pct(p24)}'
        f'<span style="color:#444;font-size:10px;">7d {_pct(p7d, True)}</span></div>'
        f'</div></div>'
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_portfolio_history() -> list:
    """History changes once per day — no need to re-query Supabase per rerun."""
    return get_portfolio_history()


def _load_portfolio() -> tuple[dict, dict]:
    """Load portfolio from DB. Returns (portfolio_dict, tv_symbols_dict).
    Falls back to hardcoded defaults if DB is unavailable."""
    db_rows = get_portfolio()

    if not db_rows:
        # Seed DB from hardcoded defaults on first run
        seeded = all(
            upsert_portfolio_coin(
                coin_id=cid,
                symbol=meta["symbol"],
                qty=meta["qty"],
                staking_apy=meta.get("staking_apy"),
                staked=meta.get("staked", False),
                tv_symbol=_DEFAULT_TV_SYMBOLS.get(cid),
            )
            for cid, meta in _DEFAULT_PORTFOLIO.items()
        )
        if seeded:
            db_rows = get_portfolio()

    if not db_rows:
        # DB unavailable — use hardcoded defaults in-memory
        return (
            {cid: dict(meta) for cid, meta in _DEFAULT_PORTFOLIO.items()},
            dict(_DEFAULT_TV_SYMBOLS),
        )

    portfolio = {}
    tv_symbols = {}
    for row in db_rows:
        cid = row["coin_id"]
        portfolio[cid] = {"symbol": row["symbol"], "qty": float(row["qty"])}
        if row.get("staking_apy"):
            portfolio[cid]["staking_apy"] = float(row["staking_apy"])
        if row.get("staked"):
            portfolio[cid]["staked"] = bool(row["staked"])
        if row.get("tv_symbol"):
            tv_symbols[cid] = row["tv_symbol"]
        # Cost basis + price alerts (need sql/migrations.sql — keys absent before it runs)
        if row.get("avg_price") is not None:
            portfolio[cid]["avg_price"] = float(row["avg_price"])
        if row.get("target_above") is not None:
            portfolio[cid]["target_above"] = float(row["target_above"])
        if row.get("target_below") is not None:
            portfolio[cid]["target_below"] = float(row["target_below"])

    return portfolio, tv_symbols


def _render_portfolio_editor(portfolio: dict, tv_symbols: dict) -> None:
    """Inline data editor for portfolio holdings."""
    import pandas as pd

    with st.expander("✏️ Edit Portfolio", expanded=False):
        df = pd.DataFrame([
            {
                "coin_id":      cid,
                "symbol":       meta["symbol"],
                "qty":          float(meta["qty"]),
                "avg_price":    float(meta.get("avg_price") or 0),
                "staking_apy":  float(meta.get("staking_apy") or 0),
                "staked":       bool(meta.get("staked", False)),
                "target_above": float(meta.get("target_above") or 0),
                "target_below": float(meta.get("target_below") or 0),
                "tv_symbol":    tv_symbols.get(cid, ""),
            }
            for cid, meta in portfolio.items()
        ]) if portfolio else pd.DataFrame(
            columns=["coin_id", "symbol", "qty", "avg_price", "staking_apy",
                     "staked", "target_above", "target_below", "tv_symbol"]
        )

        edited = st.data_editor(
            df,
            num_rows="dynamic",
            column_config={
                "coin_id":      st.column_config.TextColumn("CoinGecko ID", required=True, width="medium"),
                "symbol":       st.column_config.TextColumn("Symbol", required=True, width="small"),
                "qty":          st.column_config.NumberColumn("Qty", min_value=0, format="%.4f", width="small"),
                "avg_price":    st.column_config.NumberColumn("Avg Buy $ (cost basis)", min_value=0, format="%.6f", width="small"),
                "staking_apy":  st.column_config.NumberColumn("Staking APY %", min_value=0, max_value=100, format="%.2f", width="small"),
                "staked":       st.column_config.CheckboxColumn("Staked", width="small"),
                "target_above": st.column_config.NumberColumn("🔔 Alert ≥ $", min_value=0, format="%.6f", width="small"),
                "target_below": st.column_config.NumberColumn("🔔 Alert ≤ $", min_value=0, format="%.6f", width="small"),
                "tv_symbol":    st.column_config.TextColumn("TradingView Symbol (e.g. BINANCE:RENDERUSDT)", width="large"),
            },
            hide_index=True,
            width="stretch",
            key="portfolio_editor",
        )

        if st.button("💾 Save Portfolio", key="save_portfolio"):
            old_ids = set(portfolio.keys())
            saved_ids = set()

            for _, row in edited.iterrows():
                cid = str(row.get("coin_id") or "").strip()
                sym = str(row.get("symbol") or "").strip().upper()
                if not cid or not sym:
                    continue
                qty = float(row.get("qty") or 0)
                apy = float(row.get("staking_apy") or 0) or None
                staked = bool(row.get("staked", False))
                tv = str(row.get("tv_symbol") or "").strip() or None
                avg_price = float(row.get("avg_price") or 0) or None
                t_above = float(row.get("target_above") or 0) or None
                t_below = float(row.get("target_below") or 0) or None
                upsert_portfolio_coin(cid, sym, qty, apy, staked, tv,
                                      avg_price=avg_price,
                                      target_above=t_above, target_below=t_below)
                saved_ids.add(cid)

            for removed_id in old_ids - saved_ids:
                delete_portfolio_coin(removed_id)

            st.success(f"Saved {len(saved_ids)} coins.")
            st.rerun()


def render():
    section_header("₿ Crypto Dashboard")

    # ── Load portfolio from DB ─────────────────────────────────────────────────
    portfolio, tv_symbols = _load_portfolio()
    portfolio_ids = tuple(portfolio.keys())
    news_keywords = {meta["symbol"].lower() for meta in portfolio.values()} | _EXTRA_NEWS_KEYWORDS

    # ── Portfolio ──────────────────────────────────────────────────────────────
    st.markdown("### My Portfolio")
    _render_portfolio_editor(portfolio, tv_symbols)

    with st.spinner("Loading portfolio…"):
        portfolio_coins = get_market_overview(portfolio_ids, include_sparkline=True)

    if portfolio_coins:
        lookup = {c["id"]: c for c in portfolio_coins}

        rows = []
        total_value = 0.0
        total_24h_pnl = 0.0
        total_invested = 0.0
        total_pnl = 0.0
        has_cost_basis = False
        staking_income_yr = 0.0
        alerts = []
        perfs = []

        for coin_id, meta in portfolio.items():
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

            # Unrealized PnL vs cost basis
            avg_buy = meta.get("avg_price")
            if avg_buy and price:
                has_cost_basis = True
                total_invested += qty * avg_buy
                total_pnl += value - qty * avg_buy

            # Staking income projection
            apy = meta.get("staking_apy")
            if apy and value > 0:
                staking_income_yr += value * apy / 100

            # Price alerts
            if price > 0:
                t_above = meta.get("target_above")
                t_below = meta.get("target_below")
                if t_above and price >= t_above:
                    alerts.append((meta["symbol"], "≥", t_above, price, WIN))
                if t_below and price <= t_below:
                    alerts.append((meta["symbol"], "≤", t_below, price, LOSS))

            rows.append((coin_id, cd, value))

        rows.sort(key=lambda x: x[2], reverse=True)

        # ── Triggered price alerts ──
        if alerts:
            alert_rows = "".join(
                f'<div style="font-size:13px;font-weight:600;color:{col};margin:2px 0;">'
                f'🔔 {sym} {op} ${tgt:,.4f} — now ${cur:,.4f}</div>'
                for sym, op, tgt, cur, col in alerts
            )
            st.markdown(
                card_html(
                    f'<div style="font-size:10px;color:{WARN};text-transform:uppercase;'
                    f'letter-spacing:1px;font-weight:700;margin-bottom:6px;">Price alerts triggered</div>'
                    + alert_rows,
                    accent=True, padding="12px 18px",
                ),
                unsafe_allow_html=True,
            )
            st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

        prev_total = total_value - total_24h_pnl
        pct_24h = (total_24h_pnl / prev_total * 100) if prev_total > 0 else 0
        col_24h = WIN if total_24h_pnl >= 0 else LOSS
        sign = "+" if total_24h_pnl >= 0 else ""

        best = max(perfs, key=lambda x: x[1]) if perfs else None
        worst = min(perfs, key=lambda x: x[1]) if perfs else None

        n_positions = sum(1 for _, cd, v in rows if v > 0)

        weights = [v / total_value for _, _, v in rows if v > 0 and total_value > 0]
        hhi = sum(w ** 2 for w in weights)
        div_score = round((1 - hhi) * 100)
        div_color = LOSS if div_score < 40 else WARN if div_score < 65 else WIN
        concentrated = [
            (portfolio[cid]["symbol"], v / total_value * 100)
            for cid, _, v in rows if total_value > 0 and v / total_value > 0.30
        ]
        div_html = (
            f'<div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.07);">'
            f'<div style="font-size:9px;color:{TEXT_FAINT};text-transform:uppercase;letter-spacing:1.2px;margin-bottom:4px;">Diversification Score</div>'
            f'<div class="sv-track" style="height:4px;margin-bottom:4px;">'
            f'<div class="sv-fill" style="height:4px;width:{div_score}%;background:{div_color};color:{div_color};"></div></div>'
            f'<div style="font-size:10px;color:{div_color};font-weight:600;">{div_score}/100'
            + "".join(
                f'&nbsp;&nbsp;<span style="color:{WARN};">⚠️ {sym} dominates at {pct:.1f}%</span>'
                for sym, pct in concentrated
            )
            + f'</div></div>'
        )

        insights_html = ""
        if best and worst and best[0] != worst[0]:
            insights_html = (
                f'<div style="padding-top:2px;display:flex;justify-content:space-between;">'
                f'<div>'
                f'<div style="font-size:9px;color:{TEXT_FAINT};text-transform:uppercase;letter-spacing:1.2px;margin-bottom:3px;">Best Today</div>'
                f'<div style="font-size:12px;color:{WIN};font-weight:700;">{best[0]}&nbsp;▲&nbsp;{best[1]:.1f}%</div>'
                f'</div>'
                f'<div style="text-align:right;">'
                f'<div style="font-size:9px;color:{TEXT_FAINT};text-transform:uppercase;letter-spacing:1.2px;margin-bottom:3px;">Worst Today</div>'
                f'<div style="font-size:12px;color:{LOSS};font-weight:700;">{worst[0]}&nbsp;▼&nbsp;{abs(worst[1]):.1f}%</div>'
                f'</div>'
                f'</div>'
            )

        # Animated count-up headline (ReactBits CountUp style)
        if has_cost_basis:
            tc1, tc2, tc3, tc4 = st.columns([2, 2, 2, 1])
        else:
            tc1, tc2, tc4 = st.columns([2, 2, 1])
            tc3 = None
        with tc1:
            count_up(total_value, prefix="$", decimals=2,
                     label="Total Portfolio Value", size=30)
        with tc2:
            count_up(abs(total_24h_pnl), prefix=f"{sign}$", decimals=2,
                     label=f"24h PnL ({sign}{pct_24h:.1f}%)", size=30, color=col_24h)
        if tc3 is not None:
            pnl_sign = "+" if total_pnl >= 0 else "−"
            pnl_col = WIN if total_pnl >= 0 else LOSS
            pnl_pct_total = (total_pnl / total_invested * 100) if total_invested > 0 else 0
            with tc3:
                count_up(abs(total_pnl), prefix=f"{pnl_sign}$", decimals=2,
                         label=f"Total PnL ({pnl_sign}{abs(pnl_pct_total):.1f}%)",
                         size=30, color=pnl_col)
        with tc4:
            count_up(n_positions, label="Positions", size=30)

        # Staking income projection
        staking_html = ""
        if staking_income_yr > 0:
            staking_html = (
                f'<div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.07);'
                f'display:flex;justify-content:space-between;align-items:center;">'
                f'<span style="font-size:9px;color:{TEXT_FAINT};text-transform:uppercase;letter-spacing:1.2px;">⚡ Staking income</span>'
                f'<span class="sv-mono" style="font-size:12px;color:{WIN};font-weight:700;">'
                f'≈ ${staking_income_yr / 12:,.2f}/mo · ${staking_income_yr:,.2f}/yr</span>'
                f'</div>'
            )

        st.markdown(
            card_html(insights_html + staking_html + div_html, accent=True, padding="14px 20px"),
            unsafe_allow_html=True,
        )

        # ── Daily snapshot + value-over-time chart ──
        if not st.session_state.get("_pf_snapshot_saved"):
            save_portfolio_snapshot(datetime.now().date().isoformat(), total_value, total_24h_pnl)
            st.session_state["_pf_snapshot_saved"] = True

        history = _cached_portfolio_history()
        if len(history) >= 2:
            with st.expander("📈 Portfolio value history"):
                import plotly.graph_objects as go
                dates = [h["date"] for h in history]
                values = [float(h["total_value"]) for h in history]
                line_col = WIN if values[-1] >= values[0] else LOSS
                fig = go.Figure(go.Scatter(
                    x=dates, y=values, mode="lines",
                    line=dict(color=line_col, width=2.5, shape="spline"),
                    fill="tozeroy",
                    fillcolor=f"rgba({'52,211,153' if values[-1] >= values[0] else '248,113,113'},0.08)",
                    hovertemplate="%{x}<br><b>$%{y:,.2f}</b><extra></extra>",
                ))
                fig.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=10, b=10, l=10, r=10), height=260,
                    xaxis=dict(showgrid=False, color="#555"),
                    yaxis=dict(gridcolor="rgba(255,255,255,0.05)", color="#555",
                               tickprefix="$", tickformat=",.0f"),
                )
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

        _SORT_KEY = {
            "Allocation":  lambda r: r[2],
            "24h change":  lambda r: (r[1].get("price_change_percentage_24h_in_currency") or 0) if r[1] else 0,
            "7d change":   lambda r: (r[1].get("price_change_percentage_7d_in_currency") or 0) if r[1] else 0,
            "Market cap":  lambda r: (r[1].get("market_cap") or 0) if r[1] else 0,
        }
        sort_by = st.radio(
            "Sort by",
            list(_SORT_KEY.keys()),
            horizontal=True,
            label_visibility="collapsed",
            key="portfolio_sort",
        )
        rows.sort(key=_SORT_KEY[sort_by], reverse=True)

        _render_allocation_pie(rows, total_value, portfolio)
        _render_portfolio_rows(rows, total_value, portfolio, tv_symbols)
    else:
        st.info("Portfolio data unavailable — CoinGecko may be rate-limited. Try again in a moment.")

    st.divider()

    # ── Global market context ─────────────────────────────────────────────────
    g = get_global()
    if g and g.get("btc_dominance"):
        mcap_t = (g.get("total_mcap_usd") or 0) / 1_000_000_000_000
        mc_chg = g.get("mcap_change_24h") or 0
        mc_col = WIN if mc_chg >= 0 else LOSS
        mc_arrow = "▲" if mc_chg >= 0 else "▼"
        gc1, gc2, gc3 = st.columns(3)
        tile = (
            '<div class="sv-card" style="padding:10px 14px;text-align:center;">'
            '<div style="font-size:9px;color:{f};text-transform:uppercase;letter-spacing:1px;">{label}</div>'
            '<div class="sv-mono" style="font-size:17px;font-weight:700;color:{col};">{val}</div>'
            '</div>'
        )
        gc1.markdown(tile.format(f=TEXT_FAINT, label="BTC Dominance", col="#fb923c",
                                 val=f"{g['btc_dominance']:.1f}%"), unsafe_allow_html=True)
        gc2.markdown(tile.format(f=TEXT_FAINT, label="Total Market Cap", col="#e6e9f2",
                                 val=f"${mcap_t:,.2f}T"), unsafe_allow_html=True)
        gc3.markdown(tile.format(f=TEXT_FAINT, label="MCap 24h", col=mc_col,
                                 val=f"{mc_arrow} {abs(mc_chg):.1f}%"), unsafe_allow_html=True)
        st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

    # ── Fear & Greed ──────────────────────────────────────────────────────────
    fng = get_fear_greed()
    fng_history = get_fear_greed_history(30)
    if fng:
        val = int(fng.get("value", 50))
        label, color = _fng_label(val)
        fng_spark = _sparkline_svg(fng_history, width=120, height=28) if fng_history else ""
        ring_pct = val * 3.6
        fng_ring = (
            f'<div style="width:58px;height:58px;border-radius:50%;flex-shrink:0;'
            f'background:conic-gradient({color} {ring_pct}deg, rgba(255,255,255,0.07) {ring_pct}deg);'
            f'display:flex;align-items:center;justify-content:center;'
            f'box-shadow:0 0 18px {color}33;">'
            f'<div class="sv-mono" style="width:46px;height:46px;border-radius:50%;background:#0d1119;'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:18px;font-weight:700;color:{color};">{val}</div>'
            f'</div>'
        )
        st.markdown(
            card_html(
                f'<div style="display:flex;align-items:center;gap:20px;">'
                f'{fng_ring}'
                f'<div style="flex:1;"><div style="font-size:15px;font-weight:700;color:{color}">{label}</div>'
                f'<div style="color:#555;font-size:11px;">Fear &amp; Greed Index · 30-day trend</div></div>'
                f'{fng_spark}'
                f'</div>',
                padding="12px 20px",
            ),
            unsafe_allow_html=True,
        )
        st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)

    # ── Watchlist ──────────────────────────────────────────────────────────────
    st.markdown("### My Watchlist")
    with st.spinner("Loading watchlist…"):
        coins = get_market_overview(_WATCHLIST_IDS)

    if coins:
        sorted_coins = sorted(coins, key=lambda c: _SIG_ORDER[_compute_signal(c)])
        buy_count = sum(1 for c in sorted_coins if _compute_signal(c) in ("STRONG BUY", "BUY"))
        if buy_count:
            st.markdown(
                f'<div style="color:{WIN};font-size:12px;margin-bottom:8px;">'
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
    st.caption("Filtered to your portfolio holdings only")
    with st.spinner("Loading headlines…"):
        news = get_news(100)

    if news:
        portfolio_news = [
            n for n in news
            if any(kw in n.get("title", "").lower() for kw in news_keywords)
        ]

        if not portfolio_news:
            st.info("No news about your holdings right now.")
        else:
            for item in portfolio_news[:12]:
                title = item.get("title", "")
                url = item.get("url", "")
                source = item.get("source", "")
                pub = item.get("published", "")[:16]
                st.markdown(
                    f'<div style="border-left:3px solid {WIN};padding:8px 14px;margin-bottom:8px;'
                    f'background:rgba(255,255,255,0.02);border-radius:0 8px 8px 0;">'
                    f'<a href="{url}" target="_blank" style="color:#e6e9f2;text-decoration:none;'
                    f'font-weight:600;font-size:14px">{title}</a>'
                    f'<div style="color:#555;font-size:11px;margin-top:3px">{source} · {pub}</div></div>',
                    unsafe_allow_html=True,
                )
    else:
        st.info("News unavailable.")
