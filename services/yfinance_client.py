import logging
import streamlit as st

logger = logging.getLogger(__name__)


def _import_yf():
    try:
        import yfinance as yf
        return yf
    except ImportError:
        logger.error("yfinance not installed")
        return None


def _rsi(closes, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = closes.diff().dropna()
    gains = deltas.clip(lower=0)
    losses = (-deltas).clip(lower=0)
    avg_gain = gains.iloc[:period].mean()
    avg_loss = losses.iloc[:period].mean()
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains.iloc[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses.iloc[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _signal(rsi: float, ma5: float, ma20: float) -> str:
    cross_up = ma5 > ma20
    if rsi < 30 and cross_up:
        return "STRONG BUY"
    if rsi < 45 and cross_up:
        return "BUY"
    if rsi > 75 and not cross_up:
        return "STRONG SELL"
    if rsi > 65 and not cross_up:
        return "SELL"
    return "HOLD"


@st.cache_data(ttl=300)
def get_quotes(tickers: tuple) -> dict:
    """Current price + 1-day change % for each ticker."""
    yf = _import_yf()
    if not yf:
        return {}
    result = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            price = info.last_price
            prev = info.previous_close
            change_pct = ((price - prev) / prev * 100) if prev else 0.0
            result[ticker] = {
                "price": round(price, 2),
                "prev_close": round(prev, 2),
                "change_pct": round(change_pct, 2),
            }
        except Exception as e:
            logger.warning("Quote failed for %s: %s", ticker, e)
    return result


@st.cache_data(ttl=600)
def get_signals(tickers: tuple) -> dict:
    """MA5/MA20/RSI-14 signal for each ticker using 3-month daily history."""
    yf = _import_yf()
    if not yf:
        return {}
    result = {}
    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).history(period="3mo")
            if hist.empty or len(hist) < 22:
                continue
            closes = hist["Close"]
            ma5 = float(closes.tail(5).mean())
            ma20 = float(closes.tail(20).mean())
            rsi = _rsi(closes)
            ma_diff_pct = round((ma5 - ma20) / ma20 * 100, 2)
            result[ticker] = {
                "rsi": rsi,
                "ma5": round(ma5, 2),
                "ma20": round(ma20, 2),
                "ma_diff_pct": ma_diff_pct,
                "signal": _signal(rsi, ma5, ma20),
                "price": round(float(closes.iloc[-1]), 2),
            }
        except Exception as e:
            logger.warning("Signal failed for %s: %s", ticker, e)
    return result


@st.cache_data(ttl=900)
def get_sector_performance(tickers: tuple) -> dict:
    """1-week % change for sector ETFs."""
    yf = _import_yf()
    if not yf:
        return {}
    result = {}
    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).history(period="8d")
            if len(hist) < 2:
                continue
            start = float(hist["Close"].iloc[0])
            end = float(hist["Close"].iloc[-1])
            result[ticker] = round((end - start) / start * 100, 2)
        except Exception as e:
            logger.warning("Sector perf failed for %s: %s", ticker, e)
    return result
