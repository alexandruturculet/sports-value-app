import xml.etree.ElementTree as ET
import logging
import requests
import streamlit as st
from services.yfinance_client import get_quotes, get_signals, get_sector_performance
from services.supabase_client import get_stock_portfolio, upsert_stock_position, delete_stock_position

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

_DATA_CENTER_STACK = {
    "Energy": {
        "tickers": ("CEG", "VST", "OKLO", "EOSE", "GEV"),
        "accent": "#FB923C",
        "icon": "⚡",
    },
    "Chips & Computing": {
        "tickers": ("NVDA", "AMD", "TSM", "MU", "ARM"),
        "accent": "#818CF8",
        "icon": "💎",
    },
    "Cloud / Data Centers": {
        "tickers": ("NBIS", "IREN", "CRWV", "APLD", "CIFR"),
        "accent": "#34D399",
        "icon": "☁️",
    },
}

_ALL_STACK_TICKERS = tuple(
    t for cat in _DATA_CENTER_STACK.values() for t in cat["tickers"]
)

_DEFAULT_STOCK_PORTFOLIO = [
    {
        "ticker": "SEC0.AS",
        "name": "iShares MSCI Global Semiconductors Acc",
        "qty": round(170 / 16.31, 4),
        "avg_price": 16.31,
        "currency": "EUR",
    },
]

_SIG_STYLE = {
    "STRONG BUY":  ("#0d2b0d", "#4caf50", "▲▲"),
    "BUY":         ("#0d1f0d", "#81c784", "▲"),
    "HOLD":        ("#1a1a1a", "#9e9e9e", "—"),
    "SELL":        ("#2b0d0d", "#ef5350", "▼"),
    "STRONG SELL": ("#1f0d0d", "#b71c1c", "▼▼"),
}

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
    color = "#4caf50" if pct >= 0 else "#f44336"
    arrow = "▲" if pct >= 0 else "▼"
    return f'<span style="color:{color};font-weight:600">{arrow} {abs(pct):.2f}%</span>'


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
        }
        for row in db_rows
    ]


