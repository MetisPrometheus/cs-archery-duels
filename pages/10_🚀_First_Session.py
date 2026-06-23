"""First Session (FTUE) — what every new player actually experiences.

The make-or-break first session: how long they play, how many games, which
maps, do they win, and do they ever reach the progression loop (inventory +
chests). Powered by the per-session/per-match ETL (player_sessions /
player_matches) now that the game persists session rows via the heartbeat.
"""
from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from lib import queries as q
from lib.theme import (
    ARCHERY, MODE_COLORS, footer, format_pct, format_time, kpi_row,
    section, setup_page, themed,
)

setup_page("First Session", icon="🚀")
st.markdown("## 🚀 First Session — the FTUE make-or-break")
st.caption(
    "Everything a brand-new player lives through in their very first session. "
    "Source: `player_sessions` / `player_matches` (idx 1 = first ever). Only "
    "sessions persisted after the heartbeat fix are captured, so this is the "
    "*recent* new-player experience."
)

s = q.ftue_summary()
if not s or not s.get("players"):
    st.info("No first-session rows captured yet — waiting on the session ETL / heartbeat data.")
    footer(); st.stop()

# ── Headline KPIs ─────────────────────────────────────────────────────────
section("Are they playing for long? How much do they do?")
kpi_row([
    {"label": "First sessions captured", "value": int(s["players"]),
     "sub": "players with a recorded first session"},
    {"label": "First-session length", "avg": format_time(s["avg_dur"]),
     "median": format_time(s["median_dur"]), "style": "accent"},
    {"label": "Games in first session", "avg": f"{s['avg_games']:.1f}",
     "median": f"{s['median_games']:.0f}"},
    {"label": "Players in server", "value": f"{s.get('avg_players_on_leave') or 0:.0f}",
     "sub": "avg others present (social proof — full servers feel alive)"},
])
kpi_row([
    {"label": "Won ≥1 in first session", "value": format_pct(s["pct_won"]),
     "sub": "tasted victory early", "style": "accent"},
    {"label": "Tried PvP in first session", "value": format_pct(s["pct_pvp"]),
     "sub": "rest stayed on bots"},
    {"label": "Rage-quit signal", "value": format_pct(s["pct_ended_loss"]),
     "sub": "ended session right after a loss", "style": "warn"},
    {"label": "Left mid-match", "value": format_pct(s["pct_left_mid"]),
     "sub": "abandoned a live match"},
])

# ── FTUE reach funnel — the experiences they unlock ───────────────────────
section("How far do they get? — FTUE experience reach",
        "Share of the cohort that reaches each milestone. Where the line falls "
        "off a cliff is where new players are leaking out before they hook.")
reach = q.ftue_reach_funnel()
if not reach.empty:
    fig = go.Figure(go.Bar(
        x=reach["pct"], y=reach["stage"], orientation="h",
        marker=dict(color=reach["pct"], colorscale=[[0, ARCHERY["accent"]], [1, ARCHERY["primary"]]]),
        text=[f"{p:.0f}%  ({n:,})" for p, n in zip(reach["pct"], reach["n"])],
        textposition="auto",
        hovertemplate="%{y}: %{x:.1f}% of cohort<extra></extra>",
    ))
    fig.update_layout(yaxis=dict(autorange="reversed"), xaxis_title="% of cohort",
                      yaxis_title="", height=380)
    st.plotly_chart(themed(fig), use_container_width=True)
    # auto-callout: biggest single drop
    drops = [(reach["stage"].iloc[i], reach["pct"].iloc[i-1] - reach["pct"].iloc[i])
             for i in range(1, len(reach))]
    if drops:
        worst = max(drops, key=lambda d: d[1])
        st.markdown(
            f"<div class='pill warn'>biggest leak</div> the steepest drop is into "
            f"<b>{worst[0]}</b> (−{worst[1]:.0f} pts). That's the highest-leverage "
            f"step to smooth in onboarding.", unsafe_allow_html=True)

