"""
Postgres layer for Archery Duels.

One module owns all SQL: schema creation, the daemon's writes, and the
dashboard's reads. Latest-state-only — re-fetching a player overwrites
their row and the contents of their child tables.

Save shape (see docs/save-structure.md): combined save under DATA/{userId}
with four top-level sections — INVENTORY, METRICS, SETTINGS, STATS.

Connection string comes from $DATABASE_URL.
  - Daemon (on the box):     postgresql://archery_duels_rw:...@localhost/archery_duels
  - Streamlit Cloud reader:  postgresql://archery_duels_ro:...@<host>:5432/archery_duels?sslmode=require
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, date
from typing import Any, Iterable

import psycopg
from psycopg.types.json import Jsonb


# ─── Connection ─────────────────────────────────────────────────────────

def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set. Example: "
            "postgresql://archery_duels_rw:PASS@localhost/archery_duels"
        )
    return url


def connect(autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(database_url(), autocommit=autocommit)


# ─── Schema ─────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS players (
    user_id              BIGINT PRIMARY KEY,
    username             TEXT,
    display_name         TEXT,
    discovered_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_fetched_at      TIMESTAMPTZ,
    status               TEXT,

    -- INVENTORY.currencies
    coins                BIGINT,
    crystals             BIGINT,
    -- INVENTORY.equipped (resolved instance -> item_id)
    equipped_bow         TEXT,
    equipped_axe         TEXT,
    equipped_spear       TEXT,
    items_owned          INT,

    -- STATS.aggregate
    wins                 INT,
    losses               INT,
    matches_played       INT,
    arrows_fired         BIGINT,
    arrows_hit           BIGINT,
    headshots            BIGINT,
    current_win_streak   INT,
    longest_win_streak   INT,
    -- STATS.perMode
    bot_wins             INT,
    bot_losses           INT,
    bot_matches          INT,
    pvp_wins             INT,
    pvp_losses           INT,
    pvp_matches          INT,
    lifetime_wins_for_chests INT,

    -- METRICS.sessions
    playtime_seconds     BIGINT,
    sessions_count       INT,
    days_played          INT,
    longest_session_sec  INT,
    first_join_at        TIMESTAMPTZ,
    last_join_at         TIMESTAMPTZ,
    join_date            DATE,

    -- METRICS.clicks (play-click funnel)
    play_match_clicks            INT,
    play_match_successful        INT,
    bot_match_clicks             INT,
    bot_match_successful         INT,
    first_play_click_at          INT,

    -- METRICS.matches (analytics; matches.played is the metrics-side counter)
    metrics_matches_played       INT,

    -- METRICS.aim — the headline metric
    aim_count            INT,
    aim_tap_fires        INT,
    aim_with_aim_shots   INT,

    -- METRICS.shootDelay / load counts
    shoot_delay_bot_count INT,
    shoot_delay_pvp_count INT,
    load_count           INT,
    load_last_ms         INT,

    -- METRICS.engagement / monetization
    daily_login_claims   INT,
    daily_quest_claims   INT,
    robux_purchases      INT,
    chest_opens_total    INT,

    -- Histograms (length 6 = #edges + 1). Boundaries in PlayerMetricsConfig.lua.
    aim_buckets              INT[],
    shoot_delay_bot_buckets  INT[],
    shoot_delay_pvp_buckets  INT[],
    match_length_buckets     INT[],
    load_buckets             INT[],

    data                 JSONB
);

CREATE INDEX IF NOT EXISTS idx_players_fetch_priority
    ON players (last_fetched_at NULLS FIRST);
CREATE INDEX IF NOT EXISTS idx_players_status        ON players (status);
CREATE INDEX IF NOT EXISTS idx_players_wins_desc     ON players (wins DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_players_last_join     ON players (last_join_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_players_join_date     ON players (join_date);
CREATE INDEX IF NOT EXISTS idx_players_data_gin      ON players USING GIN (data jsonb_path_ops);


-- One row per owned weapon instance (INVENTORY.equipment keyed by uuid).
CREATE TABLE IF NOT EXISTS player_equipment (
    user_id        BIGINT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    instance_id    TEXT NOT NULL,
    item_id        TEXT,
    level          INT,
    rank           INT,
    dupes          INT,
    acquired_at    TIMESTAMPTZ,
    equipped_slot  TEXT,                 -- 'Bow' | 'Axe' | 'Spear' | NULL
    PRIMARY KEY (user_id, instance_id)
);
CREATE INDEX IF NOT EXISTS idx_equipment_item ON player_equipment (item_id);


-- METRICS.engagement.screenOpens — one row per UI screen.
CREATE TABLE IF NOT EXISTS player_screen_opens (
    user_id BIGINT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    screen  TEXT NOT NULL,
    opens   INT,
    PRIMARY KEY (user_id, screen)
);
CREATE INDEX IF NOT EXISTS idx_screen_opens_screen ON player_screen_opens (screen);


-- METRICS.monetization.purchaseLog — capped first-N Robux receipts.
CREATE TABLE IF NOT EXISTS player_purchases (
    user_id     BIGINT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    purchase_ix INT NOT NULL,
    product_id  TEXT,
    grant_key   TEXT,
    purchased_at TIMESTAMPTZ,
    PRIMARY KEY (user_id, purchase_ix)
);
"""


