"""
Global cohort filter — applies to every page.

Renders a sidebar block in `setup_page()`. State lives in
`st.session_state["global_filter"]`. `player_src()` returns either the
bare `players_clean` view or a `(SELECT * FROM players_clean WHERE ...)`
sub-query, so it's a drop-in replacement for `FROM players_clean` in
every query.

The cache layer in `queries.py` keys on the SQL string, so different
filters automatically produce different cache entries.

Archery Duels has no tutorial flow and no per-session platform field
(METRICS.sessions is aggregate-only), so the filter is simpler than
ocean-quest's: join date, playtime bounds, and a minimum-matches cohort.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import streamlit as st


_DEFAULTS: dict[str, Any] = {
    "join_from": None,
    "join_to": None,
    "min_playtime_min": 0,   # minutes
    "max_playtime_h": 0,     # hours, 0 = unlimited
    "min_matches": 0,        # STATS.aggregate.matchesPlayed >= n
    "played_pvp": False,     # only players who've played at least one PvP match
    "opened_inventory": False,  # only players who've opened the Inventory UI >=1x
}


def filter_state() -> dict[str, Any]:
    return st.session_state.get("global_filter") or dict(_DEFAULTS)


def is_filter_active() -> bool:
    f = filter_state()
    return any([
        f.get("join_from"),
        f.get("join_to"),
        (f.get("min_playtime_min") or 0) > 0,
        (f.get("max_playtime_h") or 0) > 0,
        (f.get("min_matches") or 0) > 0,
        f.get("played_pvp"),
        f.get("opened_inventory"),
    ])


def filter_clause() -> str:
    """SQL fragment (no leading WHERE) applying the current filter to the
    `players_clean` view. Returns "" when no filter active."""
    f = filter_state()
    parts: list[str] = []

    if f.get("join_from"):
        parts.append(f"join_date >= DATE '{f['join_from']}'")
    if f.get("join_to"):
        parts.append(f"join_date <= DATE '{f['join_to']}'")

    min_pt = int(f.get("min_playtime_min") or 0)
    if min_pt > 0:
        parts.append(f"playtime_seconds >= {min_pt * 60}")
    max_pt = int(f.get("max_playtime_h") or 0)
    if max_pt > 0:
        parts.append(f"playtime_seconds <= {max_pt * 3600}")

    min_m = int(f.get("min_matches") or 0)
    if min_m > 0:
        parts.append(f"COALESCE(matches_played, 0) >= {min_m}")

    if f.get("played_pvp"):
        parts.append("COALESCE(pvp_matches, 0) > 0")

    if f.get("opened_inventory"):
        # screenOpens lives in the child table player_screen_opens, not on the
        # players_clean view — gate via a semi-join. The strongest retention
        # signal we have: inventory-openers retain ~5x better (see analysis).
        parts.append(
            "user_id IN (SELECT user_id FROM player_screen_opens "
            "WHERE screen = 'Inventory')"
        )

    return " AND ".join(parts)


def player_src() -> str:
    """Drop-in replacement for `players_clean` — applies the global filter
    if any. Always aliased ``p`` so callers can reference ``p.col`` and
    ``p.data->...``. Use as: ``f"FROM {player_src()}"``."""
    where = filter_clause()
    if not where:
        return "players_clean p"
    return f"(SELECT * FROM players_clean WHERE {where}) p"


def render_global_filter() -> None:
    """Render the sidebar filter UI. Call from setup_page()."""
    if "global_filter" not in st.session_state:
        st.session_state["global_filter"] = dict(_DEFAULTS)

    with st.sidebar:
        st.markdown("### 🎯 Global filter")
        st.caption("Applies to every page. Stats, distributions, leaderboards.")

        f = st.session_state["global_filter"]

        with st.expander("Join date range", expanded=bool(f.get("join_from") or f.get("join_to"))):
            # Single range calendar: click the start day, then the end day, on
            # the same popup — the selected span highlights visually. Passing a
            # tuple value (even empty) puts st.date_input in range mode.
            preset: tuple[date, ...] = ()
            if f.get("join_from") and f.get("join_to"):
                preset = (date.fromisoformat(f["join_from"]), date.fromisoformat(f["join_to"]))
            sel = st.date_input(
                "Click start, then end",
                value=preset,
                key="gf_join_range",
                format="YYYY-MM-DD",
                max_value=date.today(),
            )
            # Range mode returns a tuple/list of 0, 1 (mid-pick), or 2 dates.
            if isinstance(sel, (list, tuple)) and len(sel) == 2:
                f["join_from"], f["join_to"] = sel[0].isoformat(), sel[1].isoformat()
            elif isinstance(sel, (list, tuple)) and len(sel) == 1:
                f["join_from"], f["join_to"] = sel[0].isoformat(), None
                st.caption("Click the end date to close the range.")
            elif isinstance(sel, date):  # safety: single-date fallback
                f["join_from"], f["join_to"] = sel.isoformat(), None
            else:
                f["join_from"] = f["join_to"] = None

        f["min_playtime_min"] = st.number_input(
            "Min playtime (minutes)",
            min_value=0, max_value=100_000, value=int(f.get("min_playtime_min") or 0),
            step=1, key="gf_min_pt",
        )
        f["max_playtime_h"] = st.number_input(
            "Max playtime (hours, 0 = ∞)",
            min_value=0, max_value=10_000, value=int(f.get("max_playtime_h") or 0),
            step=1, key="gf_max_pt",
        )
        f["min_matches"] = st.number_input(
            "Min matches played",
            min_value=0, max_value=100_000, value=int(f.get("min_matches") or 0),
            step=1, key="gf_min_matches",
        )
        f["played_pvp"] = st.checkbox(
            "PvP players only", value=bool(f.get("played_pvp")), key="gf_pvp",
        )
        f["opened_inventory"] = st.checkbox(
            "Opened Inventory only", value=bool(f.get("opened_inventory")),
            key="gf_inv",
            help="Players who opened the Inventory UI at least once — the "
                 "strongest retention/engagement signal in the data.",
        )

        if is_filter_active():
            st.markdown(
                "<div style='padding:0.5rem 0.7rem;background:rgba(242,177,52,0.12);"
                "border-left:3px solid #f2b134;border-radius:4px;font-size:0.78rem;'>"
                "🎯 <b>Filter active</b> — all metrics on this page reflect the cohort.</div>",
                unsafe_allow_html=True,
            )
            if st.button("Reset filter", use_container_width=True, key="gf_reset"):
                st.session_state["global_filter"] = dict(_DEFAULTS)
                st.rerun()
