# cs-archery-duels

Data platform for **Archery Duels**, a Roblox game by **Copium Studios** —
same pattern as [`cs-ocean-quest`](https://github.com/MetisPrometheus/cs-ocean-quest):
an Open Cloud DataStore dumper writes player saves to Postgres on the shared
`iw-infra` Hetzner box, and a Streamlit Cloud dashboard reads them over public
TLS via a read-only role. Shared infra/provisioning lives in
[`iw-infra`](https://github.com/MetisPrometheus/iw-infra).

Universe ID `10297420029`. See [`CLAUDE.md`](CLAUDE.md) for the full picture and
[`docs/save-structure.md`](docs/save-structure.md) for the real save shape.

## Layout

```
db.py                  Postgres schema + ETL (flatten + child tables)
dump_all_players.py    Resumable two-phase dumper (daemon / discover / one-shot)
dump_one_player.py     Single-player DataStore inspector (discovery/debug tool)
dashboard.py           Streamlit home
pages/                 Funnel · Aim · Combat · Match Flow · Inventory ·
                       Monetization · Engagement · Performance · Player Profile
lib/                   queries (cached SQL) · theme · global filter
deploy/                systemd units + players_clean_view.sql
docs/save-structure.md ground-truth save shape (captured live)
```

## Local dev

```bash
cp .env.example .env          # ROBLOX_API_KEY + ROBLOX_UNIVERSE_ID + DATABASE_URL
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt

# Inspect one player's live save (no DB needed):
./venv/bin/python dump_one_player.py --user <userId>

# Run the dumper once against the DB:
./venv/bin/python db.py init
./venv/bin/python dump_all_players.py --max 50

# Run the dashboard locally (needs DATABASE_URL):
./venv/bin/streamlit run dashboard.py
```

## Deploy

See [`deploy/README.md`](deploy/README.md). On the box: clone, run
`iw-infra/setup.sh archery-duels`, drop secrets into `/etc/archery-duels/env`,
start the daemon. Dashboard auto-deploys from `main` to Streamlit Cloud.
