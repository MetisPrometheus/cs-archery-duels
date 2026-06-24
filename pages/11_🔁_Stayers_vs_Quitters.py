"""Stayers vs Quitters — what do the players who stick around do differently?

The whole point: find the behaviours that separate players who return from
players who play once and vanish — so we know what to nudge new players toward.
Plus the matchmaking-fairness lens (are new players getting power-stomped in
PvP?), which is the leading suspect for the one-and-done PvP cliff.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import queries as q
from lib.theme import (
    ARCHERY, MODE_COLORS, footer, format_pct, format_time, section,
    setup_page, themed,
)

setup_page("Stayers vs Quitters", icon="🔁")
st.markdown("## 🔁 Stayers vs Quitters")
st.caption(
    "Three cohorts — **Stayers** (came back on a 2nd day), **Same-day returners** "
    "(multiple sessions, one day) and **One-and-done** (a single session, gone). "
    "What stayers do that quitters don't is the nudge map for onboarding."
)

svq = q.stayers_vs_quitters()
if svq.empty:
    st.info("No cohort data yet.")
    footer(); st.stop()

# canonical order weakest → strongest
ORDER = ["One-and-done", "Same-day returners", "Stayers (≥2 days)"]
present = [g for g in ORDER if g in set(svq["grp"])]
svq = svq.set_index("grp").reindex(present).reset_index()
# never let a NULL avg (cohort with no captured first sessions) crash f-string formatting
for _c in ["avg_playtime", "avg_matches", "pct_pvp", "pct_won", "pct_inv",
           "pct_chest", "avg_first_dur", "avg_first_games"]:
    if _c in svq.columns:
        svq[_c] = pd.to_numeric(svq[_c], errors="coerce").fillna(0)
COLORS = {"One-and-done": ARCHERY["danger"],
          "Same-day returners": ARCHERY["muted"],
          "Stayers (≥2 days)": ARCHERY["success"]}

# ── Cohort sizes ──────────────────────────────────────────────────────────
section("The three cohorts")
cols = st.columns(len(svq))
total = svq["players"].sum()
for i, row in svq.iterrows():
    with cols[i]:
        st.markdown(
            f"<div class='kpi-tile' style='border-color:{COLORS.get(row['grp'],ARCHERY['border'])}'>"
            f"<h3>{row['grp']}</h3>"
            f"<p class='v'>{int(row['players']):,}</p>"
            f"<div class='sub'>{100*row['players']/max(total,1):.1f}% of cohort · "
            f"{format_time(row['avg_playtime'])} avg play · {row['avg_matches']:.1f} matches</div></div>",
            unsafe_allow_html=True)

# ── The nudge map — behaviour prevalence by cohort ────────────────────────
section("What do stayers do that quitters don't?",
        "Each behaviour as a % of the cohort. The wider the gap from One-and-done "
        "→ Stayers, the stronger that behaviour is as a retention signal to nudge.")
metrics = [
    ("Opened inventory", "pct_inv"),
    ("Got a chest reward", "pct_chest"),
    ("Won a match", "pct_won"),
    ("Tried PvP", "pct_pvp"),
]
fig = go.Figure()
for _, row in svq.iterrows():
    fig.add_bar(
        name=row["grp"], x=[m[0] for m in metrics],
        y=[row[m[1]] for m in metrics],
        marker_color=COLORS.get(row["grp"], ARCHERY["primary"]),
        text=[f"{row[m[1]]:.0f}%" for m in metrics], textposition="auto",
    )
fig.update_layout(barmode="group", yaxis_title="% of cohort", xaxis_title="",
                  legend_title="cohort", height=420)
st.plotly_chart(themed(fig), use_container_width=True)

# auto-callout: largest stayer-vs-quitter gap
try:
    oad = svq[svq["grp"] == "One-and-done"].iloc[0]
    stay = svq[svq["grp"] == "Stayers (≥2 days)"].iloc[0]
    gaps = sorted(((label, stay[col] - oad[col]) for label, col in metrics),
                  key=lambda x: x[1], reverse=True)
    top = gaps[0]
    st.markdown(
        f"<div class='pill'>biggest divider</div> <b>{top[0]}</b> separates the cohorts "
        f"most — {stay[[c for l,c in metrics if l==top[0]][0]]:.0f}% of stayers vs "
        f"{oad[[c for l,c in metrics if l==top[0]][0]]:.0f}% of one-and-dones "
        f"(+{top[1]:.0f} pts). Pulling new players into this in session 1 is the "
        f"highest-leverage nudge.", unsafe_allow_html=True)
except (IndexError, KeyError):
    pass

# ── First-session intensity by cohort ─────────────────────────────────────
section("Was their first session already different?",
        "First-session length & games — do future stayers start hotter, or do they "
        "warm up over time? (If the first session already differs, the hook is early.)")
c1, c2 = st.columns(2)
with c1:
    fig = go.Figure(go.Bar(
        x=svq["grp"], y=svq["avg_first_dur"],
        marker_color=[COLORS.get(g, ARCHERY["primary"]) for g in svq["grp"]],
        text=[format_time(v) for v in svq["avg_first_dur"]], textposition="auto"))
    fig.update_layout(title="Avg first-session length", yaxis_title="seconds", xaxis_title="")
    st.plotly_chart(themed(fig), use_container_width=True)
with c2:
    fig = go.Figure(go.Bar(
        x=svq["grp"], y=svq["avg_first_games"],
        marker_color=[COLORS.get(g, ARCHERY["primary"]) for g in svq["grp"]],
        text=[f"{v:.1f}" for v in svq["avg_first_games"]], textposition="auto"))
    fig.update_layout(title="Avg games in first session", yaxis_title="games", xaxis_title="")
    st.plotly_chart(themed(fig), use_container_width=True)

# ── Matchmaking fairness — the PvP stomp ──────────────────────────────────
section("⚔️ Matchmaking fairness — are new players getting stomped?",
        "Average player power vs opponent power across the first 5 matches. A big "
        "positive gap (opponent stronger) + low win-rate = new players walking into "
        "buzzsaws. This is the leading suspect for the one-and-done PvP cliff.")
mm = q.early_match_matchmaking(5)
if not mm.empty:
    for mode in ["bot", "pvp"]:
        sub = mm[mm["mode"] == mode]
        if sub.empty:
            continue
        st.markdown(f"**{mode.upper()} — first 5 matches**")
        fig = go.Figure()
        fig.add_bar(x=sub["match_no"], y=sub["my_power"], name="My power",
                    marker_color=ARCHERY["primary"])
        fig.add_bar(x=sub["match_no"], y=sub["opp_power"], name="Opponent power",
                    marker_color=ARCHERY["accent"])
        fig.add_scatter(x=sub["match_no"], y=sub["winrate"], name="Win %",
                        yaxis="y2", mode="lines+markers",
                        line=dict(color=ARCHERY["success"], width=3))
        fig.update_layout(
            barmode="group", xaxis_title="match number", yaxis_title="power",
            yaxis2=dict(title="win %", overlaying="y", side="right", range=[0, 100],
                        gridcolor="rgba(0,0,0,0)"),
            legend=dict(orientation="h", y=1.12), height=330,
        )
        st.plotly_chart(themed(fig), use_container_width=True)
    pvp = mm[mm["mode"] == "pvp"]
    if not pvp.empty:
        avg_gap = pvp["power_gap"].mean()
        avg_wr = pvp["winrate"].mean()
        if avg_gap > 50:
            st.markdown(
                f"<div class='pill danger'>stomp detected</div> in early PvP, opponents "
                f"average <b>+{avg_gap:.0f} power</b> over the new player and win-rate sits "
                f"at <b>{avg_wr:.0f}%</b>. Bots are balanced (~85% win, a fair hook) but the "
                f"first taste of PvP is a beating. Power-bracketed matchmaking — or seeding "
                f"low queues with right-sized disguised opponents — directly targets this.",
                unsafe_allow_html=True)

footer()
