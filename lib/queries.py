"""
Centralised data layer for the Streamlit dashboard.

Everything that touches Postgres lives here. The underlying connection is
created once via @st.cache_resource. Most functions go through ``df()`` which
is @st.cache_data so the cache key is the SQL string — the global filter
(which mutates the SQL) automatically gets its own cache slot.

The "real players" definition lives in the `players_clean` view
(deploy/players_clean_view.sql). Don't re-add inline status filters here.
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd
import psycopg
import streamlit as st
from psycopg.rows import dict_row

from lib.filters import player_src, filter_clause


# ── Connection ──────────────────────────────────────────────────────────
def _database_url() -> str:
    if hasattr(st, "secrets"):
        try:
            url = st.secrets.get("DATABASE_URL")
            if url:
                return url
        except (FileNotFoundError, KeyError, AttributeError):
            pass
    url = os.environ.get("DATABASE_URL")
    if not url:
        st.error(
            "DATABASE_URL is not configured. Set it in `.streamlit/secrets.toml` "
            "(Streamlit Cloud secrets panel) or as an env var locally."
        )
        st.stop()
    return url


@st.cache_resource(show_spinner=False)
def get_conn() -> psycopg.Connection:
    return psycopg.connect(_database_url(), row_factory=dict_row, autocommit=True)


def _exec(sql: str, params: tuple = ()) -> list[dict]:
    try:
        with get_conn().cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())
    except (psycopg.OperationalError, psycopg.InterfaceError):
        get_conn.clear()
        with get_conn().cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


@st.cache_data(ttl=600, show_spinner=False)
def df(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run an arbitrary SELECT and return as DataFrame. Cached 10 min."""
    return pd.DataFrame(_exec(sql, params))


def _user_id_in_filter() -> str:
    """SQL fragment for child-table queries: restrict to user_ids that pass
    the global filter. Empty string when no filter active."""
    where = filter_clause()
    if not where:
        return ""
    return f" user_id IN (SELECT user_id FROM players_clean WHERE {where}) "


# ── Dumper progress (never filtered) ─────────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def fetch_status_counts() -> dict:
    rows = _exec(
        "SELECT COALESCE(status,'unfetched') AS s, COUNT(*) AS c FROM players GROUP BY 1"
    )
    return {r["s"]: r["c"] for r in rows}


# ── Top-level KPI summary ───────────────────────────────────────────────
def kpi_summary() -> dict[str, Any]:
    """Headline numbers for the home page. `total_known`/`total_fetched` are
    dumper-progress counters on raw `players` (never filtered). Everything
    else respects the global filter via `player_src()`."""
    src = player_src()
    rows = df(
        f"""
        SELECT
            (SELECT COUNT(*) FROM players)                     AS total_known,
            (SELECT COUNT(*) FROM players WHERE status='ok')   AS total_fetched,
            (SELECT COUNT(*) FROM players_clean)               AS total_clean,
            COUNT(*)                                                          AS cohort_n,
            COUNT(*) FILTER (WHERE COALESCE(matches_played,0) >= 1)           AS played_1,
            COUNT(*) FILTER (WHERE COALESCE(matches_played,0) >= 5)           AS played_5,
            COUNT(*) FILTER (WHERE COALESCE(wins,0) >= 1)                     AS won_1,
            COUNT(*) FILTER (WHERE COALESCE(pvp_matches,0) >= 1)              AS pvp_1,
            COUNT(*) FILTER (WHERE last_join_at > NOW() - INTERVAL '7 days')  AS active_7d,
            COUNT(*) FILTER (WHERE last_join_at > NOW() - INTERVAL '24 hours') AS active_1d,
            COALESCE(SUM(matches_played), 0)                AS total_matches,
            COALESCE(SUM(wins), 0)                          AS total_wins,
            COALESCE(SUM(arrows_fired), 0)                  AS total_arrows_fired,
            COALESCE(SUM(arrows_hit), 0)                    AS total_arrows_hit,
            COALESCE(SUM(coins), 0)                          AS total_coins,
            COALESCE(SUM(robux_purchases), 0)                AS total_robux_purchases,
            COUNT(*) FILTER (WHERE COALESCE(robux_purchases,0) > 0)          AS paying_players,
            COALESCE(SUM(playtime_seconds), 0)              AS total_playtime_sec,
            COALESCE(AVG(playtime_seconds) FILTER (WHERE playtime_seconds > 0), 0)::float AS avg_playtime_sec,
            COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY playtime_seconds)
                     FILTER (WHERE playtime_seconds > 0), 0)::float AS median_playtime_sec,
            COALESCE(AVG(matches_played) FILTER (WHERE matches_played > 0), 0)::float AS avg_matches,
            COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY matches_played)
                     FILTER (WHERE matches_played > 0), 0)::float AS median_matches
        FROM {src}
        """
    )
    return {} if rows.empty else rows.iloc[0].to_dict()


