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
