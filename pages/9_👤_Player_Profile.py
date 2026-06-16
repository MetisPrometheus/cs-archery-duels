"""Player Profile — drill into a single player's stats, inventory and metrics."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from lib import queries as q
from lib.theme import (
    ARCHERY, format_n, format_pct, format_time, format_ts, footer,
    kpi_row, section, setup_page,
)

setup_page("Player Profile", icon="👤")
st.markdown("## 👤 Player Profile")
st.caption("Search by username or user id, then drill into one player.")

query = st.text_input("Search player", placeholder="username or user id…")
results = q.player_search(query.strip(), limit=30)

if results.empty:
    st.info("No matching players.")
    footer(); st.stop()

def _label(r) -> str:
    name = r["username"] or r["display_name"] or str(r["user_id"])
    return f"{name}  ·  {int(r['wins'] or 0)}W / {int(r['matches_played'] or 0)}M  ·  id:{r['user_id']}"

options = {(_label(r)): int(r["user_id"]) for _, r in results.iterrows()}
choice = st.selectbox("Pick a player", list(options.keys()))
uid = options[choice]

p = q.player_full(uid)
if not p:
    st.warning("Player not found in the clean view.")
    footer(); st.stop()

name = p.get("username") or p.get("display_name") or str(uid)
st.markdown(f"### {name}")
st.caption(f"user id {uid} · last fetched {format_ts(p['last_fetched_at'].timestamp() if p.get('last_fetched_at') else None)}")

# ── Headline stats ───────────────────────────────────────────────────────
section("Stats")
af, ah = int(p.get("arrows_fired", 0) or 0), int(p.get("arrows_hit", 0) or 0)
kpi_row([
    {"label": "Wins / Losses", "value": f"{int(p.get('wins',0) or 0)} / {int(p.get('losses',0) or 0)}"},
    {"label": "Matches", "value": int(p.get("matches_played", 0) or 0),
     "sub": f"{int(p.get('pvp_matches',0) or 0)} PvP · {int(p.get('bot_matches',0) or 0)} bot"},
    {"label": "Accuracy", "value": format_pct(100*ah/af) if af else "—",
     "sub": f"{format_n(ah)} / {format_n(af)} arrows"},
    {"label": "Longest streak", "value": int(p.get("longest_win_streak", 0) or 0)},
])
kpi_row([
    {"label": "Playtime", "value": format_time(p.get("playtime_seconds"))},
    {"label": "Sessions", "value": int(p.get("sessions_count", 0) or 0),
     "sub": f"{int(p.get('days_played',0) or 0)} days"},
    {"label": "Coins", "value": int(p.get("coins", 0) or 0)},
    {"label": "Robux receipts", "value": int(p.get("robux_purchases", 0) or 0)},
])

# ── Percentile ranks ─────────────────────────────────────────────────────
section("Where they rank", "Percentile within the current cohort.")
cols = st.columns(4)
for col, (mc, lab) in zip(cols, [
    ("wins", "Wins"), ("matches_played", "Matches"),
    ("playtime_seconds", "Playtime"), ("longest_win_streak", "Best streak"),
]):
    pct = q.player_percentile(uid, mc)
    with col:
        st.metric(lab, format_pct(pct) if pct is not None else "—",
                  help="Higher = ahead of more of the cohort")

# ── Equipment ────────────────────────────────────────────────────────────
section("Equipment")
eq = q.player_equipment(uid)
if not eq.empty:
    st.dataframe(
        eq.rename(columns={
            "item_id": "Item", "level": "Lvl", "rank": "Rank",
            "dupes": "Dupes", "equipped_slot": "Equipped",
        })[["Item", "Lvl", "Rank", "Dupes", "Equipped"]],
        use_container_width=True, hide_index=True,
    )
else:
    st.caption("No equipment rows.")

# ── Screen opens ─────────────────────────────────────────────────────────
section("UI screen opens")
so = q.player_screen_opens(uid)
if not so.empty:
    st.dataframe(so.rename(columns={"screen": "Screen", "opens": "Opens"}),
                 use_container_width=True, hide_index=True)
else:
    st.caption("No screen-open telemetry for this player.")

# ── Raw save ─────────────────────────────────────────────────────────────
with st.expander("Raw combined save (JSONB)"):
    st.json(p.get("data") or {})

footer()