# ── Funnels ──────────────────────────────────────────────────────────────
def match_funnel() -> pd.DataFrame:
    """Engagement funnel by progression milestones."""
    src = player_src()
    rows = df(
        f"""
        SELECT
            COUNT(*)                                                  AS s0,
            COUNT(*) FILTER (WHERE COALESCE(play_match_clicks,0)>0
                                OR COALESCE(bot_match_clicks,0)>0)    AS s1,
            COUNT(*) FILTER (WHERE COALESCE(matches_played,0)>=1)     AS s2,
            COUNT(*) FILTER (WHERE COALESCE(wins,0)>=1)               AS s3,
            COUNT(*) FILTER (WHERE COALESCE(matches_played,0)>=5)     AS s4,
            COUNT(*) FILTER (WHERE COALESCE(pvp_matches,0)>=1)        AS s5,
            COUNT(*) FILTER (WHERE COALESCE(pvp_wins,0)>=1)           AS s6
        FROM {src}
        """
    )
    if rows.empty:
        return pd.DataFrame()
    r = rows.iloc[0]
    return pd.DataFrame([
        {"step": "Fetched",      "label": "Account exists",       "n": int(r["s0"])},
        {"step": "Clicked play", "label": "Clicked play/bot",     "n": int(r["s1"])},
        {"step": "1 match",      "label": "Played ≥ 1 match",     "n": int(r["s2"])},
        {"step": "1 win",        "label": "Won ≥ 1 match",        "n": int(r["s3"])},
        {"step": "5 matches",    "label": "Played ≥ 5 matches",   "n": int(r["s4"])},
        {"step": "PvP",          "label": "Played ≥ 1 PvP match", "n": int(r["s5"])},
        {"step": "PvP win",      "label": "Won ≥ 1 PvP match",    "n": int(r["s6"])},
    ])


def click_funnel() -> pd.DataFrame:
    """Play-button click → slot-claimed conversion, bot vs pvp path."""
    src = player_src()
    rows = df(
        f"""
        SELECT
            COALESCE(SUM(play_match_clicks),0)       AS pvp_clicks,
            COALESCE(SUM(play_match_successful),0)   AS pvp_ok,
            COALESCE(SUM(bot_match_clicks),0)        AS bot_clicks,
            COALESCE(SUM(bot_match_successful),0)    AS bot_ok
        FROM {src}
        """
    )
    if rows.empty:
        return pd.DataFrame()
    r = rows.iloc[0]
    return pd.DataFrame([
        {"path": "PvP",  "clicks": int(r["pvp_clicks"]), "claimed": int(r["pvp_ok"])},
        {"path": "Bot",  "clicks": int(r["bot_clicks"]), "claimed": int(r["bot_ok"])},
    ])


def daily_signups(days: int = 60) -> pd.DataFrame:
    src = player_src()
    return df(
        f"""
        SELECT join_date AS day, COUNT(*) AS new_players
        FROM {src}
        WHERE join_date IS NOT NULL AND join_date > CURRENT_DATE - %s::interval
        GROUP BY 1 ORDER BY 1
        """,
        (f"{days} days",),
    )


def daily_active(days: int = 30) -> pd.DataFrame:
    src = player_src()
    return df(
        f"""
        SELECT DATE(last_join_at) AS day, COUNT(*) AS active
        FROM {src}
        WHERE last_join_at IS NOT NULL AND last_join_at > NOW() - %s::interval
        GROUP BY 1 ORDER BY 1
        """,
        (f"{days} days",),
    )


# ── Histogram buckets (INT[] columns summed across the cohort) ───────────
_BUCKET_COLS = {
    "aim_buckets",
    "shoot_delay_bot_buckets",
    "shoot_delay_pvp_buckets",
    "match_length_buckets",
    "load_buckets",
}


def bucket_totals(col: str, labels: list[str]) -> pd.DataFrame:
    """Sum a length-6 INT[] histogram column element-wise across the cohort.
    `labels` names each bucket slot. `col` must be whitelisted."""
    if col not in _BUCKET_COLS:
        raise ValueError(f"Unsafe bucket column: {col}")
    src = player_src()
    rows = df(
        f"""
        SELECT idx, SUM(val)::bigint AS n
        FROM {src},
             unnest(COALESCE(p.{col}, ARRAY[0,0,0,0,0,0])) WITH ORDINALITY AS t(val, idx)
        GROUP BY idx ORDER BY idx
        """
    )
    if rows.empty:
        return pd.DataFrame({"bucket": labels, "n": [0] * len(labels)})
    counts = {int(r.idx): int(r.n) for r in rows.itertuples()}
    return pd.DataFrame(
        {"bucket": labels, "n": [counts.get(i + 1, 0) for i in range(len(labels))]}
    )


