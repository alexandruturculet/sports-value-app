import json
import xml.etree.ElementTree as ET
import logging
import requests
import streamlit as st
import streamlit.components.v1 as components
from services.yfinance_client import get_quotes, get_signals, get_sector_performance, get_sparklines
from services.supabase_client import get_stock_portfolio, upsert_stock_position, delete_stock_position
from ui.components import LOSS, SIG_STYLE, WIN, section_header

logger = logging.getLogger(__name__)

_OVERVIEW_TICKERS = ("SPY", "QQQ", "DIA", "IWM", "^VIX")
_OVERVIEW_NAMES = {
    "SPY": "S&P 500 ETF", "QQQ": "Nasdaq 100 ETF",
    "DIA": "Dow Jones ETF", "IWM": "Russell 2000 ETF", "^VIX": "Volatility Index",
}

_SECTORS = ("XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLB", "XLP", "XLU", "XLRE")
_SECTOR_NAMES = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
    "XLV": "Health Care", "XLY": "Consumer Disc.", "XLI": "Industrials",
    "XLB": "Materials", "XLP": "Consumer Stap.", "XLU": "Utilities",
    "XLRE": "Real Estate",
}

_DATA_CENTER_STACK = {
    "Energy": {
        "tickers": ("CEG", "VST", "OKLO", "EOSE", "GEV", "NEOV"),
        "accent": "#FB923C",
        "icon": "⚡",
    },
    "Chips & Computing": {
        "tickers": ("NVDA", "AMD", "TSM", "MU", "ARM", "RGTI", "ARQQ"),
        "accent": "#818CF8",
        "icon": "💎",
    },
    "Cloud / Data Centers": {
        "tickers": ("NBIS", "IREN", "CRWV", "APLD", "CIFR", "CORZ", "WYFI", "RAMP"),
        "accent": "#34D399",
        "icon": "☁️",
    },
}

_ALL_STACK_TICKERS = tuple(
    t for cat in _DATA_CENTER_STACK.values() for t in cat["tickers"]
)

_DEFAULT_STOCK_PORTFOLIO = [
    {
        "ticker": "SEC0.DE",
        "name": "iShares MSCI Global Semiconductors Acc",
        "qty": round(170 / 16.31, 4),
        "avg_price": 16.31,
        "currency": "EUR",
        "tv_symbol": "XETR:SEC0",
    },
]

_NEWS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY,QQQ,NVDA,AMD,TSM"


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
    color = WIN if pct >= 0 else LOSS
    arrow = "▲" if pct >= 0 else "▼"
    return f'<span style="color:{color};font-weight:600">{arrow} {abs(pct):.2f}%</span>'


def _sparkline_svg(prices: list, width: int = 80, height: int = 28) -> str:
    if not prices or len(prices) < 2:
        return f'<div style="width:{width}px;height:{height}px;flex-shrink:0;"></div>'
    mn, mx = min(prices), max(prices)
    if mn == mx:
        return f'<div style="width:{width}px;height:{height}px;flex-shrink:0;"></div>'
    pad = 2
    n = len(prices)
    x_step = (width - pad * 2) / (n - 1)
    pts = []
    for i, p in enumerate(prices):
        x = round(pad + i * x_step, 1)
        y = round(height - pad - (p - mn) / (mx - mn) * (height - pad * 2), 1)
        pts.append(f"{x},{y}")
    color = WIN if prices[-1] >= prices[0] else LOSS
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


def _load_stock_portfolio() -> list:
    db_rows = get_stock_portfolio()

    if not db_rows:
        seeded = all(
            upsert_stock_position(
                ticker=p["ticker"],
                name=p["name"],
                qty=p["qty"],
                avg_price=p["avg_price"],
                currency=p["currency"],
                tv_symbol=p.get("tv_symbol"),
            )
            for p in _DEFAULT_STOCK_PORTFOLIO
        )
        if seeded:
            db_rows = get_stock_portfolio()

    if not db_rows:
        return [dict(p) for p in _DEFAULT_STOCK_PORTFOLIO]

    return [
        {
            "ticker": row["ticker"],
            "name": row.get("name") or "",
            "qty": float(row["qty"]),
            "avg_price": float(row["avg_price"]),
            "currency": row.get("currency") or "USD",
            "tv_symbol": row.get("tv_symbol") or "",
        }
        for row in db_rows
    ]


