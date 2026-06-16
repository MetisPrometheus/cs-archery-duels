# cs-archery-duels

Data platform for **Archery Duels**, a Roblox game by **Copium Studios** —
same pattern as [`cs-ocean-quest`](https://github.com/MetisPrometheus/cs-ocean-quest):
an Open Cloud DataStore dumper writes player saves to Postgres on the shared
`iw-infra` Hetzner box, and a Streamlit Cloud dashboard reads them over public
TLS via a read-only role. Shared infra/provisioning lives in
[`iw-infra`](https://github.com/MetisPrometheus/iw-infra).

## Status: discovery phase

We're building this in order. **Step 1 (now): confirm the real save structure**
before designing the schema — using the single-player inspector rather than
inferring shape from the game's Lua `PlayerMetricsConfig` / STATS modules.

```bash
cp .env.example .env        # fill in ROBLOX_API_KEY + ROBLOX_UNIVERSE_ID
# (no venv needed — the inspector is stdlib-only)

python dump_one_player.py --list-stores              # what stores exist?
python dump_one_player.py --store <name> --list-keys # key naming?
python dump_one_player.py --store <name> --key <key> # dump one entry
python dump_one_player.py --user <userId>            # or auto-probe by user id
```

Dumped entries are saved (pretty-printed) under `samples/` (git-ignored).

> **API key:** the ocean-quest Open Cloud key is scoped to the ocean-quest
> universe only and won't read Archery Duels. Either add the Archery Duels
> experience to that key's access list, or create a new key — then put it and
> the Archery Duels universe id in `.env`.

## Still to build (after we see real structure)

- `db.py` — Postgres schema + ETL, modelled on the actual save (STATS +
  METRICS). The METRICS side is histogram-bucket-heavy (aim hold, shoot delay,
  match length, load time) per `PlayerMetricsConfig`.
- `dump_all_players.py` — full resumable two-phase dumper (port from
  ocean-quest: token bucket, cooldown, `--daemon`/`--discover-only`).
- `dashboard.py` + `pages/` + `lib/` — Streamlit dashboard.
- `deploy/` — systemd units; provision via `iw-infra/setup.sh archery-duels`.

See [`CLAUDE.md`](CLAUDE.md) for the per-project context a future session needs.