def aim_summary() -> dict[str, Any]:
    """The headline aim question: are players tap-firing or learning to hold-aim?"""
    src = player_src()
    rows = df(
        f"""
        SELECT
            COALESCE(SUM(aim_count), 0)          AS shots,
            COALESCE(SUM(aim_tap_fires), 0)      AS tap_fires,
            COALESCE(SUM(aim_with_aim_shots), 0) AS with_aim,
            COUNT(*) FILTER (WHERE COALESCE(aim_count,0) > 0) AS players_with_aim_data
        FROM {src}
        """
    )
    return {} if rows.empty else rows.iloc[0].to_dict()


# ── Combat / stats ───────────────────────────────────────────────────────
def combat_stats() -> pd.DataFrame:
    src = player_src()
    return df(
        f"""
        SELECT
            user_id,
            COALESCE(username, display_name, user_id::text) AS name,
            COALESCE(wins,0)               AS wins,
            COALESCE(losses,0)             AS losses,
            COALESCE(matches_played,0)     AS matches,
            COALESCE(arrows_fired,0)       AS arrows_fired,
            COALESCE(arrows_hit,0)         AS arrows_hit,
            COALESCE(headshots,0)          AS headshots,
            COALESCE(current_win_streak,0) AS current_streak,
            COALESCE(longest_win_streak,0) AS longest_streak,
            COALESCE(bot_matches,0)        AS bot_matches,
            COALESCE(pvp_matches,0)        AS pvp_matches,
            COALESCE(pvp_wins,0)           AS pvp_wins,
            COALESCE(pvp_losses,0)         AS pvp_losses,
            COALESCE(playtime_seconds,0)   AS playtime,
            CASE WHEN COALESCE(arrows_fired,0) > 0
                 THEN arrows_hit::float / arrows_fired * 100 END AS accuracy,
            CASE WHEN COALESCE(matches_played,0) > 0
                 THEN wins::float / matches_played * 100 END     AS winrate
        FROM {src}
        """
    )


def mode_split() -> pd.DataFrame:
    """Aggregate bot vs pvp totals."""
    src = player_src()
    rows = df(
        f"""
        SELECT
            COALESCE(SUM(bot_matches),0) AS bot_matches,
            COALESCE(SUM(bot_wins),0)    AS bot_wins,
            COALESCE(SUM(bot_losses),0)  AS bot_losses,
            COALESCE(SUM(pvp_matches),0) AS pvp_matches,
            COALESCE(SUM(pvp_wins),0)    AS pvp_wins,
            COALESCE(SUM(pvp_losses),0)  AS pvp_losses
        FROM {src}
        """
    )
    if rows.empty:
        return pd.DataFrame()
    r = rows.iloc[0]
    return pd.DataFrame([
        {"mode": "Bot", "matches": int(r["bot_matches"]), "wins": int(r["bot_wins"]), "losses": int(r["bot_losses"])},
        {"mode": "PvP", "matches": int(r["pvp_matches"]), "wins": int(r["pvp_wins"]), "losses": int(r["pvp_losses"])},
    ])


def percentile(metric_col: str) -> pd.DataFrame:
    safe = {
        "wins", "losses", "matches_played", "arrows_fired", "arrows_hit",
        "headshots", "longest_win_streak", "playtime_seconds", "coins",
        "crystals", "pvp_matches", "pvp_wins", "robux_purchases", "items_owned",
    }
    if metric_col not in safe:
        raise ValueError(f"Unsafe metric: {metric_col}")
    src = player_src()
    return df(
        f"""
        SELECT
            COALESCE(MIN({metric_col}), 0)                                          AS p_min,
            COALESCE(percentile_cont(0.10) WITHIN GROUP (ORDER BY {metric_col}), 0) AS p10,
            COALESCE(percentile_cont(0.25) WITHIN GROUP (ORDER BY {metric_col}), 0) AS p25,
            COALESCE(percentile_cont(0.50) WITHIN GROUP (ORDER BY {metric_col}), 0) AS p50,
            COALESCE(percentile_cont(0.75) WITHIN GROUP (ORDER BY {metric_col}), 0) AS p75,
            COALESCE(percentile_cont(0.90) WITHIN GROUP (ORDER BY {metric_col}), 0) AS p90,
            COALESCE(percentile_cont(0.99) WITHIN GROUP (ORDER BY {metric_col}), 0) AS p99,
            COALESCE(MAX({metric_col}), 0)                                          AS p_max,
            COALESCE(AVG({metric_col}), 0)                                          AS avg
        FROM {src} WHERE {metric_col} > 0
        """
    )


