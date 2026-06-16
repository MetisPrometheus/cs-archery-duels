"""Monetization — Robux purchases, chest opens, conversion."""
from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from lib import queries as q
from lib.theme import (
    ARCHERY, format_n, format_pct, footer, kpi_row, section, setup_page, themed,
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

# ── Top purchasers ───────────────────────────────────────────────────────
section("Top purchasers")
pp = q.purchasers(50)
if not pp.empty:
    st.dataframe(
        pp[["name", "purchases", "chest_opens"]].rename(columns={
            "name": "Player", "purchases": "Receipts", "chest_opens": "Chest opens",
        }),
        use_container_width=True, hide_index=True,
    )
else:
    st.caption("No purchases recorded yet.")

footer()