def _render_stock_portfolio_editor(positions: list) -> None:
    import pandas as pd

    with st.expander("✏️ Edit Portfolio", expanded=False):
        df = pd.DataFrame(positions) if positions else pd.DataFrame(
            columns=["ticker", "name", "qty", "avg_price", "currency", "tv_symbol"]
        )

        edited = st.data_editor(
            df,
            num_rows="dynamic",
            column_config={
                "ticker":    st.column_config.TextColumn("Ticker (yfinance)", required=True, width="small",
                             help="Use exchange suffix for non-US: e.g. SEC0.DE, SECO.AS"),
                "name":      st.column_config.TextColumn("Name", width="large"),
                "qty":       st.column_config.NumberColumn("Qty", min_value=0, format="%.4f", width="small"),
                "avg_price": st.column_config.NumberColumn("Avg Price", min_value=0, format="%.4f", width="small"),
                "currency":  st.column_config.SelectboxColumn("Currency", options=["USD", "EUR", "GBP"], width="small"),
                "tv_symbol": st.column_config.TextColumn("TradingView Symbol (e.g. XETR:SEC0, NASDAQ:NVDA)", width="large"),
            },
            hide_index=True,
            width="stretch",
            key="stock_portfolio_editor",
        )

        if st.button("💾 Save Portfolio", key="save_stock_portfolio"):
            old_tickers = {p["ticker"] for p in positions}
            saved_tickers = set()

            for _, row in edited.iterrows():
                ticker = str(row.get("ticker") or "").strip().upper()
                if not ticker:
                    continue
                name = str(row.get("name") or "").strip()
                qty = float(row.get("qty") or 0)
                avg_price = float(row.get("avg_price") or 0)
                currency = str(row.get("currency") or "USD").strip()
                tv_symbol = str(row.get("tv_symbol") or "").strip() or None
                upsert_stock_position(ticker, name, qty, avg_price, currency, tv_symbol)
                saved_tickers.add(ticker)

            for removed in old_tickers - saved_tickers:
                delete_stock_position(removed)

            st.success(f"Saved {len(saved_tickers)} positions.")
            st.rerun()


def _stock_portfolio_card(
    pos: dict, q: dict | None, total_invested_by_cur: dict,
    sparkline_prices: list, safe_id: str,
) -> str:
    ticker = pos["ticker"]
    name = pos.get("name") or ticker
    qty = pos["qty"]
    avg_price = pos["avg_price"]
    currency = pos.get("currency", "USD")
    invested = qty * avg_price

    current_price = q["price"] if q else None
    change_pct = q["change_pct"] if q else None
    current_value = qty * current_price if current_price else None

    pnl = current_value - invested if current_value is not None else None
    pnl_pct = pnl / invested * 100 if pnl is not None and invested > 0 else None

    cur_sym = {"EUR": "€", "GBP": "£"}.get(currency, "$")
    p24_val = change_pct or 0
    border_col = WIN if p24_val > 0 else LOSS if p24_val < 0 else "rgba(255,255,255,0.15)"
    pnl_color = WIN if (pnl or 0) >= 0 else LOSS
    chg_color = WIN if p24_val >= 0 else LOSS

    price_str = f"{cur_sym}{current_price:,.4f}" if current_price else "—"
    value_str = f"{cur_sym}{current_value:,.2f}" if current_value else "—"
    invested_str = f"{cur_sym}{invested:,.2f}"

    if pnl is not None and pnl_pct is not None:
        pnl_sign = "+" if pnl >= 0 else ""
        pnl_display = f"{pnl_sign}{cur_sym}{abs(pnl):.2f} ({pnl_sign}{pnl_pct:.1f}%)"
    else:
        pnl_display = "—"

    chg_str = (
        f"{'▲' if p24_val >= 0 else '▼'} {abs(change_pct):.2f}%"
    ) if change_pct is not None else "—"

    bar_pct = min(invested / (total_invested_by_cur.get(currency) or 1) * 100, 100)
    spark = _sparkline_svg(sparkline_prices)

    return (
        f'<div class="pf-row" style="border-left:3px solid {border_col};">'
        f'<div style="display:flex;align-items:center;gap:12px;">'
        f'<div style="flex:1;min-width:0;">'
        f'<div style="font-size:13px;font-weight:700;color:#f1f5f9;">{ticker}</div>'
        f'<div style="color:#4a4a4a;font-size:10px;margin-top:2px;">{name}</div>'
        f'<div style="color:#4a4a4a;font-size:10px;">{qty:,.4f} units · {currency}</div>'
        f'</div>'
        f'<div data-chart-id="{safe_id}" title="Click to open TradingView chart" style="flex-shrink:0;cursor:pointer;">{spark}</div>'
        f'<div style="text-align:center;flex-shrink:0;min-width:76px;">'
        f'<div style="font-size:11px;color:#666;margin-bottom:2px;">{price_str}</div>'
        f'<div style="font-size:10px;color:{chg_color};font-weight:600;">{chg_str}</div>'
        f'</div>'
        f'<div style="text-align:right;flex-shrink:0;min-width:110px;">'
        f'<div style="font-weight:700;font-size:13px;color:#f1f5f9;">{value_str}</div>'
        f'<div style="font-size:10px;color:{pnl_color};margin-top:2px;">{pnl_display}</div>'
        f'<div style="font-size:9px;color:#3a3a3a;margin-top:1px;">inv: {invested_str}</div>'
        f'</div>'
        f'</div>'
        f'<div style="margin-top:8px;height:2px;background:rgba(255,255,255,0.07);border-radius:1px;">'
        f'<div style="height:2px;width:{bar_pct:.1f}%;background:#818CF8;border-radius:1px;box-shadow:0 0 6px #818CF8;"></div>'
        f'</div>'
        f'</div>'
    )


