"""Monetization — Robux purchases, chest opens, conversion."""
from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from lib import queries as q
from lib.theme import (
    ARCHERY, format_n, format_pct, footer, kpi_row, product_name,
    roblox_profile_url, section, setup_page, themed,
)

setup_page("Monetization", icon="💰")
st.markdown("## 💰 Monetization")
st.caption("Robux receipts and chest opens. (Spend in Robux isn't in the save — these are receipt counts.)")

m = q.monetization_summary()
cohort = int(m.get("cohort_n", 0) or 0)
if cohort == 0:
    st.info("No cohort data yet.")
    footer(); st.stop()

payers = int(m.get("payers", 0) or 0)
section("Conversion")
kpi_row([
    {"label": "Paying players", "value": payers,
     "sub": f"of {format_n(cohort)} players", "style": "warn"},
    {"label": "Conversion rate", "value": format_pct(100 * payers / max(cohort, 1))},
    {"label": "Total receipts", "value": int(m.get("total_purchases", 0) or 0)},
    {"label": "Receipts / payer", "value": f"{float(m.get('avg_purchases_per_payer', 0) or 0):.1f}"},
])

# ── Chest opens by tier ──────────────────────────────────────────────────
section("Chest opens by tier")
chests = q.chest_opens_breakdown()
if not chests.empty and chests["opens"].sum() > 0:
    fig = px.bar(chests, x="tier", y="opens")
    fig.update_traces(marker_color=ARCHERY["primary"])
    fig.update_layout(xaxis_title="", yaxis_title="Opens")
    st.plotly_chart(themed(fig), use_container_width=True)
else:
    st.caption("No chest opens recorded yet.")

# ── Products purchased (per-product breakdown from player_purchases) ──────
section("Products purchased", "Per-product receipts from the purchase log — what's actually selling.")
prod = q.product_breakdown(30)
if not prod.empty:
    prod = prod.copy()
    prod["product"] = prod["product_id"].map(product_name)
    fig = px.bar(prod, x="product", y="purchases")
    fig.update_traces(marker_color=ARCHERY["accent"])
    # Force a categorical axis — product IDs are numeric-looking and plotly would
    # otherwise render them as a continuous "3.6B" number line.
    fig.update_layout(xaxis_title="", yaxis_title="Receipts", xaxis_type="category")
    st.plotly_chart(themed(fig), use_container_width=True)
    st.dataframe(
        prod[["product", "product_id", "purchases", "buyers", "first_purchase", "last_purchase"]].rename(columns={
            "product": "Product", "product_id": "Product ID", "purchases": "Receipts",
            "buyers": "Buyers", "first_purchase": "First", "last_purchase": "Last",
        }),
        use_container_width=True, hide_index=True,
    )
else:
    st.caption("No itemised purchases logged yet — the purchase log is empty for this cohort.")

# ── Chest progression (lifetime_wins_for_chests) ─────────────────────────
section("Chest progression", "Lifetime wins counted toward chest rewards — how far players grind.")
cps = q.chest_progress_summary()
with_progress = int(cps.get("with_progress", 0) or 0)
cohort_n = int(cps.get("cohort_n", 0) or 0)
kpi_row([
    {"label": "Players progressing", "value": with_progress,
     "sub": f"of {format_n(cohort_n)} players", "style": "accent"},
    {"label": "Share progressing", "value": format_pct(100 * with_progress / max(cohort_n, 1))},
    {"label": "Median wins-for-chests", "value": f"{float(cps.get('median_progress', 0) or 0):.0f}"},
    {"label": "Max wins-for-chests", "value": int(cps.get("max_progress", 0) or 0)},
])
cp = q.chest_progression()
if not cp.empty:
    fig = px.histogram(cp, x="wins_for_chests", nbins=30)
    fig.update_traces(marker_color=ARCHERY["primary"])
    fig.update_layout(xaxis_title="Lifetime wins for chests", yaxis_title="Players")
    st.plotly_chart(themed(fig), use_container_width=True)
else:
    st.caption("No chest progression recorded yet.")

# ── Top purchasers ───────────────────────────────────────────────────────
section("Top purchasers")
pp = q.purchasers(50)
if not pp.empty:
    pp = pp.copy()
    pp["profile"] = pp["user_id"].map(roblox_profile_url)
    st.dataframe(
        pp[["name", "profile", "purchases", "chest_opens"]].rename(columns={
            "name": "Player", "purchases": "Receipts", "chest_opens": "Chest opens",
        }),
        use_container_width=True, hide_index=True,
        column_config={
            "profile": st.column_config.LinkColumn("Profile", display_text="open ↗"),
        },
    )
    st.caption("Player shows the stored username; click **Profile** to confirm who a bare-ID player is on Roblox.")
else:
    st.caption("No purchases recorded yet.")

footer()