def top_players(metric: str, n: int = 20) -> pd.DataFrame:
    safe = {
        "wins", "losses", "matches_played", "arrows_fired", "arrows_hit",
        "headshots", "longest_win_streak", "current_win_streak",
        "playtime_seconds", "sessions_count", "days_played", "coins",
        "crystals", "pvp_matches", "pvp_wins", "robux_purchases", "items_owned",
    }
    if metric not in safe:
        raise ValueError(f"Unsafe metric: {metric}")
    src = player_src()
    return df(
        f"""
        SELECT user_id, COALESCE(username, display_name, user_id::text) AS name,
               {metric} AS value, last_join_at,
               COALESCE(matches_played,0) AS matches, COALESCE(wins,0) AS wins
        FROM {src}
        WHERE {metric} IS NOT NULL
        ORDER BY {metric} DESC NULLS LAST
        LIMIT %s
        """,
        (n,),
    )


# ── Inventory / economy ──────────────────────────────────────────────────
def currency_stats() -> pd.DataFrame:
    src = player_src()
    return df(
        f"""
        SELECT
            user_id,
            COALESCE(coins,0)            AS coins,
            COALESCE(crystals,0)         AS crystals,
            COALESCE(items_owned,0)      AS items_owned,
            COALESCE(playtime_seconds,0) AS playtime
        FROM {src}
        """
    )


def equipped_breakdown(slot: str) -> pd.DataFrame:
    """How many players have each item equipped in a given slot."""
    col = {"Bow": "equipped_bow", "Axe": "equipped_axe", "Spear": "equipped_spear"}.get(slot)
    if not col:
        raise ValueError(f"Unknown slot: {slot}")
    src = player_src()
    return df(
        f"""
        SELECT COALESCE({col}, 'none') AS item_id, COUNT(*) AS n
        FROM {src} GROUP BY 1 ORDER BY 2 DESC
        """
    )


def item_popularity(n: int = 30) -> pd.DataFrame:
    """Ownership of each item across the cohort, from player_equipment."""
    user_in = _user_id_in_filter()
    where = f"WHERE {user_in}" if user_in else ""
    return df(
        f"""
        SELECT
            item_id,
            COUNT(*)                                  AS instances,
            COUNT(DISTINCT user_id)                   AS owners,
            COUNT(*) FILTER (WHERE equipped_slot IS NOT NULL) AS equipped_count,
            COALESCE(AVG(level), 0)::float            AS avg_level,
            COALESCE(MAX(level), 0)                   AS max_level,
            COALESCE(MAX(rank), 0)                    AS max_rank,
            COALESCE(SUM(dupes), 0)                   AS total_dupes
        FROM player_equipment
        {where}
        GROUP BY item_id
        ORDER BY owners DESC NULLS LAST
        LIMIT %s
        """,
        (n,),
    )


# ── Monetization ─────────────────────────────────────────────────────────
def monetization_summary() -> dict[str, Any]:
    src = player_src()
    rows = df(
        f"""
        SELECT
            COUNT(*)                                              AS cohort_n,
            COUNT(*) FILTER (WHERE COALESCE(robux_purchases,0)>0) AS payers,
            COALESCE(SUM(robux_purchases),0)                      AS total_purchases,
            COALESCE(SUM(chest_opens_total),0)                    AS total_chest_opens,
            COALESCE(AVG(robux_purchases) FILTER (WHERE robux_purchases>0),0)::float AS avg_purchases_per_payer
        FROM {src}
        """
    )
    return {} if rows.empty else rows.iloc[0].to_dict()


def chest_opens_breakdown() -> pd.DataFrame:
    """Sum chest opens by tier from the JSONB blob."""
    src = player_src()
    return df(
        f"""
        SELECT tier, SUM(COALESCE(cnt,0))::bigint AS opens
        FROM {src},
             LATERAL (VALUES
                ('Small',       (p.data->'METRICS'->'monetization'->'chestOpens'->>'Small')::int),
                ('Medium',      (p.data->'METRICS'->'monetization'->'chestOpens'->>'Medium')::int),
                ('Large',       (p.data->'METRICS'->'monetization'->'chestOpens'->>'Large')::int),
                ('MythicChest', (p.data->'METRICS'->'monetization'->'chestOpens'->>'MythicChest')::int)
             ) AS t(tier, cnt)
        GROUP BY tier ORDER BY opens DESC
        """
    )


def purchasers(n: int = 50) -> pd.DataFrame:
    src = player_src()
    return df(
        f"""
        SELECT user_id, COALESCE(username, display_name, user_id::text) AS name,
               COALESCE(robux_purchases,0) AS purchases,
               COALESCE(chest_opens_total,0) AS chest_opens,
               COALESCE(playtime_seconds,0) AS playtime
        FROM {src}
        WHERE COALESCE(robux_purchases,0) > 0
        ORDER BY robux_purchases DESC
        LIMIT %s
        """,
        (n,),
    )