def _render_stock_portfolio(positions: list, quotes: dict, sparklines: dict) -> None:
    if not positions:
        return

    total_invested_by_cur: dict[str, float] = {}
    for p in positions:
        cur = p.get("currency", "USD")
        total_invested_by_cur[cur] = total_invested_by_cur.get(cur, 0) + p["qty"] * p["avg_price"]

    tv_safe = {
        p["ticker"].replace(".", "_").replace("-", "_"): p["tv_symbol"]
        for p in positions if p.get("tv_symbol")
    }

    cards_html = ""
    for pos in positions:
        ticker = pos["ticker"]
        safe_id = ticker.replace(".", "_").replace("-", "_")
        sparkline_prices = sparklines.get(ticker, [])
        cards_html += _stock_portfolio_card(
            pos, quotes.get(ticker), total_invested_by_cur, sparkline_prices, safe_id
        )
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
    }}else if(!TV[id]){{
      document.getElementById('tv_'+id).innerHTML='<div style="padding:20px;color:#555;font-size:12px;text-align:center;">No TradingView symbol set — open ✏️ Edit Portfolio and add it (e.g. XETR:SEC0, NASDAQ:NVDA)</div>';
    }}
  }}else{{c.style.display='none';active=null;}}
}}
</script></body></html>"""
    components.html(html, height=len(positions) * 80 + 460, scrolling=False)


def _render_data_center_stack(signals: dict, quotes: dict) -> None:
    for category, config in _DATA_CENTER_STACK.items():
        accent = config["accent"]
        icon = config["icon"]
        tickers = config["tickers"]

        st.markdown(
            f'<div style="font-size:12px;font-weight:700;color:{accent};text-transform:uppercase;'
            f'letter-spacing:1.2px;margin:16px 0 8px;">{icon} {category}</div>',
            unsafe_allow_html=True,
        )

        cols = st.columns(len(tickers))
        for col, ticker in zip(cols, tickers):
            q = quotes.get(ticker) or {}
            s = signals.get(ticker) or {}
            price = q.get("price") or s.get("price")
            change_pct = q.get("change_pct")
            signal = s.get("signal", "HOLD")

            sig_bg, sig_color, sig_icon = SIG_STYLE[signal]
            chg_color = WIN if (change_pct or 0) >= 0 else LOSS
            chg_arrow = "▲" if (change_pct or 0) >= 0 else "▼"
            price_str = f"${price:,.2f}" if price else "—"
            chg_str = f"{chg_arrow} {abs(change_pct):.1f}%" if change_pct is not None else "—"
            sig_short = signal.replace("STRONG BUY", "S.BUY").replace("STRONG SELL", "S.SELL")

            col.markdown(
                f'<div class="sv-card" style="border-top:2px solid {accent};'
                f'padding:10px 8px;text-align:center;">'
                f'<div style="font-weight:800;font-size:13px;color:#f1f5f9;">{ticker}</div>'
                f'<div class="sv-mono" style="font-size:11px;color:#94a3b8;margin:3px 0;">{price_str}</div>'
                f'<div style="font-size:10px;color:{chg_color};margin-bottom:5px;">{chg_str}</div>'
                f'<span style="background:{sig_bg};color:{sig_color};font-size:8px;padding:2px 6px;'
                f'border-radius:10px;font-weight:700;">{sig_icon} {sig_short}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )


def render():
    section_header("📈 Markets Dashboard")

    # ── My Stock Portfolio ─────────────────────────────────────────────────────
    st.markdown("### My Stock Portfolio")
    positions = _load_stock_portfolio()
    _render_stock_portfolio_editor(positions)

    if positions:
        portfolio_tickers = tuple(p["ticker"] for p in positions)
        with st.spinner("Loading portfolio prices…"):
            portfolio_quotes = get_quotes(portfolio_tickers)
            portfolio_sparklines = get_sparklines(portfolio_tickers)
        _render_stock_portfolio(positions, portfolio_quotes, portfolio_sparklines)

    st.divider()

    # ── Data Center Stack ──────────────────────────────────────────────────────
    st.markdown("### Data Center Stack")
    st.caption("Energy · Chips & Computing · Cloud / Data Centers")
    with st.spinner("Loading Data Center Stack…"):
        stack_quotes = get_quotes(_ALL_STACK_TICKERS)
        stack_signals = get_signals(_ALL_STACK_TICKERS)
    _render_data_center_stack(stack_signals, stack_quotes)

    st.divider()

    # ── Market Overview ────────────────────────────────────────────────────────
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
            col.markdown(
                f'<div class="sv-card" style="padding:14px;text-align:center;margin-bottom:8px">'
                f'<div style="color:#555;font-size:11px">{name}</div>'
                f'<div class="sv-mono" style="font-size:20px;font-weight:800">{price:,.2f}</div>'
                f'<div style="font-size:13px;margin-top:4px">{badge}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        st.info("Market data unavailable. yfinance may be rate-limited — try again shortly.")

    # ── Sector Rotation ────────────────────────────────────────────────────────
    st.markdown("### Sector Rotation (1-Week)")
    with st.spinner("Loading sector data…"):
        sector_perf = get_sector_performance(_SECTORS)

    if sector_perf:
        sorted_sectors = sorted(sector_perf.items(), key=lambda x: x[1], reverse=True)
        max_abs = max(abs(v) for v in sector_perf.values()) or 1
        for ticker, pct in sorted_sectors:
            name = _SECTOR_NAMES.get(ticker, ticker)
            bar_width = int(abs(pct) / max_abs * 60)
            color = WIN if pct >= 0 else LOSS
            arrow = "▲" if pct >= 0 else "▼"
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:6px">'
                f'<div style="width:130px;color:#aaa;font-size:13px">{name}</div>'
                f'<div style="width:{bar_width + 60}px;background:{color};height:8px;border-radius:4px;'
                f'opacity:0.75;box-shadow:0 0 8px {color}66;"></div>'
                f'<div style="color:{color};font-weight:600;font-size:13px">{arrow} {abs(pct):.2f}%</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        st.info("Sector data unavailable.")

    # ── AI Trade Signals ───────────────────────────────────────────────────────
    st.markdown("### AI Trade Signals")
    raw_watchlist = st.text_input(
        "Watchlist tickers (comma-separated)",
        value=",".join(_ALL_STACK_TICKERS),
        help="Enter any US stock/ETF tickers separated by commas",
    )
    tickers = tuple(t.strip().upper() for t in raw_watchlist.split(",") if t.strip())

    if tickers:
        with st.spinner(f"Computing signals for {len(tickers)} tickers…"):
            signals = get_signals(tickers)

        if signals:
            for ticker, data in signals.items():
                sig = data["signal"]
                bg, color, icon = SIG_STYLE[sig]
                rsi = data["rsi"]
                ma_diff = data["ma_diff_pct"]
                price = data["price"]
                ma_color = WIN if ma_diff >= 0 else LOSS
                ma_sign = "+" if ma_diff >= 0 else ""
                st.markdown(
                    f'<div class="sv-card" style="border-color:{color}44;'
                    f'padding:12px 18px;margin-bottom:8px;display:flex;'
                    f'align-items:center;justify-content:space-between">'
                    f'<div>'
                    f'<span style="font-weight:800;font-size:16px">{ticker}</span>'
                    f'<span class="sv-mono" style="color:#555;font-size:12px;margin-left:8px">${price:,.2f}</span>'
                    f'</div>'
                    f'<div style="display:flex;gap:20px;align-items:center">'
                    f'<div style="text-align:center">'
                    f'<div style="color:#888;font-size:10px">RSI-14</div>'
                    f'<div class="sv-mono" style="font-weight:700;font-size:14px">{rsi}</div>'
                    f'</div>'
                    f'<div style="text-align:center">'
                    f'<div style="color:#888;font-size:10px">MA5 vs MA20</div>'
                    f'<div class="sv-mono" style="font-weight:700;font-size:14px;color:{ma_color}">{ma_sign}{ma_diff}%</div>'
                    f'</div>'
                    f'<span style="background:{bg};color:{color};font-weight:700;font-size:12px;'
                    f'padding:4px 12px;border-radius:12px">{icon} {sig}</span>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("Signal computation failed — tickers may be invalid or yfinance is rate-limited.")

    # ── Market News ────────────────────────────────────────────────────────────
    st.markdown("### Market News")
    with st.spinner("Loading headlines…"):
        news = _get_market_news()

    if news:
        for item in news:
            st.markdown(
                f'<div style="border-left:3px solid #818CF8;padding:8px 14px;margin-bottom:8px;'
                f'background:rgba(255,255,255,0.02);border-radius:0 8px 8px 0;">'
                f'<a href="{item["url"]}" target="_blank" style="color:#e6e9f2;text-decoration:none;'
                f'font-weight:600;font-size:14px">{item["title"]}</a>'
                f'<div style="color:#555;font-size:11px;margin-top:3px">Yahoo Finance · {item["published"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        st.info("News unavailable.")
