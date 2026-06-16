"""Aim Analysis — THE headline metric: are players tap-firing or hold-aiming?"""
from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from lib import queries as q
from lib.theme import (
    ARCHERY, AIM_HOLD_LABELS, format_n, format_pct, footer, kpi_row,
    section, setup_page, themed,
)

setup_page("Aim Analysis", icon="🎯")
st.markdown("## 🎯 Aim Analysis")
st.caption(
    "The core design question: do players release almost immediately (tap-fire, "
    "never learning hold-drag-to-aim) or actually hold to aim? A 'tap' is a "
    "release under 0.15s."
)

a = q.aim_summary()
shots = int(a.get("shots", 0) or 0)
if shots == 0:
    st.info("No aim telemetry yet — `METRICS.aim.count` is 0 across the cohort. "
            "Once players generate aim gestures, this page fills in.")
    footer(); st.stop()

tap = int(a.get("tap_fires", 0) or 0)
with_aim = int(a.get("with_aim", 0) or 0)
section("Headline")
kpi_row([
    {"label": "Shots w/ aim data", "value": shots},
    {"label": "Tap-fire rate", "value": format_pct(100 * tap / max(shots, 1)),
     "sub": f"{format_n(tap)} pure tap-fires", "style": "danger"},
    {"label": "Aimed-shot rate", "value": format_pct(100 * with_aim / max(shots, 1)),
     "sub": f"{format_n(with_aim)} with trajectory shown", "style": "success"},
    {"label": "Players w/ data", "value": int(a.get("players_with_aim_data", 0) or 0)},
])

# ── Hold-duration histogram ──────────────────────────────────────────────
section("Aim hold-duration distribution", "Seconds from begin-aim to release, bucketed. Left = tap-firing, right = deliberate aiming.")
hist = q.bucket_totals("aim_buckets", AIM_HOLD_LABELS)
total = max(int(hist["n"].sum()), 1)
hist["pct"] = (100 * hist["n"] / total).round(1)
colors = [ARCHERY["danger"]] + [ARCHERY["primary"]] * (len(AIM_HOLD_LABELS) - 1)
fig = go.Figure(go.Bar(
    x=hist["bucket"], y=hist["n"], marker_color=colors,
    text=hist["pct"].map(lambda p: f"{p}%"), textposition="outside",
))
st.plotly_chart(themed(fig, "Hold-duration buckets (red = tap)"), use_container_width=True)

# ── Tap vs aimed donut ───────────────────────────────────────────────────
c1, c2 = st.columns(2)
with c1:
    section("Tap-fire vs aimed")
    other = max(shots - tap - with_aim, 0)
    pie = go.Figure(go.Pie(
        labels=["Tap-fire", "Aimed", "Other"],
        values=[tap, with_aim, other],
        marker_colors=[ARCHERY["danger"], ARCHERY["success"], ARCHERY["subtle"]],
        hole=0.55,
    ))
    st.plotly_chart(themed(pie), use_container_width=True)
with c2:
    section("Read")
    tap_pct = 100 * tap / max(shots, 1)
    if tap_pct > 50:
        st.error(f"**{tap_pct:.0f}% of shots are tap-fires.** A majority of players "
                 "aren't engaging with the hold-drag aiming mechanic — a strong signal "
                 "the aiming affordance isn't landing in onboarding.")
    elif tap_pct > 25:
        st.warning(f"**{tap_pct:.0f}% tap-fires.** A meaningful slice still isn't "
                   "learning to hold-aim.")
    else:
        st.success(f"**Only {tap_pct:.0f}% tap-fires** — most players are holding to aim.")

footer()