def chest_progress_summary() -> dict[str, Any]:
    """Headline numbers for `lifetime_wins_for_chests` — the win-count players
    grind toward chest rewards. Stats over players who have any progress."""
    src = player_src()
    rows = df(
        f"""
        SELECT
            COUNT(*)                                                            AS cohort_n,
            COUNT(*) FILTER (WHERE COALESCE(lifetime_wins_for_chests,0) > 0)     AS with_progress,
            COALESCE(AVG(lifetime_wins_for_chests)
                     FILTER (WHERE lifetime_wins_for_chests > 0), 0)::float      AS avg_progress,
            COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY lifetime_wins_for_chests)
                     FILTER (WHERE lifetime_wins_for_chests > 0), 0)::float      AS median_progress,
            COALESCE(MAX(lifetime_wins_for_chests), 0)                          AS max_progress
        FROM {src}
        """
    )
    return {} if rows.empty else rows.iloc[0].to_dict()


def chest_progression() -> pd.DataFrame:
    """Per-player `lifetime_wins_for_chests` for players with any progress,
    for a distribution histogram."""
    src = player_src()
    return df(
        f"""
        SELECT user_id, COALESCE(lifetime_wins_for_chests, 0) AS wins_for_chests
        FROM {src}
        WHERE COALESCE(lifetime_wins_for_chests, 0) > 0
        """
    )


def product_breakdown(n: int = 30) -> pd.DataFrame:
    """Product-level purchase breakdown from the player_purchases child table
    (which the dashboard otherwise never surfaces — only the aggregate count)."""
    user_in = _user_id_in_filter()
    where = f"WHERE {user_in}" if user_in else ""
    return df(
        f"""
        SELECT
            COALESCE(product_id, '(unknown)')  AS product_id,
            COUNT(*)                           AS purchases,
            COUNT(DISTINCT user_id)            AS buyers,
            MIN(purchased_at)                  AS first_purchase,
            MAX(purchased_at)                  AS last_purchase
        FROM player_purchases
        {where}
        GROUP BY product_id
        ORDER BY purchases DESC NULLS LAST
        LIMIT %s
        """,
        (n,),
    )


# ── Engagement ───────────────────────────────────────────────────────────
def screen_open_aggregates() -> pd.DataFrame:
    user_in = _user_id_in_filter()
    where = f"WHERE {user_in}" if user_in else ""
    return df(
        f"""
        SELECT screen,
               SUM(opens)  AS total_opens,
               COUNT(*)    AS unique_users,
               AVG(opens)::float AS avg_per_user
        FROM player_screen_opens
        {where}
        GROUP BY screen ORDER BY total_opens DESC
        """
    )


def engagement_stats() -> pd.DataFrame:
    src = player_src()
    return df(
        f"""
        SELECT
            user_id,
            COALESCE(daily_login_claims,0) AS login_claims,
            COALESCE(daily_quest_claims,0) AS quest_claims,
            COALESCE(sessions_count,0)     AS sessions,
            COALESCE(days_played,0)        AS days_played,
            COALESCE(playtime_seconds,0)   AS playtime,
            COALESCE(longest_session_sec,0) AS longest_session
        FROM {src}
        """
    )


def playtime_survival() -> pd.DataFrame:
    """Drop-off / survival curve: % of players who reached at least N minutes
    of LIFETIME play. Columns: seconds, minutes, remaining, pct.

    Source is `METRICS.sessions.totalPlaytime` (flattened to `playtime_seconds`).
    As of the heartbeat fix this accumulates live during play instead of only on
    player-leave, so it's now populated for ~all active players and reads as true
    lifetime engagement. (Pre-fix saves still show 0 and sink to the first bucket.)
    """
    src = player_src()
    thresholds = [
        0, 30, 60, 90, 120, 180, 240, 300, 420, 600, 900, 1200, 1500,
        1800, 2400, 3000, 3600, 4800, 6000,
    ]
    out = df(
        f"""
        WITH base AS (
            SELECT COALESCE(p.playtime_seconds, 0) AS pt
            FROM {src}
        ), tot AS (SELECT COUNT(*)::float n FROM base)
        SELECT thr AS seconds,
               (SELECT COUNT(*) FROM base WHERE pt >= thr)                          AS remaining,
               (SELECT COUNT(*) FROM base WHERE pt >= thr)::float
                   / NULLIF((SELECT n FROM tot), 0) * 100                            AS pct
        FROM unnest(%s::int[]) AS thr
        ORDER BY thr
        """,
        (thresholds,),
    )
    if not out.empty:
        out["minutes"] = (out["seconds"] / 60).round(2)
        out["pct"] = out["pct"].round(1)
    return out


