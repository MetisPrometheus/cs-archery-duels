"""Funnel — onboarding progression and play-button click conversion."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from lib import queries as q
from lib.theme import ARCHERY, MODE_COLORS, format_n, format_pct, footer, section, setup_page, themed

setup_page("Funnel", icon="📊")
st.markdown("## 📊 Funnel")
st.caption("Where players progress — and where they drop off.")

# ── Progression funnel ───────────────────────────────────────────────────
section("Onboarding progression")
fn = q.match_funnel()
if fn.empty or fn["n"].iloc[0] == 0:
    st.info("No cohort data yet.")
    footer(); st.stop()

top = max(int(fn["n"].iloc[0]), 1)
fig = go.Figure(go.Funnel(
    y=fn["label"], x=fn["n"],
    textinfo="value+percent initial",
    marker=dict(color=ARCHERY["primary"]),
    connector=dict(line=dict(color=ARCHERY["border"])),
))
st.plotly_chart(themed(fig), use_container_width=True)

# step-to-step conversion table
fn["pct_of_start"] = (100 * fn["n"] / top).round(1)
fn["step_conv"] = (100 * fn["n"] / fn["n"].shift(1)).round(1)
st.dataframe(
    fn[["label", "n", "pct_of_start", "step_conv"]].rename(columns={
        "label": "Milestone", "n": "Players",
        "pct_of_start": "% of fetched", "step_conv": "% of prev step",
    }),
    use_container_width=True, hide_index=True,
)

# ── Click conversion ─────────────────────────────────────────────────────
section("Play-button click → slot claimed", "Did the click 'take' (slot claimed) or bounce (arena full / already in a slot)?")
cf = q.click_funnel()
if not cf.empty:
    cf["bounce"] = cf["clicks"] - cf["claimed"]
    cf["conv"] = (100 * cf["claimed"] / cf["clicks"].clip(lower=1)).round(1)
    c1, c2 = st.columns([2, 1])
    with c1:
        fig = go.Figure()
        fig.add_bar(name="Claimed", x=cf["path"], y=cf["claimed"], marker_color=ARCHERY["success"])
        fig.add_bar(name="Bounced", x=cf["path"], y=cf["bounce"], marker_color=ARCHERY["danger"])
        fig.update_layout(barmode="stack")
        st.plotly_chart(themed(fig, "Clicks by outcome"), use_container_width=True)
    with c2:
        for _, r in cf.iterrows():
            st.metric(f"{r['path']} conversion", format_pct(r["conv"]),
                      help=f"{format_n(r['claimed'])} claimed of {format_n(r['clicks'])} clicks")

footer()