def init_schema(conn: psycopg.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        if not own:
            conn.commit()
    finally:
        if own:
            conn.close()


# ─── Helpers ────────────────────────────────────────────────────────────

def _epoch_to_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    try:
        return datetime.fromtimestamp(v, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _epoch_to_date(value: Any) -> date | None:
    dt = _epoch_to_dt(value)
    return dt.date() if dt else None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_map(value: Any) -> dict:
    """Lua empty tables serialize as JSON ``[]`` (not ``{}``), and older
    saves may omit a field entirely. Map-shaped fields therefore arrive as
    dict | list | None — coerce anything that isn't a populated dict to {}."""
    return value if isinstance(value, dict) else {}


def _buckets(value: Any, size: int = 6) -> list[int]:
    """Normalise a histogram array to a fixed-length list of ints."""
    out = [0] * size
    if isinstance(value, list):
        for i in range(min(size, len(value))):
            out[i] = _safe_int(value[i]) or 0
    return out


# ─── Flatten: JSON blob → typed scalars ─────────────────────────────────

def flatten(data: dict) -> dict[str, Any]:
    """Pull hot scalars out of a combined save dict. Missing fields → None.
    Never raises on shape variation; the save will keep evolving."""
    out: dict[str, Any] = {}

    inv = _as_map(data.get("INVENTORY"))
    cur = _as_map(inv.get("currencies"))
    out["coins"] = _safe_int(cur.get("coins"))
    out["crystals"] = _safe_int(cur.get("crystals"))

    equipment = _as_map(inv.get("equipment"))
    equipped = _as_map(inv.get("equipped"))
    out["items_owned"] = len(equipment)

    def _resolve(slot: str) -> str | None:
        inst = equipped.get(slot)
        entry = equipment.get(inst) if inst is not None else None
        if isinstance(entry, dict) and entry.get("item_id") is not None:
            return str(entry["item_id"])
        return None

    out["equipped_bow"] = _resolve("Bow")
    out["equipped_axe"] = _resolve("Axe")
    out["equipped_spear"] = _resolve("Spear")

    stats = _as_map(data.get("STATS"))
    agg = _as_map(stats.get("aggregate"))
    out["wins"] = _safe_int(agg.get("wins"))
    out["losses"] = _safe_int(agg.get("losses"))
    out["matches_played"] = _safe_int(agg.get("matchesPlayed"))
    out["arrows_fired"] = _safe_int(agg.get("arrowsFired"))
    out["arrows_hit"] = _safe_int(agg.get("arrowsHit"))
    out["headshots"] = _safe_int(agg.get("headshots"))
    out["current_win_streak"] = _safe_int(agg.get("currentWinStreak"))
    out["longest_win_streak"] = _safe_int(agg.get("longestWinStreak"))

    per_mode = _as_map(stats.get("perMode"))
    bot = _as_map(per_mode.get("bot"))
    pvp = _as_map(per_mode.get("pvp"))
    out["bot_wins"] = _safe_int(bot.get("wins"))
    out["bot_losses"] = _safe_int(bot.get("losses"))
    out["bot_matches"] = _safe_int(bot.get("matchesPlayed"))
    out["pvp_wins"] = _safe_int(pvp.get("wins"))
    out["pvp_losses"] = _safe_int(pvp.get("losses"))
    out["pvp_matches"] = _safe_int(pvp.get("matchesPlayed"))
    out["lifetime_wins_for_chests"] = _safe_int(stats.get("lifetimeWinsForChests"))

    m = _as_map(data.get("METRICS"))
    sessions = _as_map(m.get("sessions"))
    out["playtime_seconds"] = _safe_int(sessions.get("totalPlaytime"))
    out["sessions_count"] = _safe_int(sessions.get("totalCount"))
    out["days_played"] = _safe_int(sessions.get("daysPlayed"))
    out["longest_session_sec"] = _safe_int(sessions.get("longestSession"))
    out["first_join_at"] = _epoch_to_dt(sessions.get("firstJoinDate"))
    out["last_join_at"] = _epoch_to_dt(sessions.get("lastJoinDate"))
    out["join_date"] = _epoch_to_date(sessions.get("firstJoinDate"))

    clicks = _as_map(m.get("clicks"))
    out["play_match_clicks"] = _safe_int(clicks.get("playMatch"))
    out["play_match_successful"] = _safe_int(clicks.get("playMatchSuccessful"))
    out["bot_match_clicks"] = _safe_int(clicks.get("botMatch"))
    out["bot_match_successful"] = _safe_int(clicks.get("botMatchSuccessful"))
    out["first_play_click_at"] = _safe_int(clicks.get("firstPlayClickAt"))

    matches = _as_map(m.get("matches"))
    out["metrics_matches_played"] = _safe_int(matches.get("played"))
    out["match_length_buckets"] = _buckets(matches.get("lengthBuckets"))

    aim = _as_map(m.get("aim"))
    out["aim_count"] = _safe_int(aim.get("count"))
    out["aim_tap_fires"] = _safe_int(aim.get("tapFires"))
    out["aim_with_aim_shots"] = _safe_int(aim.get("withAimShots"))
    out["aim_buckets"] = _buckets(aim.get("buckets"))

    shoot = _as_map(m.get("shootDelay"))
    sd_bot = _as_map(shoot.get("bot"))
    sd_pvp = _as_map(shoot.get("pvp"))
    out["shoot_delay_bot_count"] = _safe_int(sd_bot.get("count"))
    out["shoot_delay_pvp_count"] = _safe_int(sd_pvp.get("count"))
    out["shoot_delay_bot_buckets"] = _buckets(sd_bot.get("buckets"))
    out["shoot_delay_pvp_buckets"] = _buckets(sd_pvp.get("buckets"))

    load = _as_map(m.get("load"))
    out["load_count"] = _safe_int(load.get("count"))
    out["load_last_ms"] = _safe_int(load.get("lastMs"))
    out["load_buckets"] = _buckets(load.get("buckets"))

    engagement = _as_map(m.get("engagement"))
    out["daily_login_claims"] = _safe_int(engagement.get("dailyLoginClaims"))
    out["daily_quest_claims"] = _safe_int(engagement.get("dailyQuestClaims"))

    mon = _as_map(m.get("monetization"))
    out["robux_purchases"] = _safe_int(mon.get("robuxPurchases"))
    chest = _as_map(mon.get("chestOpens"))
    out["chest_opens_total"] = sum(_safe_int(v) or 0 for v in chest.values())

    return out


# ─── Child rows ─────────────────────────────────────────────────────────

def _equipment_rows(uid: int, data: dict) -> Iterable[tuple]:
    inv = _as_map(data.get("INVENTORY"))
    equipment = _as_map(inv.get("equipment"))
    equipped = _as_map(inv.get("equipped"))
    # instance_id -> slot it's equipped in (reverse of equipped map)
    slot_of = {v: k for k, v in equipped.items() if v is not None}
    for inst, entry in equipment.items():
        if not isinstance(entry, dict):
            continue
        yield (
            uid,
            str(inst),
            str(entry.get("item_id")) if entry.get("item_id") is not None else None,
            _safe_int(entry.get("level")),
            _safe_int(entry.get("rank")),
            _safe_int(entry.get("dupes")),
            _epoch_to_dt(entry.get("acquiredAt")),
            slot_of.get(inst),
        )


def _screen_open_rows(uid: int, data: dict) -> Iterable[tuple]:
    m = _as_map(data.get("METRICS"))
    eng = _as_map(m.get("engagement"))
    screens = _as_map(eng.get("screenOpens"))
    for screen, opens in screens.items():
        yield (uid, str(screen), _safe_int(opens))


def _purchase_rows(uid: int, data: dict) -> Iterable[tuple]:
    m = _as_map(data.get("METRICS"))
    mon = _as_map(m.get("monetization"))
    log = mon.get("purchaseLog")
    if not isinstance(log, list):
        return
    for ix, p in enumerate(log):
        if not isinstance(p, dict):
            continue
        yield (
            uid,
            ix,
            str(p.get("pid")) if p.get("pid") is not None else None,
            str(p.get("key")) if p.get("key") is not None else None,
            _epoch_to_dt(p.get("ts")),
        )


# ─── Writes ─────────────────────────────────────────────────────────────

def record_discovered(conn: psycopg.Connection, uid: int) -> bool:
    """Mark a player ID as known. Returns True if newly inserted."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO players (user_id) VALUES (%s) "
            "ON CONFLICT (user_id) DO NOTHING",
            (uid,),
        )
        return cur.rowcount == 1


def record_fetch(
    conn: psycopg.Connection,
    uid: int,
    status: str,
    username: str | None,
    display_name: str | None,
    data: dict | None,
) -> None:
    """ETL one player's fetch result.

    For status='ok' with data: upsert the players row (hot scalars + JSONB)
    and replace all child rows. For 'empty'/'failed': only touch the players
    row so a transient failure doesn't wipe child data.
    """
    fetched_at = datetime.now(timezone.utc)

    if status == "ok" and isinstance(data, dict):
        scalars = flatten(data)
        cols = list(scalars.keys())
        with conn.cursor() as cur:
            placeholders = ", ".join(["%s"] * (5 + len(cols)))
            update_set = ", ".join(
                f"{c} = EXCLUDED.{c}" for c in [
                    "username", "display_name", "last_fetched_at", "status", *cols, "data"
                ]
            )
            sql = (
                f"INSERT INTO players "
                f"(user_id, username, display_name, last_fetched_at, status, "
                f"{', '.join(cols)}, data) "
                f"VALUES ({placeholders}, %s) "
                f"ON CONFLICT (user_id) DO UPDATE SET {update_set}"
            )
            params = [
                uid, username, display_name, fetched_at, status,
                *[scalars[c] for c in cols],
                Jsonb(data),
            ]
            cur.execute(sql, params)

            cur.execute("DELETE FROM player_equipment WHERE user_id = %s", (uid,))
            eq = list(_equipment_rows(uid, data))
            if eq:
                cur.executemany(
                    "INSERT INTO player_equipment "
                    "(user_id, instance_id, item_id, level, rank, dupes, acquired_at, equipped_slot) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    eq,
                )

            cur.execute("DELETE FROM player_screen_opens WHERE user_id = %s", (uid,))
            so = list(_screen_open_rows(uid, data))
            if so:
                cur.executemany(
                    "INSERT INTO player_screen_opens (user_id, screen, opens) "
                    "VALUES (%s, %s, %s)",
                    so,
                )

            cur.execute("DELETE FROM player_purchases WHERE user_id = %s", (uid,))
            pu = list(_purchase_rows(uid, data))
            if pu:
                cur.executemany(
                    "INSERT INTO player_purchases "
                    "(user_id, purchase_ix, product_id, grant_key, purchased_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    pu,
                )
    else:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO players (user_id, username, display_name, "
                "last_fetched_at, status) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET "
                "username = COALESCE(EXCLUDED.username, players.username), "
                "display_name = COALESCE(EXCLUDED.display_name, players.display_name), "
                "last_fetched_at = EXCLUDED.last_fetched_at, "
                "status = EXCLUDED.status",
                (uid, username, display_name, fetched_at, status),
            )

    conn.commit()


# ─── Reads (used by the daemon; the dashboard reads via lib/queries.py) ──

def select_targets(
    conn: psycopg.Connection,
    refresh_after_hours: float | None,
    limit: int,
) -> list[int]:
    """UIDs to fetch this run, in priority order: never-fetched, then failed,
    then stale (if a cutoff is given)."""
    parts = [
        "SELECT user_id FROM players "
        "WHERE last_fetched_at IS NULL OR status IS NULL ORDER BY discovered_at",
        "SELECT user_id FROM players "
        "WHERE status = 'failed' ORDER BY last_fetched_at NULLS FIRST",
    ]
    if refresh_after_hours is not None and refresh_after_hours > 0:
        parts.append(
            f"SELECT user_id FROM players "
            f"WHERE status IN ('ok','empty') "
            f"AND last_fetched_at < NOW() - INTERVAL '{float(refresh_after_hours)} hours' "
            f"ORDER BY last_fetched_at NULLS FIRST"
        )
    union = " UNION ALL ".join(f"({p})" for p in parts)
    with conn.cursor() as cur:
        cur.execute(f"SELECT user_id FROM ({union}) q LIMIT %s", (limit,))
        return [r[0] for r in cur.fetchall()]


def count_by_status(conn: psycopg.Connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(status, 'unfetched'), COUNT(*) FROM players GROUP BY 1"
        )
        return {row[0]: row[1] for row in cur.fetchall()}


def count_total(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM players")
        return cur.fetchone()[0]


# ─── CLI: `python db.py init|status` ────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "init"
    if cmd == "init":
        init_schema()
        print("Schema initialised.")
    elif cmd == "status":
        with connect() as c:
            counts = count_by_status(c)
            total = count_total(c)
        print(f"Total players: {total}")
        for k, v in sorted(counts.items()):
            print(f"  {k:11s} {v}")
    else:
        print(f"Unknown command: {cmd!r}")
        print("Usage: python db.py [init|status]")
        sys.exit(1)
