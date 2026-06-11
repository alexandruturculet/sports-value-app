"""Reusable UI components — ReactBits-style effects in pure HTML/CSS/JS.

HTML-string helpers return markup to embed; render helpers draw directly.
All styling tokens match assets/styles.css.
"""
import streamlit as st
import streamlit.components.v1 as components

# ── Design tokens ──────────────────────────────────────────────────────────────

ACCENT_CYAN = "#22d3ee"
ACCENT_VIOLET = "#a78bfa"
ACCENT_MINT = "#34d399"
WIN = "#34d399"
LOSS = "#f87171"
WARN = "#fbbf24"
TEXT = "#e6e9f2"
TEXT_DIM = "rgba(230,233,242,0.45)"
TEXT_FAINT = "rgba(230,233,242,0.28)"

# Prediction market → (bg, fg) pill colors
PRED_STYLE = {
    "1":         ("rgba(52,211,153,0.14)",  "#34d399"),
    "2":         ("rgba(96,165,250,0.14)",  "#60a5fa"),
    "X":         ("rgba(251,191,36,0.14)",  "#fbbf24"),
    "1X":        ("rgba(52,211,153,0.10)",  "#6ee7b7"),
    "X2":        ("rgba(167,139,250,0.14)", "#a78bfa"),
    "BTTS":      ("rgba(34,211,238,0.14)",  "#22d3ee"),
    "Over 2.5":  ("rgba(251,146,60,0.14)",  "#fb923c"),
    "Under 2.5": ("rgba(192,132,252,0.14)", "#c084fc"),
}

# Buy/sell signal → (bg, fg, arrow) — shared by crypto & markets sections
SIG_STYLE = {
    "STRONG BUY":  ("rgba(52,211,153,0.16)", "#34d399", "▲▲"),
    "BUY":         ("rgba(52,211,153,0.10)", "#6ee7b7", "▲"),
    "HOLD":        ("rgba(255,255,255,0.07)", "#9aa3b5", "—"),
    "SELL":        ("rgba(248,113,113,0.12)", "#f87171", "▼"),
    "STRONG SELL": ("rgba(248,113,113,0.18)", "#ef4444", "▼▼"),
}


def conf_color(conf: float) -> str:
    if conf >= 72:
        return WIN
    if conf >= 58:
        return WARN
    return LOSS


# ── Text ───────────────────────────────────────────────────────────────────────

def gradient_title(text: str, size: int = 38, subtitle: str = "") -> None:
    """Shimmering gradient headline (split-text style)."""
    sub = f'<div class="sv-subtitle">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<h1 class="sv-title" style="font-size:{size}px;">{text}</h1>{sub}',
        unsafe_allow_html=True,
    )


def section_header(text: str, caption: str = "") -> None:
    cap = f'<div class="sv-subtitle">{caption}</div>' if caption else ""
    st.markdown(
        f'<h2 class="sv-title" style="font-size:24px;margin-top:8px;">{text}</h2>{cap}',
        unsafe_allow_html=True,
    )


# ── Cards / pills / badges (HTML-string helpers) ───────────────────────────────

def card_html(inner: str, accent: bool = False, padding: str = "16px 20px") -> str:
    cls = "sv-card sv-card--accent" if accent else "sv-card"
    return f'<div class="{cls}" style="padding:{padding};">{inner}</div>'


def glass_card(inner: str, accent: bool = False, padding: str = "16px 20px") -> None:
    st.markdown(card_html(inner, accent, padding), unsafe_allow_html=True)


def pill(text: str, bg: str, fg: str, size: int = 11) -> str:
    return (
        f'<span class="sv-pill" style="background:{bg};color:{fg};'
        f'font-size:{size}px;">{text}</span>'
    )


def pred_pill(prediction: str, size: int = 12) -> str:
    bg, fg = PRED_STYLE.get(prediction, ("rgba(255,255,255,0.08)", "#fff"))
    return pill(prediction, bg, fg, size)


def signal_badge(signal: str) -> str:
    bg, fg, arrow = SIG_STYLE.get(signal, SIG_STYLE["HOLD"])
    return pill(f"{arrow} {signal}", bg, fg)