def retention_by_signup(days: int = 60) -> pd.DataFrame:
    """For each signup day, how many came back ≥2 days / played ≥1 match."""
    src = player_src()
    return df(
        f"""
        SELECT
            join_date AS day,
            COUNT(*) AS n,
            COUNT(*) FILTER (WHERE COALESCE(days_played,0) >= 2)     AS returned,
            COUNT(*) FILTER (WHERE COALESCE(matches_played,0) >= 1)  AS played
        FROM {src}
        WHERE join_date IS NOT NULL AND join_date > CURRENT_DATE - %s::interval
        GROUP BY 1 ORDER BY 1
        """,
        (f"{days} days",),
    )


# ── Performance (load time) ──────────────────────────────────────────────
def load_summary() -> dict[str, Any]:
    src = player_src()
    rows = df(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE COALESCE(load_count,0) > 0) AS players_with_load,
            COALESCE(SUM(load_count),0)                        AS total_samples,
            COALESCE(AVG(load_last_ms) FILTER (WHERE load_last_ms > 0),0)::float AS avg_last_ms,
            COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY load_last_ms)
                     FILTER (WHERE load_last_ms > 0),0)::float AS median_last_ms,
            COALESCE(percentile_cont(0.9) WITHIN GROUP (ORDER BY load_last_ms)
                     FILTER (WHERE load_last_ms > 0),0)::float AS p90_last_ms
        FROM {src}
        """
    )
    return {} if rows.empty else rows.iloc[0].to_dict()


# ── Player profile ───────────────────────────────────────────────────────
def player_search(q: str, limit: int = 30) -> pd.DataFrame:
    src = player_src()
    if not q:
        return df(
            f"""
            SELECT user_id, username, display_name, last_fetched_at,
                   playtime_seconds, wins, matches_played
            FROM {src}
            ORDER BY playtime_seconds DESC NULLS LAST LIMIT %s
            """,
            (limit,),
        )
    return df(
        f"""
        SELECT user_id, username, display_name, last_fetched_at,
               playtime_seconds, wins, matches_played
        FROM {src}
        WHERE username ILIKE %s OR display_name ILIKE %s OR user_id::text = %s
        ORDER BY playtime_seconds DESC NULLS LAST LIMIT %s
        """,
        (f"%{q}%", f"%{q}%", q, limit),
    )


def player_full(user_id: int) -> dict | None:
    rows = _exec("SELECT * FROM players_clean WHERE user_id = %s", (int(user_id),))
    return rows[0] if rows else None


def player_equipment(user_id: int) -> pd.DataFrame:
    return df(
        """
        SELECT instance_id, item_id, level, rank, dupes, acquired_at, equipped_slot
        FROM player_equipment WHERE user_id = %s
        ORDER BY equipped_slot NULLS LAST, item_id
        """,
        (int(user_id),),
    )


def player_screen_opens(user_id: int) -> pd.DataFrame:
    return df(
        "SELECT screen, opens FROM player_screen_opens WHERE user_id = %s ORDER BY opens DESC",
        (int(user_id),),
    )


def player_percentile(user_id: int, metric_col: str) -> float | None:
    safe = {
        "wins", "matches_played", "arrows_hit", "headshots",
        "longest_win_streak", "playtime_seconds", "coins", "pvp_wins",
    }
    if metric_col not in safe:
        return None
    src = player_src()
    rows = _exec(
        f"""
        WITH player AS (SELECT {metric_col} AS v FROM players_clean WHERE user_id = %s)
        SELECT COUNT(*) FILTER (WHERE p.{metric_col} <= player.v)::float
               / NULLIF(COUNT(*),0)::float * 100 AS pct
        FROM {src}, player
        WHERE p.{metric_col} IS NOT NULL
        """,
        (int(user_id),),
    )
    if not rows or rows[0]["pct"] is None:
        return None
    return float(rows[0]["pct"])


# ════════════════════════════════════════════════════════════════════════
# First-Time User Experience (FTUE)
#
# Sources (all populated by the session-metrics ETL in db.py, fed by the
# heartbeat-flushed save rows):
#   • player_sessions  — one row per session; idx=1 is the first-ever session.
#   • player_matches   — one row per match;   idx=1 is the first-ever match.
#   • first_day_*       — flattened rollup of all sessions in the first 24h.
#   • player_screen_opens / chest_opens_total — what they reached.
# Every query respects the global cohort filter via player_src().
# ════════════════════════════════════════════════════════════════════════

def ftue_summary() -> dict[str, Any]:
    """Headline first-session numbers, denominator = players whose first
    session was captured (post heartbeat-fix)."""
    src = player_src()
    rows = df(
        f"""
        WITH fs AS (
            SELECT DISTINCT ON (s.user_id) s.*
            FROM player_sessions s JOIN {src} ON p.user_id = s.user_id
            ORDER BY s.user_id, s.idx
        )
        SELECT
            COUNT(*)                                                    AS players,
            AVG(duration_s)::float                                      AS avg_dur,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_s)::float AS median_dur,
            AVG(games_bot + games_pvp)::float                          AS avg_games,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY (games_bot+games_pvp))::float AS median_games,
            100.0*COUNT(*) FILTER (WHERE games_pvp > 0)/NULLIF(COUNT(*),0)        AS pct_pvp,
            100.0*COUNT(*) FILTER (WHERE wins_bot+wins_pvp > 0)/NULLIF(COUNT(*),0) AS pct_won,
            100.0*COUNT(*) FILTER (WHERE ended_after_loss)/NULLIF(COUNT(*),0)     AS pct_ended_loss,
            100.0*COUNT(*) FILTER (WHERE left_mid_match)/NULLIF(COUNT(*),0)       AS pct_left_mid,
            AVG(aim_shots)::float                                       AS avg_aim_shots,
            AVG(players_on_leave)::float                               AS avg_players_on_leave
        FROM fs
        """
    )
    return {} if rows.empty else rows.iloc[0].to_dict()


def first_day_summary() -> dict[str, Any]:
    """First-24h rollup (first_day_* columns)."""
    src = player_src()
    rows = df(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE first_day_recorded)                          AS players,
            AVG(first_day_playtime_s) FILTER (WHERE first_day_recorded)::float  AS avg_playtime,
            AVG(first_day_sessions)   FILTER (WHERE first_day_recorded)::float  AS avg_sessions,
            AVG(first_day_games_bot + first_day_games_pvp)
                FILTER (WHERE first_day_recorded)::float                        AS avg_games,
            AVG(first_day_wins_bot + first_day_wins_pvp)
                FILTER (WHERE first_day_recorded)::float                        AS avg_wins
        FROM {src}
        """
    )
    return {} if rows.empty else rows.iloc[0].to_dict()