# ── Distributions: how long / how many games ──────────────────────────────
c1, c2 = st.columns(2)
with c1:
    section("First-session length")
    dur = q.first_session_duration_dist()
    if not dur.empty:
        fig = px.bar(dur, x="bucket", y="n")
        fig.update_traces(marker_color=ARCHERY["primary"])
        fig.update_layout(xaxis_title="", yaxis_title="players",
                          xaxis=dict(categoryorder="array", categoryarray=list(dur["bucket"])))
        st.plotly_chart(themed(fig), use_container_width=True)
with c2:
    section("Games played in first session")
    g = q.first_session_games_dist()
    if not g.empty:
        g = g.copy()
        g["label"] = g["games"].apply(lambda x: "6+" if x >= 6 else str(int(x)))
        fig = px.bar(g, x="label", y="n")
        fig.update_traces(marker_color=ARCHERY["accent"])
        fig.update_layout(xaxis_title="games", yaxis_title="players")
        st.plotly_chart(themed(fig), use_container_width=True)

# ── Which games / which maps / do they win ────────────────────────────────
section("Which games & maps do they get? Do they win?",
        "Maps and modes of the first 3 matches every player plays, with win-rate.")
fm = q.ftue_first_matches(3)
if not fm.empty:
    c1, c2 = st.columns([3, 2])
    with c1:
        fig = px.bar(fm, x="n", y="map", color="mode", orientation="h",
                     color_discrete_map=MODE_COLORS,
                     hover_data={"winrate": ":.0f"})
        fig.update_layout(yaxis=dict(autorange="reversed"), xaxis_title="first-3 matches",
                          yaxis_title="", legend_title="mode")
        st.plotly_chart(themed(fig), use_container_width=True)
    with c2:
        st.dataframe(
            fm.assign(winrate=fm["winrate"].round(0)).rename(columns={
                "map": "Map", "mode": "Mode", "n": "Matches", "winrate": "Win %"}),
            use_container_width=True, hide_index=True,
        )
    maps_seen = fm.groupby("map")["n"].sum().sort_values(ascending=False)
    if len(maps_seen) and maps_seen.iloc[0] / maps_seen.sum() > 0.7:
        st.markdown(
            f"<div class='pill'>map variety</div> <b>{maps_seen.index[0]}</b> is "
            f"{100*maps_seen.iloc[0]/maps_seen.sum():.0f}% of all early matches — new "
            f"players barely see the other maps. Rotating early maps could add novelty.",
            unsafe_allow_html=True)

# ── First-match outcome → retention (the win hook) ────────────────────────
section("Does winning the first match hook them?",
        "Retention & engagement split by the result of a player's very first match. "
        "If winners come back more, protecting the first-match win is a retention lever.")
fmr = q.first_match_outcome_retention()
if not fmr.empty:
    c1, c2 = st.columns([2, 3])
    with c1:
        fig = go.Figure(go.Bar(
            x=fmr["outcome"], y=fmr["pct_returned"],
            marker_color=[ARCHERY["success"] if o.startswith("Won") else
                          ARCHERY["danger"] if o.startswith("Lost") else ARCHERY["muted"]
                          for o in fmr["outcome"]],
            text=[f"{p:.1f}%" for p in fmr["pct_returned"]], textposition="auto",
        ))
        fig.update_layout(yaxis_title="% returned (≥2 days)", xaxis_title="")
        st.plotly_chart(themed(fig), use_container_width=True)
    with c2:
        st.dataframe(
            fmr.assign(
                pct_returned=fmr["pct_returned"].round(1),
                avg_matches=fmr["avg_matches"].round(1),
                avg_playtime=(fmr["avg_playtime"] / 60).round(1),
            ).rename(columns={
                "outcome": "First match", "players": "Players",
                "pct_returned": "Returned %", "avg_matches": "Avg matches",
                "avg_playtime": "Avg playtime (min)"})[
                ["First match", "Players", "Returned %", "Avg matches", "Avg playtime (min)"]],
            use_container_width=True, hide_index=True,
        )

footer()
