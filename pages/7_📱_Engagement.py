"""Engagement — sessions, retention, daily claims, UI screen opens."""
from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from lib import queries as q
from lib.theme import (
    ARCHERY, format_n, format_pct, format_time, footer, kpi_row,
    section, setup_page, themed,
)

setup_page("Engagement", icon="📱")
st.markdown("## 📱 Engagement")
st.caption("Sessions, return behaviour, daily-reward claims and UI navigation.")

eng = q.engagement_stats()
if eng.empty:
    st.info("No cohort data yet.")
    footer(); st.stop()

n = len(eng)
returned = int((eng["days_played"] >= 2).sum())

# ── Playtime drop-off (survival) curve ───────────────────────────────────
section("Playtime drop-off curve",
        "% of players still in the game as minutes-played climbs. Source: "
        "current-day playtime (STATS.dailyPlaytime.seconds) — resets daily, so "
        "read it as within-a-day engagement. (Lifetime totalPlaytime isn't wired "
        "game-side yet — it's 0 for ~all players.)")
sv = q.playtime_survival()
if not sv.empty and sv["remaining"].iloc[0] > 0:
    fig = go.Figure(go.Scatter(
        x=sv["minutes"], y=sv["pct"], mode="lines+markers",
        fill="tozeroy", line=dict(color=ARCHERY["primary"], width=2),
        fillcolor="rgba(242,177,52,0.15)", marker=dict(size=6),
        hovertemplate="%{x:.0f} min → %{y:.1f}% remaining<extra></extra>",
    ))
    fig.update_layout(
        xaxis_title="Minutes played (that day)",
        yaxis_title="% of players still in",
        yaxis=dict(range=[0, 100]),
    )
    st.plotly_chart(themed(fig), use_container_width=True)

    # Milestone callouts at key minute marks.
    def _pct_at(sec: int) -> float:
        row = sv[sv["seconds"] == sec]
        return float(row["pct"].iloc[0]) if not row.empty else 0.0
    # median = first threshold where remaining drops below 50%
    below = sv[sv["pct"] < 50]
    median_min = float(below["minutes"].iloc[0]) if not below.empty else float(sv["minutes"].iloc[-1])
    kpi_row([
        {"label": "Median time", "value": f"~{median_min:.0f} min",
         "sub": "half the players pass this", "style": "accent"},
        {"label": "Reach 5 min", "value": format_pct(_pct_at(300))},
        {"label": "Reach 10 min", "value": format_pct(_pct_at(600))},
        {"label": "Reach 30 min", "value": format_pct(_pct_at(1800)), "style": "warn"},
    ])

section("Sessions & retention")
kpi_row([
    {"label": "Sessions / player", "avg": f"{eng['sessions'].mean():.1f}",
     "median": f"{eng['sessions'].median():.0f}"},
    {"label": "Days played / player", "avg": f"{eng['days_played'].mean():.1f}",
     "median": f"{eng['days_played'].median():.0f}"},
    {"label": "Returned (≥2 days)", "value": returned,
     "sub": f"{format_pct(100*returned/max(n,1))} of cohort", "style": "accent"},
    {"label": "Longest session", "avg": format_time(eng["longest_session"].mean()),
     "median": format_time(eng["longest_session"].median())},
])

# ── Daily claims ─────────────────────────────────────────────────────────
section("Daily-reward claims")
kpi_row([
    {"label": "Total login claims", "value": int(eng["login_claims"].sum())},
    {"label": "Total quest claims", "value": int(eng["quest_claims"].sum())},
    {"label": "Claimed login ≥1", "value": int((eng["login_claims"] > 0).sum())},
    {"label": "Claimed quest ≥1", "value": int((eng["quest_claims"] > 0).sum())},
], cols=4)

# ── Retention by signup day ──────────────────────────────────────────────
section("Retention by signup day", "Of players who joined each day, share that returned (≥2 days) or played a match.")
ret = q.retention_by_signup(60)
if not ret.empty:
    ret = ret[ret["n"] > 0].copy()
    ret["ret_pct"] = (100 * ret["returned"] / ret["n"]).round(1)
    ret["play_pct"] = (100 * ret["played"] / ret["n"]).round(1)
    fig = go.Figure()
    fig.add_scatter(x=ret["day"], y=ret["ret_pct"], name="Returned ≥2d",
                    mode="lines+markers", line_color=ARCHERY["primary"])
    fig.add_scatter(x=ret["day"], y=ret["play_pct"], name="Played ≥1 match",
                    mode="lines+markers", line_color=ARCHERY["accent"])
    fig.update_layout(yaxis_title="% of cohort", xaxis_title="Signup day")
    st.plotly_chart(themed(fig), use_container_width=True)

# ── UI screen opens ──────────────────────────────────────────────────────
section("UI screen opens", "Which screens players open, summed across the cohort.")
so = q.screen_open_aggregates()
if not so.empty:
    fig = px.bar(so.head(20), x="total_opens", y="screen", orientation="h")
    fig.update_traces(marker_color=ARCHERY["primary"])
    fig.update_layout(yaxis=dict(autorange="reversed"), xaxis_title="Total opens", yaxis_title="")
    st.plotly_chart(themed(fig), use_container_width=True)
    st.dataframe(
        so.rename(columns={
            "screen": "Screen", "total_opens": "Total opens",
            "unique_users": "Unique users", "avg_per_user": "Avg / user",
        }).round({"Avg / user": 1}),
        use_container_width=True, hide_index=True,
    )
else:
    st.caption("No screen-open telemetry recorded yet.")

footer()