def first_session_duration_dist() -> pd.DataFrame:
    """Histogram of first-session length. Ordered by `ord`."""
    src = player_src()
    return df(
        f"""
        WITH fs AS (
            SELECT DISTINCT ON (s.user_id) s.duration_s
            FROM player_sessions s JOIN {src} ON p.user_id = s.user_id
            ORDER BY s.user_id, s.idx
        )
        SELECT bucket, ord, COUNT(*) AS n FROM (
            SELECT CASE
                WHEN duration_s <   60 THEN '0–1m'
                WHEN duration_s <  120 THEN '1–2m'
                WHEN duration_s <  300 THEN '2–5m'
                WHEN duration_s <  600 THEN '5–10m'
                WHEN duration_s < 1200 THEN '10–20m'
                ELSE '20m+' END AS bucket,
            CASE
                WHEN duration_s <   60 THEN 0 WHEN duration_s <  120 THEN 1
                WHEN duration_s <  300 THEN 2 WHEN duration_s <  600 THEN 3
                WHEN duration_s < 1200 THEN 4 ELSE 5 END AS ord
            FROM fs
        ) t GROUP BY bucket, ord ORDER BY ord
        """
    )


def first_session_games_dist() -> pd.DataFrame:
    """Distribution of #games played in the first session (capped 6+)."""
    src = player_src()
    return df(
        f"""
        WITH fs AS (
            SELECT DISTINCT ON (s.user_id) LEAST(s.games_bot + s.games_pvp, 6) AS games
            FROM player_sessions s JOIN {src} ON p.user_id = s.user_id
            ORDER BY s.user_id, s.idx
        )
        SELECT games, COUNT(*) AS n FROM fs GROUP BY 1 ORDER BY 1
        """
    )


def ftue_first_matches(n_first: int = 3) -> pd.DataFrame:
    """Maps & modes of each player's first N matches, with win-rate."""
    src = player_src()
    return df(
        f"""
        SELECT m.map, m.mode, COUNT(*) AS n,
               100.0*COUNT(*) FILTER (WHERE m.result = 1)/NULLIF(COUNT(*),0) AS winrate
        FROM player_matches m JOIN {src} ON p.user_id = m.user_id
        WHERE m.idx <= %s
        GROUP BY 1, 2 ORDER BY n DESC
        """,
        (n_first,),
    )


def first_match_outcome_retention() -> pd.DataFrame:
    """Does the result of a player's VERY FIRST match predict retention?"""
    src = player_src()
    return df(
        f"""
        WITH fm AS (
            SELECT DISTINCT ON (m.user_id) m.user_id, m.result, m.mode
            FROM player_matches m JOIN {src} ON p.user_id = m.user_id
            ORDER BY m.user_id, m.idx
        )
        SELECT
            CASE fm.result WHEN 1 THEN 'Won 1st match'
                           WHEN -1 THEN 'Lost 1st match' ELSE 'Tied 1st' END AS outcome,
            fm.result AS ord,
            COUNT(*) AS players,
            100.0*COUNT(*) FILTER (WHERE COALESCE(p2.days_played,0) >= 2)/NULLIF(COUNT(*),0) AS pct_returned,
            AVG(COALESCE(p2.matches_played,0))::float AS avg_matches,
            AVG(COALESCE(p2.playtime_seconds,0))::float AS avg_playtime
        FROM fm JOIN players_clean p2 ON p2.user_id = fm.user_id
        GROUP BY 1, 2 ORDER BY 2 DESC
        """
    )


