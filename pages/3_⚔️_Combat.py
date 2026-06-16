"""Combat — wins/losses, accuracy, headshots, streaks, bot vs PvP."""
from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from lib import queries as q
from lib.theme import (
    ARCHERY, MODE_COLORS, format_n, format_pct, footer, kpi_row,
    section, setup_page, themed,
)

setup_page("Combat", icon="⚔️")
st.markdown("## ⚔️ Combat")
st.caption("Win/loss, accuracy, headshots and streaks — across bot and PvP modes.")

cs = q.combat_stats()
if cs.empty:
    st.info("No cohort data yet.")
    footer(); st.stop()

total_matches = int(cs["matches"].sum())
total_wins = int(cs["wins"].sum())
total_af = int(cs["arrows_fired"].sum())
total_ah = int(cs["arrows_hit"].sum())
total_hs = int(cs["headshots"].sum())
section("Totals")
kpi_row([
    {"label": "Matches", "value": total_matches,
     "sub": f"{format_n(total_wins)} wins · {format_pct(100*total_wins/max(total_matches,1))} winrate"},
    {"label": "Global accuracy", "value": format_pct(100*total_ah/max(total_af,1)),
     "sub": f"{format_n(total_ah)} / {format_n(total_af)} arrows"},
    {"label": "Headshots", "value": total_hs,
     "sub": f"{format_pct(100*total_hs/max(total_ah,1))} of hits"},
    {"label": "Longest streak", "value": int(cs["longest_streak"].max()),
     "sub": f"avg best {cs['longest_streak'].mean():.1f}"},
])

# ── Bot vs PvP ───────────────────────────────────────────────────────────
section("Bot vs PvP")
ms = q.mode_split()
if not ms.empty:
    c1, c2 = st.columns([1, 1])
    with c1:
        fig = go.Figure()
        fig.add_bar(name="Wins", x=ms["mode"], y=ms["wins"], marker_color=ARCHERY["success"])
        fig.add_bar(name="Losses", x=ms["mode"], y=ms["losses"], marker_color=ARCHERY["danger"])
        fig.update_layout(barmode="group")
        st.plotly_chart(themed(fig, "Outcomes by mode"), use_container_width=True)
    with c2:
        fig2 = go.Figure(go.Pie(
            labels=ms["mode"], values=ms["matches"], hole=0.5,
            marker_colors=[MODE_COLORS["bot"], MODE_COLORS["pvp"]],
        ))
        st.plotly_chart(themed(fig2, "Match volume by mode"), use_container_width=True)

# ── Accuracy distribution ────────────────────────────────────────────────
section("Accuracy distribution", "Players with ≥1 arrow fired.")
acc = cs[cs["accuracy"].notna()]
if not acc.empty:
    fig = px.histogram(acc, x="accuracy", nbins=30)
    fig.update_traces(marker_color=ARCHERY["primary"])
    fig.update_layout(xaxis_title="Accuracy %", yaxis_title="Players")
    st.plotly_chart(themed(fig), use_container_width=True)

# ── Winrate distribution ─────────────────────────────────────────────────
section("Winrate distribution", "Players with ≥1 match.")
wr = cs[cs["winrate"].notna()]
if not wr.empty:
    fig = px.histogram(wr, x="winrate", nbins=20)
    fig.update_traces(marker_color=ARCHERY["accent"])
    fig.update_layout(xaxis_title="Winrate %", yaxis_title="Players")
    st.plotly_chart(themed(fig), use_container_width=True)

# ── Leaderboard ──────────────────────────────────────────────────────────
section("Top by wins")
top = q.top_players("wins", 20)
if not top.empty:
    st.dataframe(
        top[["name", "value", "matches"]].rename(
            columns={"name": "Player", "value": "Wins", "matches": "Matches"}),
        use_container_width=True, hide_index=True,
    )

footer()