def stat_tile(label: str, value: str, color: str = TEXT) -> str:
    return (
        '<div style="text-align:center;">'
        f'<div style="font-size:9px;color:{TEXT_FAINT};text-transform:uppercase;'
        f'letter-spacing:0.6px;">{label}</div>'
        f'<div class="sv-mono" style="font-size:18px;font-weight:700;color:{color};">{value}</div>'
        '</div>'
    )


# ── Bars ───────────────────────────────────────────────────────────────────────

def confidence_bar(pct: float, color: str | None = None, label: str = "Confidence") -> str:
    """Glowing animated progress bar."""
    color = color or conf_color(pct)
    return (
        '<div style="flex:1;min-width:100px;">'
        '<div style="display:flex;justify-content:space-between;margin-bottom:3px;">'
        f'<span style="font-size:10px;color:{TEXT_FAINT};">{label}</span>'
        f'<span class="sv-mono" style="font-size:10px;color:{color};font-weight:700;">{pct}%</span>'
        '</div>'
        '<div class="sv-track">'
        f'<div class="sv-fill" style="width:{pct}%;background:{color};color:{color};"></div>'
        '</div></div>'
    )


def bar_row(label: str, home_name: str, home_val: float,
            away_name: str, away_val: float,
            home_color: str = ACCENT_MINT, away_color: str = "#60a5fa") -> str:
    """Two-team horizontal comparison bars (xG, cards, corners…)."""
    mx = max(home_val, away_val, 0.01)
    h_pct = min(home_val / mx * 100, 100)
    a_pct = min(away_val / mx * 100, 100)
    ns = (f"font-size:11px;color:{TEXT};width:110px;overflow:hidden;"
          "text-overflow:ellipsis;white-space:nowrap;text-align:right;")
    return (
        f'<div style="margin:8px 0 2px;">'
        f'<div style="font-size:10px;color:{TEXT_FAINT};text-transform:uppercase;'
        f'letter-spacing:0.5px;margin-bottom:5px;">{label}</div>'
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
        f'<span style="{ns}">{home_name}</span>'
        f'<div class="sv-track" style="height:7px;">'
        f'<div class="sv-fill" style="width:{h_pct:.0f}%;background:{home_color};color:{home_color};"></div></div>'
        f'<span class="sv-mono" style="font-size:11px;font-weight:700;color:{home_color};width:38px;">{home_val:.2f}</span>'
        f'</div>'
        f'<div style="display:flex;align-items:center;gap:8px;">'
        f'<span style="{ns}">{away_name}</span>'
        f'<div class="sv-track" style="height:7px;">'
        f'<div class="sv-fill" style="width:{a_pct:.0f}%;background:{away_color};color:{away_color};"></div></div>'
        f'<span class="sv-mono" style="font-size:11px;font-weight:700;color:{away_color};width:38px;">{away_val:.2f}</span>'
        f'</div>'
        f'</div>'
    )


# ── Count-up animated number (ReactBits CountUp) ───────────────────────────────

def count_up(value: float, prefix: str = "", suffix: str = "", color: str = TEXT,
             size: int = 26, decimals: int = 0, label: str = "", height: int = 0) -> None:
    """Animated number via a tiny JS requestAnimationFrame ease-out counter."""
    label_html = (
        f'<div style="font-size:9px;color:rgba(230,233,242,0.35);text-transform:uppercase;'
        f'letter-spacing:0.6px;font-family:Inter,sans-serif;margin-bottom:2px;">{label}</div>'
        if label else ""
    )
    h = height or (size + (26 if label else 14))
    components.html(
        f"""
        <div style="margin:0;padding:0;">
          {label_html}
          <div id="n" style="font:700 {size}px 'JetBrains Mono',Consolas,monospace;
               color:{color};line-height:1.1;"></div>
        </div>
        <script>
          const end = {value}, el = document.getElementById('n');
          const t0 = performance.now(), dur = 900;
          function fmt(v) {{
            return '{prefix}' + v.toLocaleString('en-US', {{
              minimumFractionDigits: {decimals}, maximumFractionDigits: {decimals}
            }}) + '{suffix}';
          }}
          function tick(t) {{
            const p = Math.min((t - t0) / dur, 1);
            const e = 1 - Math.pow(1 - p, 3);
            el.textContent = fmt(end * e);
            if (p < 1) requestAnimationFrame(tick);
          }}
          requestAnimationFrame(tick);
        </script>
        """,
        height=h,
    )
