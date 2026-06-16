"""Inventory & Economy — currencies, item ownership, equipped weapons."""
from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from lib import queries as q
from lib.theme import (
    ARCHERY, WEAPON_COLORS, format_n, format_time, footer, kpi_row,
    section, setup_page, themed,
)

setup_page("Inventory", icon="🎒")
st.markdown("## 🎒 Inventory & Economy")
st.caption("Currencies, item ownership and which weapons players run.")

cur = q.currency_stats()
if cur.empty:
    st.info("No cohort data yet.")
    footer(); st.stop()

section("Currency totals")
kpi_row([
    {"label": "Total coins", "value": int(cur["coins"].sum())},
    {"label": "Coins / player", "avg": format_n(cur["coins"].mean()),
     "median": format_n(cur["coins"].median())},
    {"label": "Total crystals", "value": int(cur["crystals"].sum())},
    {"label": "Items / player", "avg": f"{cur['items_owned'].mean():.1f}",
     "median": f"{cur['items_owned'].median():.0f}"},
])

# ── Equipped weapon breakdown per slot ───────────────────────────────────
section("Equipped weapons by slot", "What players actually run in each slot.")
cols = st.columns(3)
for col, slot in zip(cols, ["Bow", "Axe", "Spear"]):
    with col:
        brk = q.equipped_breakdown(slot)
        if brk.empty:
            st.caption(f"No {slot} data.")
            continue
        fig = go.Figure(go.Pie(
            labels=brk["item_id"], values=brk["n"], hole=0.5,
            title=slot,
        ))
        fig.update_traces(marker=dict(line=dict(color=ARCHERY["bg"], width=1)))
        st.plotly_chart(themed(fig, slot), use_container_width=True)

# ── Item popularity ──────────────────────────────────────────────────────
section("Item ownership", "Across every owned instance (player_equipment).")
items = q.item_popularity(40)
if not items.empty:
    fig = px.bar(items.head(20), x="owners", y="item_id", orientation="h")
    fig.update_traces(marker_color=ARCHERY["primary"])
    fig.update_layout(yaxis=dict(autorange="reversed"), xaxis_title="Owners", yaxis_title="")
    st.plotly_chart(themed(fig, "Top items by owners"), use_container_width=True)

    st.dataframe(
        items.rename(columns={
            "item_id": "Item", "owners": "Owners", "instances": "Instances",
            "equipped_count": "Equipped", "avg_level": "Avg level",
            "max_level": "Max level", "max_rank": "Max rank", "total_dupes": "Dupes",
        }).round({"Avg level": 1}),
        use_container_width=True, hide_index=True,
    )

# ── Coin distribution ────────────────────────────────────────────────────
section("Coin distribution", "Players with > 0 coins.")
pos = cur[cur["coins"] > 0]
if not pos.empty:
    fig = px.histogram(pos, x="coins", nbins=40)
    fig.update_traces(marker_color=ARCHERY["accent"])
    fig.update_layout(xaxis_title="Coins", yaxis_title="Players")
    st.plotly_chart(themed(fig), use_container_width=True)

footer()
