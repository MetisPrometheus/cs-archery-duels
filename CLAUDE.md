# CLAUDE.md — cs-archery-duels

Context for any future Claude session opening this repo. Read this first.

**Companion read for box-level / cross-project context:**
[`iw-infra/CLAUDE.md`](https://github.com/MetisPrometheus/iw-infra/blob/main/CLAUDE.md)
— the shared Hetzner box, canonical `setup.sh`, naming conventions, ops.
This file describes only **what's specific to Archery Duels**.

It is the sibling of [`cs-ocean-quest`](https://github.com/MetisPrometheus/cs-ocean-quest)
and was built from the same pattern — if something here is underspecified,
the ocean-quest repo is the reference implementation.

---

## What this repo is

Data platform for **Archery Duels**, a Roblox game by **Copium Studios**.

- A Roblox Open Cloud DataStore dumper runs as a long-lived systemd daemon on
  the shared `iw-infra` box, fetches every player's saved game state, and
  writes to Postgres on the same box.
- A Streamlit dashboard ([dashboard.py](dashboard.py) + [pages/](pages/))
  auto-deploys to Streamlit Community Cloud and reads Postgres over public TLS
  via a read-only role.

## Architecture

```
GitHub (this repo)
  ├──► Streamlit Community Cloud (auto-deploys dashboard.py)
  │       │  postgresql://archery_duels_ro:...@89.167.9.101:5432/archery_duels?sslmode=require
  │       ▼
  └──► Hetzner CX33, Helsinki (host: iw-infra, IP: 89.167.9.101)
        ├── PostgreSQL 16, DB `archery_duels`
        │     ├── archery_duels_rw (daemon writes)
        │     └── archery_duels_ro (Streamlit Cloud reads)
        ├── archery-duels-fetch.service     (long-running daemon)
        └── archery-duels-discover.timer    (hourly DataStore rescan)
```

Universe ID: **`10297420029`**. Open Cloud key needs the Archery Duels
experience in its access list with `universe-datastores` List Data Stores +
List Keys + Read Entry.

## Files & responsibilities

| Path | Purpose |
|---|---|
| [`db.py`](db.py) | All Postgres logic. Schema, `flatten()` (hot scalars), child-row builders, `record_fetch` ETL, `select_targets`. CLI: `python db.py init` / `status`. |
| [`dump_all_players.py`](dump_all_players.py) | Two-phase resumable dumper (ported from ocean-quest). Modes `--daemon`/`--discover-only`/one-shot. Token bucket + cooldown. |
| [`dump_one_player.py`](dump_one_player.py) | Single-player DataStore inspector — discovery/debug tool (stdlib-only). List stores/keys, dump one entry, auto-probe by user id. |
| [`dashboard.py`](dashboard.py) | Streamlit home (KPIs + funnel + aim teaser). |
| [`pages/`](pages/) | Funnel · Aim Analysis · Combat · Match Flow · Inventory · Monetization · Engagement · Performance · Player Profile. |
| [`lib/queries.py`](lib/queries.py) | Every Postgres read for the dashboard, cached 10 min, keyed on SQL string. |
| [`lib/theme.py`](lib/theme.py) | Palette (archery gold/red), KPI primitives, formatters, bucket labels. |
| [`lib/filters.py`](lib/filters.py) | Global cohort filter (join date, playtime, min matches, PvP-only). |
| [`deploy/`](deploy/) | systemd units + `players_clean_view.sql`. Provisioned by `iw-infra/setup.sh`. |
| [`docs/save-structure.md`](docs/save-structure.md) | **The ground-truth save shape**, captured live. Read before changing the schema. |

## Data model — read docs/save-structure.md before schema changes

**Latest state only — no per-fetch history.** Re-fetching overwrites the row
and its child rows.

- Save lives under DataStore `DATA/{userId}`, numeric version keys, latest = max
  (same mechanics as ocean-quest).
- Four top-level save sections: `INVENTORY`, `METRICS`, `SETTINGS`, `STATS`.
- `players` — one row per player; hot scalars flattened from all four sections,
  five histogram `INT[]` columns (aim / shoot-delay bot+pvp / match-length /
  load), full combined save in `data JSONB`.
- `players_clean` — **view** (`status='ok'` + playtime sanity guard). **All
  dashboard queries read this, not `players`.** Defined in
  [`deploy/players_clean_view.sql`](deploy/players_clean_view.sql).
- Child tables: `player_equipment`, `player_screen_opens`, `player_purchases`.

**ETL gotcha:** empty Lua tables serialize as JSON `[]` (not `{}`), and older
saves omit fields. Map-shaped fields (`screenOpens`, `purchaseLog`,
`daysPlayedSet`) arrive as dict | list | None — `db._as_map()` coerces anything
that isn't a populated dict to `{}`. The JSONB blob is the safety net for
fields not yet flattened: `data->'METRICS'->'...'`.

Histogram bucket edges are authored in the game's `PlayerMetricsConfig.lua`
(single source of truth) and mirrored as labels in [`lib/theme.py`](lib/theme.py).
Changing an edge in Lua changes what new counts mean — treat as a schema change.

## Common operations

```bash
ssh root@89.167.9.101
sudo journalctl -u archery-duels-fetch -f
cd /opt/projects/archery-duels && git pull && sudo systemctl restart archery-duels-fetch
sudo -u postgres psql -d archery_duels -c "
  SELECT COALESCE(status,'unfetched') AS s, COUNT(*) FROM players GROUP BY 1;"
```

## Conventions

- **Secrets live in `/etc/archery-duels/env` on the box, not in this repo.**
  `.env.example` and `.streamlit/secrets.toml.example` are templates.
- `_rw` role writes on the box; `_ro` role for everything external (Streamlit).
- Linux/dir name is bare (`archery-duels`); GitHub repo is `cs-archery-duels`.
- No fetch history by design. Don't add `app.py` — Streamlit reads `dashboard.py`.

## Things this repo deliberately does NOT do

- No per-fetch history (re-fetch overwrites). No webhooks (pure polling).
- No CI/CD — push to main → Streamlit Cloud auto-deploys; box does `git pull && systemctl restart`.
- Does not run Streamlit on the box (that's Streamlit Cloud).