def _render_stock_portfolio_editor(positions: list) -> None:
    import pandas as pd

    with st.expander("✏️ Edit Portfolio", expanded=False):
        df = pd.DataFrame(positions) if positions else pd.DataFrame(
            columns=["ticker", "name", "qty", "avg_price", "currency"]
        )

        edited = st.data_editor(
            df,
            num_rows="dynamic",
            column_config={
                "ticker":    st.column_config.TextColumn("Ticker (yfinance)", required=True, width="small",
                             help="Use exchange suffix for non-US: e.g. SECO.AS, SECO.PA, SECO.L"),
                "name":      st.column_config.TextColumn("Name", width="large"),
                "qty":       st.column_config.NumberColumn("Qty", min_value=0, format="%.4f", width="small"),
                "avg_price": st.column_config.NumberColumn("Avg Price", min_value=0, format="%.4f", width="small"),
                "currency":  st.column_config.SelectboxColumn("Currency", options=["USD", "EUR", "GBP"], width="small"),
            },
            hide_index=True,
            use_container_width=True,
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
                upsert_stock_position(ticker, name, qty, avg_price, currency)
                saved_tickers.add(ticker)

            for removed in old_tickers - saved_tickers:
                delete_stock_position(removed)

            st.success(f"Saved {len(saved_tickers)} positions.")
            st.rerun()


def _render_stock_portfolio(positions: list, quotes: dict) -> None:
    if not positions:
        return

    total_invested_by_cur: dict[str, float] = {}
    for p in positions:
        cur = p.get("currency", "USD")
        total_invested_by_cur[cur] = total_invested_by_cur.get(cur, 0) + p["qty"] * p["avg_price"]

    for pos in positions:
        ticker = pos["ticker"]
        name = pos.get("name") or ticker
        qty = pos["qty"]
        avg_price = pos["avg_price"]
        currency = pos.get("currency", "USD")
        invested = qty * avg_price

        q = quotes.get(ticker)
        current_price = q["price"] if q else None
        change_pct = q["change_pct"] if q else None
        current_value = qty * current_price if current_price else None

        pnl = current_value - invested if current_value is not None else None
        pnl_pct = pnl / invested * 100 if pnl is not None and invested > 0 else None

        cur_sym = {"EUR": "€", "GBP": "£"}.get(currency, "$")
        pnl_color = "#34D399" if (pnl or 0) >= 0 else "#F87171"
        chg_color = "#34D399" if (change_pct or 0) >= 0 else "#F87171"

        price_str = f"{cur_sym}{current_price:,.4f}" if current_price else "—"
        value_str = f"{cur_sym}{current_value:,.2f}" if current_value else "—"
        invested_str = f"{cur_sym}{invested:,.2f}"

        if pnl is not None and pnl_pct is not None:
            pnl_sign = "+" if pnl >= 0 else ""
            pnl_str = f"{pnl_sign}{cur_sym}{abs(pnl):.2f} ({pnl_sign}{pnl_pct:.1f}%)"
        else:
            pnl_str = "Price unavailable"

        chg_str = (
            f"{'▲' if (change_pct or 0) >= 0 else '▼'} {abs(change_pct):.2f}% today"
        ) if change_pct is not None else ""

        bar_pct = min(invested / (total_invested_by_cur.get(currency) or 1) * 100, 100)

        st.markdown(
            f'<div style="background:#0a0d14;border:1px solid #1e2535;border-left:3px solid #818CF8;'
            f'border-radius:8px;padding:14px 16px;margin-bottom:8px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">'
            f'<div>'
            f'<span style="font-size:15px;font-weight:800;color:#f1f5f9;">{ticker}</span>'
            f'<span style="font-size:10px;color:#475569;margin-left:8px;">{name}</span>'
            f'<div style="font-size:10px;color:#475569;margin-top:2px;">{qty:,.4f} units · {currency}</div>'
            f'</div>'
            f'<div style="text-align:right;">'
            f'<div style="font-size:16px;font-weight:800;color:#f1f5f9;">{value_str}</div>'
            f'<div style="font-size:10px;color:{chg_color};margin-top:2px;">{chg_str}</div>'
            f'</div>'
            f'</div>'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
            f'<div style="font-size:11px;color:#94a3b8;">Invested: <b>{invested_str}</b> @ {cur_sym}{avg_price:.4f}</div>'
            f'<div style="font-size:12px;color:{pnl_color};font-weight:700;">{pnl_str}</div>'
            f'</div>'
            f'<div style="height:2px;background:#1a2030;border-radius:1px;">'
            f'<div style="height:2px;width:{bar_pct:.1f}%;background:#818CF8;border-radius:1px;"></div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )


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

            _, sig_color, sig_icon = _SIG_STYLE[signal]
            chg_color = "#4caf50" if (change_pct or 0) >= 0 else "#f44336"
            chg_arrow = "▲" if (change_pct or 0) >= 0 else "▼"
            price_str = f"${price:,.2f}" if price else "—"
            chg_str = f"{chg_arrow} {abs(change_pct):.1f}%" if change_pct is not None else "—"
            sig_short = signal.replace("STRONG BUY", "S.BUY").replace("STRONG SELL", "S.SELL")

            col.markdown(
                f'<div style="background:#0d1117;border:1px solid #1e2535;border-top:2px solid {accent};'
                f'border-radius:8px;padding:10px 8px;text-align:center;">'
                f'<div style="font-weight:800;font-size:13px;color:#f1f5f9;">{ticker}</div>'
                f'<div style="font-size:11px;color:#94a3b8;margin:3px 0;">{price_str}</div>'
                f'<div style="font-size:10px;color:{chg_color};margin-bottom:5px;">{chg_str}</div>'
                f'<span style="background:{sig_color};color:#000;font-size:8px;padding:2px 5px;'
                f'border-radius:3px;font-weight:700;">{sig_icon} {sig_short}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )


def render():
    st.markdown("## 📈 Markets Dashboard")

    # ── My Stock Portfolio ─────────────────────────────────────────────────────
    st.markdown("### My Stock Portfolio")
    positions = _load_stock_portfolio()
    _render_stock_portfolio_editor(positions)

    if positions:
        portfolio_tickers = tuple(p["ticker"] for p in positions)
        with st.spinner("Loading portfolio prices…"):
            portfolio_quotes = get_quotes(portfolio_tickers)
        _render_stock_portfolio(positions, portfolio_quotes)

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
                f'<div style="background:#111;border:1px solid #222;border-radius:10px;'
                f'padding:14px;text-align:center;margin-bottom:8px">'
                f'<div style="color:#555;font-size:11px">{name}</div>'
                f'<div style="font-size:20px;font-weight:800">{price:,.2f}</div>'
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
            color = "#4caf50" if pct >= 0 else "#f44336"
            arrow = "▲" if pct >= 0 else "▼"
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:6px">'
                f'<div style="width:130px;color:#aaa;font-size:13px">{name}</div>'
                f'<div style="width:{bar_width + 60}px;background:{color};height:8px;border-radius:4px;opacity:0.7"></div>'
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
                bg, color, icon = _SIG_STYLE[sig]
                rsi = data["rsi"]
                ma_diff = data["ma_diff_pct"]
                price = data["price"]
                ma_color = "#4caf50" if ma_diff >= 0 else "#f44336"
                ma_sign = "+" if ma_diff >= 0 else ""
                st.markdown(
                    f'<div style="background:{bg};border:1px solid {color}44;border-radius:8px;'
                    f'padding:12px 18px;margin-bottom:8px;display:flex;'
                    f'align-items:center;justify-content:space-between">'
                    f'<div>'
                    f'<span style="font-weight:800;font-size:16px">{ticker}</span>'
                    f'<span style="color:#555;font-size:12px;margin-left:8px">${price:,.2f}</span>'
                    f'</div>'
                    f'<div style="display:flex;gap:20px;align-items:center">'
                    f'<div style="text-align:center">'
                    f'<div style="color:#888;font-size:10px">RSI-14</div>'
                    f'<div style="font-weight:700;font-size:14px">{rsi}</div>'
                    f'</div>'
                    f'<div style="text-align:center">'
                    f'<div style="color:#888;font-size:10px">MA5 vs MA20</div>'
                    f'<div style="font-weight:700;font-size:14px;color:{ma_color}">{ma_sign}{ma_diff}%</div>'
                    f'</div>'
                    f'<span style="background:{color};color:#000;font-weight:700;font-size:12px;'
                    f'padding:4px 12px;border-radius:4px">{icon} {sig}</span>'
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
                f'<div style="border-left:3px solid #333;padding:8px 14px;margin-bottom:8px">'
                f'<a href="{item["url"]}" target="_blank" style="color:#e0e0e0;text-decoration:none;'
                f'font-weight:600;font-size:14px">{item["title"]}</a>'
                f'<div style="color:#555;font-size:11px;margin-top:3px">Yahoo Finance · {item["published"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        st.info("News unavailable.")
