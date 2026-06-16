"""
Archery Duels — analytics home.

Streamlit multi-page app. This landing page shows high-signal KPI tiles, two
hero charts, then navigation into the deep-dive pages under `pages/`.

Heavy logic lives in `lib/queries.py` (every query cached 10 min) and
`lib/theme.py` (palette, formatters, KPI primitives).
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from lib import queries as q
from lib.filters import is_filter_active
from lib.theme import (
    ARCHERY, format_n, format_pct, format_time, footer, kpi_row, section,
    setup_page, themed,
)

setup_page("Archery Duels", icon="🏹")

# ── Hero header ─────────────────────────────────────────────────────────
col_title, col_status = st.columns([3, 1])
with col_title:
    st.markdown(
        f"<h1 style='margin-bottom:0;'>🏹 Archery Duels "
        f"<span style='color:{ARCHERY['primary']};'>Analytics</span></h1>"
        f"<div class='accent-bar'></div>"
        f"<div style='color:{ARCHERY['muted']};font-size:0.95rem;'>"
        f"Player data from Roblox Open Cloud. Use the sidebar to navigate.</div>",
        unsafe_allow_html=True,
    )
with col_status:
    statuses = q.fetch_status_counts()
    ok = statuses.get("ok", 0)
    pending = statuses.get("unfetched", 0) + statuses.get(None, 0)
    failed = statuses.get("failed", 0)
    st.markdown(
        f"<div style='text-align:right;font-size:0.8rem;color:{ARCHERY['muted']};'>"
        f"<span class='pill'>✓ {format_n(ok)} fetched</span>"
        f"{f'<span class=pill>⏳ {format_n(pending)} pending</span>' if pending else ''}"
        f"{f'<span class=\"pill danger\">✗ {format_n(failed)} failed</span>' if failed else ''}"
        f"</div>",
        unsafe_allow_html=True,
    )

k = q.kpi_summary()
if not k:
    st.warning("No player data yet. Once the dumper has fetched players, this fills in.")
    footer()
    st.stop()

cohort_n = int(k.get("cohort_n", 0) or 0)
denom = max(cohort_n, 1)

# ── KPI tiles ───────────────────────────────────────────────────────────
section("Population" + ("  ·  filtered cohort" if is_filter_active() else ""))
kpi_row([
    {"label": "Players (clean)", "value": cohort_n,
     "sub": f"{format_n(k.get('total_known'))} known · {format_n(k.get('total_fetched'))} fetched"},
    {"label": "Active 7d", "value": int(k.get("active_7d", 0) or 0),
     "sub": f"{format_pct(100*int(k.get('active_7d',0) or 0)/denom)} of cohort", "style": "accent"},
    {"label": "Active 24h", "value": int(k.get("active_1d", 0) or 0),
     "sub": f"{format_pct(100*int(k.get('active_1d',0) or 0)/denom)} of cohort"},
    {"label": "Paying players", "value": int(k.get("paying_players", 0) or 0),
     "sub": f"{format_pct(100*int(k.get('paying_players',0) or 0)/denom)} conversion", "style": "warn"},
])

section("Engagement")
total_af = int(k.get("total_arrows_fired", 0) or 0)
total_ah = int(k.get("total_arrows_hit", 0) or 0)
acc = (100 * total_ah / total_af) if total_af else 0
kpi_row([
    {"label": "Total matches", "value": int(k.get("total_matches", 0) or 0)},
    {"label": "Matches / player", "avg": format_n(k.get("avg_matches")),
     "median": format_n(k.get("median_matches")), "sub": "among players with ≥1 match"},
    {"label": "Playtime / player", "avg": format_time(k.get("avg_playtime_sec")),
     "median": format_time(k.get("median_playtime_sec"))},
    {"label": "Global accuracy", "value": format_pct(acc),
     "sub": f"{format_n(total_ah)} hits / {format_n(total_af)} arrows"},
])

# ── Hero charts ─────────────────────────────────────────────────────────
c1, c2 = st.columns(2)

with c1:
    section("Engagement funnel")
    fn = q.match_funnel()
    if not fn.empty:
        top = max(fn["n"].max(), 1)
        fn["pct"] = (100 * fn["n"] / top).round(1)
        fig = go.Figure(go.Funnel(
            y=fn["label"], x=fn["n"],
            textinfo="value+percent initial",
            marker=dict(color=ARCHERY["primary"]),
            connector=dict(line=dict(color=ARCHERY["border"])),
        ))
        st.plotly_chart(themed(fig), use_container_width=True)

with c2:
    section("New players / day")
    su = q.daily_signups(60)
    if not su.empty:
        fig = px.area(su, x="day", y="new_players")
        fig.update_traces(line_color=ARCHERY["primary"],
                          fillcolor="rgba(242,177,52,0.18)")
        st.plotly_chart(themed(fig), use_container_width=True)
    else:
        st.caption("No join-date data yet.")

# ── Aim teaser (the headline metric) ─────────────────────────────────────
section("Aim behaviour — the headline question", "Are players tap-firing or learning to hold-aim? Full breakdown on the Aim Analysis page.")
a = q.aim_summary()
shots = int(a.get("shots", 0) or 0)
if shots > 0:
    tap = int(a.get("tap_fires", 0) or 0)
    with_aim = int(a.get("with_aim", 0) or 0)
    kpi_row([
        {"label": "Shots with aim data", "value": shots},
        {"label": "Tap-fires", "value": tap, "sub": f"{format_pct(100*tap/max(shots,1))} of shots", "style": "danger"},
        {"label": "Aimed shots", "value": with_aim, "sub": f"{format_pct(100*with_aim/max(shots,1))} of shots", "style": "success"},
        {"label": "Players w/ aim data", "value": int(a.get("players_with_aim_data", 0) or 0)},
    ])
else:
    st.caption("No aim telemetry recorded yet (aim.count is 0 across the cohort).")

footer()
