"""
Theme + small UI helpers shared across pages.

Keeps colors, formatters, and a couple of layout primitives in one place
so the look stays consistent without each page re-defining everything.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import plotly.graph_objects as go
import streamlit as st


# ── Palette ─────────────────────────────────────────────────────────────
# Archery / tournament dark mode. Gold primary, fletching-red accent.
ARCHERY = {
    "bg":       "#16110c",
    "bg_card":  "#241a10",
    "bg_card2": "#332515",
    "border":   "#43321d",
    "primary":  "#f2b134",   # bow gold
    "accent":   "#e8643c",   # fletching orange-red
    "danger":   "#ff6b6b",
    "success":  "#7dd87d",
    "muted":    "#b0a080",
    "text":     "#f5ecd9",
    "subtle":   "#8a7a5e",
}

# Weapon slots — the three equip slots.
WEAPON_COLORS = {
    "Bow":   "#f2b134",   # gold
    "Axe":   "#e8643c",   # red
    "Spear": "#4a90d9",   # blue
}

# Match modes.
MODE_COLORS = {
    "bot": "#8a7a5e",   # muted (practice)
    "pvp": "#f2b134",   # gold (real)
}

# Bucket labels — must match PlayerMetricsConfig.lua edges.
AIM_HOLD_LABELS    = ["≤0.15s (tap)", "≤0.4s", "≤0.8s", "≤1.5s", "≤3.0s", "3.0s+"]
SHOOT_DELAY_LABELS = ["≤1s", "≤2s", "≤4s", "≤7s", "≤12s", "12s+"]
MATCH_LEN_LABELS   = ["≤30s", "≤60s", "≤2m", "≤4m", "≤8m", "8m+"]
LOAD_TIME_LABELS   = ["≤2s", "≤4s", "≤7s", "≤12s", "≤20s", "20s+"]


# Plotly default layout — applied via fig.update_layout(**PLOTLY_LAYOUT)
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=ARCHERY["text"], family="ui-sans-serif, system-ui"),
    xaxis=dict(gridcolor=ARCHERY["border"], zerolinecolor=ARCHERY["border"]),
    yaxis=dict(gridcolor=ARCHERY["border"], zerolinecolor=ARCHERY["border"]),
    margin=dict(l=10, r=10, t=40, b=10),
    legend=dict(bgcolor="rgba(0,0,0,0)"),
)


def themed(fig: go.Figure, title: str | None = None) -> go.Figure:
    """Apply the archery theme to a Plotly fig in place. Returns the fig."""
    layout = dict(PLOTLY_LAYOUT)
    if title is not None:
        layout["title"] = dict(text=title, font=dict(size=16, color=ARCHERY["text"]))
    fig.update_layout(**layout)
    return fig


# ── Page setup ──────────────────────────────────────────────────────────
def setup_page(title: str, icon: str = "🏹", wide: bool = True) -> None:
    """Call as the very first Streamlit command on every page."""
    st.set_page_config(
        page_title=f"{title} · Archery Duels",
        page_icon=icon,
        layout="wide" if wide else "centered",
        initial_sidebar_state="auto",
    )
    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)
    from lib.filters import render_global_filter
    render_global_filter()


_GLOBAL_CSS = f"""
<style>
    .block-container {{ padding-top: 1.2rem; max-width: 1400px; }}

    .kpi-tile {{
        background: linear-gradient(135deg, {ARCHERY['bg_card']} 0%, {ARCHERY['bg_card2']} 100%);
        border: 1px solid {ARCHERY['border']};
        border-radius: 14px;
        padding: 1.1rem 1.2rem 1rem;
        height: 100%;
        margin-bottom: 0.7rem;
        transition: transform 0.15s ease, border-color 0.15s ease;
        display: flex; flex-direction: column; justify-content: flex-start;
    }}
    .kpi-tile:hover {{ transform: translateY(-2px); border-color: {ARCHERY['primary']}; }}
    .kpi-tile h3 {{
        margin: 0 0 0.5rem; color: {ARCHERY['muted']};
        font-size: 0.72rem; text-transform: uppercase; letter-spacing: 1.1px;
        font-weight: 600;
    }}
    .kpi-tile .v {{
        margin: 0; color: {ARCHERY['text']};
        font-size: 1.85rem; font-weight: 700; line-height: 1.15;
    }}
    .kpi-tile .v.small {{ font-size: 1.3rem; }}
    .kpi-tile .sub {{
        color: {ARCHERY['subtle']}; font-size: 0.78rem; margin-top: 0.45rem;
        line-height: 1.3;
    }}
    .kpi-tile .v-split {{
        display: flex; gap: 0.9rem; margin: 0; align-items: baseline;
    }}
    .kpi-tile .v-split .col {{ display: flex; flex-direction: column; }}
    .kpi-tile .v-split .col .lab {{
        color: {ARCHERY['muted']}; font-size: 0.62rem;
        text-transform: uppercase; letter-spacing: 0.8px;
    }}
    .kpi-tile .v-split .col .val {{
        color: {ARCHERY['text']}; font-weight: 700; font-size: 1.35rem; line-height: 1.1;
    }}
    .kpi-tile.accent {{ border-color: {ARCHERY['primary']}; }}
    .kpi-tile.warn   {{ border-color: {ARCHERY['accent']}; }}
    .kpi-tile.danger {{ border-color: {ARCHERY['danger']}; }}

    .section-h {{
        border-left: 3px solid {ARCHERY['primary']};
        padding-left: 0.7rem;
        margin: 1.6rem 0 0.8rem;
        font-size: 1.15rem;
        font-weight: 600;
        color: {ARCHERY['text']};
    }}

    .pg-foot {{
        margin-top: 3rem; padding-top: 1rem;
        border-top: 1px solid {ARCHERY['border']};
        color: {ARCHERY['subtle']}; font-size: 0.78rem; text-align: center;
    }}

    .pill {{
        display: inline-block; padding: 0.18rem 0.55rem;
        border-radius: 99px; font-size: 0.72rem; font-weight: 600;
        background: {ARCHERY['bg_card']}; color: {ARCHERY['primary']};
        border: 1px solid {ARCHERY['border']};
        margin-right: 0.3rem;
    }}
    .pill.warn {{ color: {ARCHERY['accent']}; }}
    .pill.danger {{ color: {ARCHERY['danger']}; }}

    @media (max-width: 768px) {{
        .kpi-tile {{ padding: 0.8rem 0.9rem; }}
        .kpi-tile .v {{ font-size: 1.5rem; }}
    }}

    .accent-bar {{
        height: 3px; width: 60px;
        background: linear-gradient(90deg, {ARCHERY['primary']}, transparent);
        margin: 0.3rem 0 1rem;
    }}
