"""Match Flow — match-length and shoot-delay (decision speed) distributions."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from lib import queries as q
from lib.theme import (
    ARCHERY, MODE_COLORS, MATCH_LEN_LABELS, SHOOT_DELAY_LABELS,
    footer, section, setup_page, themed,
)

setup_page("Match Flow", icon="⏱️")
st.markdown("## ⏱️ Match Flow")
st.caption("How long matches run, and how long players deliberate before loosing a shot.")

# ── Match length ─────────────────────────────────────────────────────────
section("Match length distribution", "Accumulated across all matches in the cohort.")
ml = q.bucket_totals("match_length_buckets", MATCH_LEN_LABELS)
total = max(int(ml["n"].sum()), 1)
ml["pct"] = (100 * ml["n"] / total).round(1)
fig = go.Figure(go.Bar(
    x=ml["bucket"], y=ml["n"], marker_color=ARCHERY["primary"],
    text=ml["pct"].map(lambda p: f"{p}%"), textposition="outside",
))
st.plotly_chart(themed(fig, "Match length"), use_container_width=True)

# ── Shoot delay (decision speed), bot vs pvp ─────────────────────────────
section("Shoot delay — decision speed", "Seconds on a turn before firing. Bot vs PvP overlaid.")
sd_bot = q.bucket_totals("shoot_delay_bot_buckets", SHOOT_DELAY_LABELS)
sd_pvp = q.bucket_totals("shoot_delay_pvp_buckets", SHOOT_DELAY_LABELS)

fig = go.Figure()
fig.add_bar(name="Bot", x=sd_bot["bucket"], y=sd_bot["n"], marker_color=MODE_COLORS["bot"])
fig.add_bar(name="PvP", x=sd_pvp["bucket"], y=sd_pvp["n"], marker_color=MODE_COLORS["pvp"])
fig.update_layout(barmode="group")
st.plotly_chart(themed(fig, "Shoot delay buckets"), use_container_width=True)

c1, c2 = st.columns(2)
with c1:
    bot_total = int(sd_bot["n"].sum())
    st.metric("Bot shots timed", f"{bot_total:,}")
with c2:
    pvp_total = int(sd_pvp["n"].sum())
    st.metric("PvP shots timed", f"{pvp_total:,}")

if bot_total == 0 and pvp_total == 0:
    st.caption("No shoot-delay telemetry recorded yet.")

footer()