def ftue_reach_funnel() -> pd.DataFrame:
    """How far through the FTUE experience the cohort gets. Cohort-relative %."""
    src = player_src()
    rows = df(
        f"""
        WITH c AS (SELECT * FROM {src})
        SELECT
            COUNT(*) AS joined,
            COUNT(*) FILTER (WHERE COALESCE(matches_played,0) >= 1) AS played_1,
            COUNT(*) FILTER (WHERE COALESCE(matches_played,0) >= 3) AS played_3,
            COUNT(*) FILTER (WHERE COALESCE(wins,0) >= 1)           AS won_1,
            COUNT(*) FILTER (WHERE COALESCE(pvp_matches,0) >= 1)    AS tried_pvp,
            COUNT(*) FILTER (WHERE user_id IN
                (SELECT user_id FROM player_screen_opens WHERE screen='Inventory')) AS opened_inv,
            COUNT(*) FILTER (WHERE COALESCE(chest_opens_total,0) >= 1) AS got_chest,
            COUNT(*) FILTER (WHERE COALESCE(days_played,0) >= 2)    AS returned
        FROM c
        """
    )
    if rows.empty:
        return rows
    r = rows.iloc[0]
    stages = [
        ("Joined", r["joined"]),
        ("Played 1 match", r["played_1"]),
        ("Played 3 matches", r["played_3"]),
        ("Won a match", r["won_1"]),
        ("Tried PvP", r["tried_pvp"]),
        ("Opened inventory", r["opened_inv"]),
        ("Got a chest", r["got_chest"]),
        ("Returned (day 2)", r["returned"]),
    ]
    base = float(r["joined"]) or 1.0
    return pd.DataFrame({
        "stage": [s for s, _ in stages],
        "n": [int(v) for _, v in stages],
        "pct": [round(100*v/base, 1) for _, v in stages],
    })


def stayers_vs_quitters() -> pd.DataFrame:
    """Behaviour comparison across retention cohorts. The 'what do stayers do
    that quitters don't' table — the nudge map."""
    src = player_src()
    return df(
        f"""
        WITH c AS (
            SELECT p.*,
                CASE WHEN COALESCE(days_played,0) >= 2          THEN 'Stayers (≥2 days)'
                     WHEN COALESCE(sessions_count,0) <= 1       THEN 'One-and-done'
                     ELSE 'Same-day returners' END AS grp
            FROM {src}
        ),
        fs AS (SELECT DISTINCT ON (user_id) * FROM player_sessions ORDER BY user_id, idx)
        SELECT
            c.grp,
            COUNT(*) AS players,
            AVG(COALESCE(c.playtime_seconds,0))::float                 AS avg_playtime,
            AVG(COALESCE(c.matches_played,0))::float                   AS avg_matches,
            100.0*COUNT(*) FILTER (WHERE COALESCE(c.pvp_matches,0)>0)/COUNT(*) AS pct_pvp,
            100.0*COUNT(*) FILTER (WHERE COALESCE(c.wins,0)>0)/COUNT(*)        AS pct_won,
            100.0*COUNT(*) FILTER (WHERE c.user_id IN
                (SELECT user_id FROM player_screen_opens WHERE screen='Inventory'))/COUNT(*) AS pct_inv,
            100.0*COUNT(*) FILTER (WHERE COALESCE(c.chest_opens_total,0)>0)/COUNT(*) AS pct_chest,
            AVG(fs.duration_s)::float                                  AS avg_first_dur,
            AVG(fs.games_bot + fs.games_pvp)::float                    AS avg_first_games
        FROM c LEFT JOIN fs ON fs.user_id = c.user_id
        GROUP BY c.grp
        """
    )


def early_match_matchmaking(n_first: int = 5) -> pd.DataFrame:
    """Power matchup (mine vs opponent) across the first N matches, by match
    number & mode. Surfaces whether new players get power-stomped early."""
    src = player_src()
    return df(
        f"""
        SELECT m.idx AS match_no, m.mode,
               COUNT(*) AS n,
               AVG(m.my_power)::float  AS my_power,
               AVG(m.opp_power)::float AS opp_power,
               AVG(m.opp_power - m.my_power)::float AS power_gap,
               100.0*COUNT(*) FILTER (WHERE m.result = 1)/NULLIF(COUNT(*),0) AS winrate
        FROM player_matches m JOIN {src} ON p.user_id = m.user_id
        WHERE m.idx <= %s AND m.my_power > 0 AND m.opp_power > 0
        GROUP BY 1, 2 ORDER BY 1, 2
        """,
        (n_first,),
    )