</style>
"""


# ── KPI tiles ───────────────────────────────────────────────────────────
def kpi(label: str, value: str | int | float, sub: str = "", style: str = "") -> None:
    """Render a single KPI tile in the current Streamlit container.

    Single-line HTML — multi-line indented HTML inside st.markdown gets
    treated as a CommonMark code block and renders raw `</div>` tags.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = format_n(value)
    else:
        v = str(value)
    cls = "kpi-tile" + (f" {style}" if style else "")
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    st.markdown(
        f'<div class="{cls}"><h3>{label}</h3><p class="v">{v}</p>{sub_html}</div>',
        unsafe_allow_html=True,
    )


def kpi_split(label: str, avg: str, median: str, sub: str = "", style: str = "") -> None:
    """KPI tile showing avg and median side-by-side."""
    cls = "kpi-tile" + (f" {style}" if style else "")
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    st.markdown(
        f'<div class="{cls}"><h3>{label}</h3>'
        f'<div class="v-split">'
        f'<div class="col"><span class="lab">avg</span><span class="val">{avg}</span></div>'
        f'<div class="col"><span class="lab">median</span><span class="val">{median}</span></div>'
        f'</div>{sub_html}</div>',
        unsafe_allow_html=True,
    )


def kpi_row(items: list[dict[str, Any]], cols: int = 4) -> None:
    """Render a row of KPI tiles. items: [{label, value, sub?, style?}, ...]
    OR for split tiles: [{label, avg, median, sub?, style?}, ...]
    """
    columns = st.columns(cols)
    for i, item in enumerate(items):
        with columns[i % cols]:
            if "avg" in item and "median" in item:
                kpi_split(
                    item["label"], item["avg"], item["median"],
                    item.get("sub", ""), item.get("style", ""),
                )
            else:
                kpi(
                    item["label"], item["value"],
                    item.get("sub", ""), item.get("style", ""),
                )


def section(title: str, sub: str | None = None) -> None:
    st.markdown(f'<div class="section-h">{title}</div>', unsafe_allow_html=True)
    if sub:
        st.caption(sub)


# ── Formatters ──────────────────────────────────────────────────────────
def format_n(n: float | int | None) -> str:
    if n is None:
        return "—"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "—"
    if abs(n) >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    if abs(n) >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if abs(n) >= 10_000:
        return f"{n/1_000:.1f}k"
    if n == int(n):
        return f"{int(n):,}"
    return f"{n:,.2f}"


def format_time(seconds: float | int | None) -> str:
    if seconds is None or seconds <= 0:
        return "0s"
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{s/60:.1f}m"
    if s < 86400:
        h, m = int(s // 3600), int((s % 3600) // 60)
        return f"{h}h {m}m"
    d = int(s // 86400)
    h = int((s % 86400) // 3600)
    return f"{d}d {h}h"


def format_pct(p: float | None, decimals: int = 1) -> str:
    if p is None:
        return "—"
    return f"{p:.{decimals}f}%"


def format_ts(ts: int | float | None) -> str:
    if ts is None or ts <= 0:
        return "—"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError, OverflowError):
        return "—"


# ── Footer ──────────────────────────────────────────────────────────────
def footer() -> None:
    st.markdown(
        '<div class="pg-foot">'
        'Archery Duels · live data from Postgres on iw-infra · cached 10 min'
        '</div>',
        unsafe_allow_html=True,
    )
