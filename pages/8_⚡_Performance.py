"""Performance — client load time (boot → ready)."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from lib import queries as q
from lib.theme import (
    ARCHERY, LOAD_TIME_LABELS, format_n, footer, kpi_row, section, setup_page, themed,
)

setup_page("Performance", icon="⚡")
st.markdown("## ⚡ Performance")
st.caption("Client load time, boot to ready. Slow loads are a silent churn driver.")

s = q.load_summary()
samples = int(s.get("total_samples", 0) or 0)
if samples == 0:
    st.info("No load-time telemetry yet — `METRICS.load.count` is 0 across the cohort.")
    footer(); st.stop()

section("Load time (last sample per player)")
kpi_row([
    {"label": "Players w/ data", "value": int(s.get("players_with_load", 0) or 0)},
    {"label": "Median load", "value": f"{float(s.get('median_last_ms',0) or 0)/1000:.1f}s"},
    {"label": "Avg load", "value": f"{float(s.get('avg_last_ms',0) or 0)/1000:.1f}s"},
    {"label": "p90 load", "value": f"{float(s.get('p90_last_ms',0) or 0)/1000:.1f}s", "style": "warn"},
])

section("Load-time distribution", "Accumulated load samples across the cohort.")
hist = q.bucket_totals("load_buckets", LOAD_TIME_LABELS)
total = max(int(hist["n"].sum()), 1)
hist["pct"] = (100 * hist["n"] / total).round(1)
# green→red gradient: fast loads good, slow loads bad
colors = [ARCHERY["success"], ARCHERY["success"], ARCHERY["primary"],
          ARCHERY["accent"], ARCHERY["danger"], ARCHERY["danger"]]
fig = go.Figure(go.Bar(
    x=hist["bucket"], y=hist["n"], marker_color=colors,
    text=hist["pct"].map(lambda p: f"{p}%"), textposition="outside",
))
st.plotly_chart(themed(fig, "Load time buckets"), use_container_width=True)

footer()
