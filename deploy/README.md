# cs-archery-duels deploy

Project-specific deploy artifacts. The **provisioning script lives in
[`iw-infra`](https://github.com/MetisPrometheus/iw-infra)**, not here — this
folder only holds the three systemd units specific to this project. The shared
`setup.sh`, Postgres config, and ops docs are reused for every project on the box.

## What's in here

| File | Purpose |
|---|---|
| [`archery-duels-fetch.service`](archery-duels-fetch.service) | Long-running daemon that batches Roblox player fetches. `User=archery-duels`, `EnvironmentFile=/etc/archery-duels/env`. |
| [`archery-duels-discover.service`](archery-duels-discover.service) | One-shot DataStore rescan invoked by the timer. |
| [`archery-duels-discover.timer`](archery-duels-discover.timer) | Hourly trigger for the discover service. |
| [`players_clean_view.sql`](players_clean_view.sql) | The `players_clean` view every dashboard query reads from. |

`iw-infra/setup.sh` globs `<project>/deploy/*.service` + `*.timer`, installs
them into `/etc/systemd/system/`, and enables them.

## Provisioning the box

```bash
ssh root@89.167.9.101

cd /opt/projects
git clone https://github.com/MetisPrometheus/cs-archery-duels.git archery-duels
sudo bash /opt/projects/iw-infra/setup.sh archery-duels

# Python env for the daemon
cd /opt/projects/archery-duels
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt

# Secrets (type the key directly — never paste into chat)
sudo $EDITOR /etc/archery-duels/env        # ROBLOX_API_KEY + ROBLOX_UNIVERSE_ID=10297420029 + DATABASE_URL(_rw)

# Schema + clean view
./venv/bin/python db.py init
sudo -u postgres psql -d archery_duels -f deploy/players_clean_view.sql

sudo systemctl restart archery-duels-fetch
sudo systemctl enable --now archery-duels-discover.timer
```

`setup.sh` prints the read-only connection string. **Save it in 1Password as
`iw-infra · archery_duels_ro`** — it's what Streamlit Cloud uses.

## Streamlit Cloud secret

Settings → Secrets:

```toml
DATABASE_URL = "postgresql://archery_duels_ro:PASSWORD@89.167.9.101:5432/archery_duels?sslmode=require"
```

## Verifying

```bash
systemctl status archery-duels-fetch --no-pager
sudo journalctl -u archery-duels-fetch -f
sudo -u postgres psql -d archery_duels -c "
  SELECT COALESCE(status,'unfetched') AS s, COUNT(*) FROM players GROUP BY 1;"
```

## Updating after a code change

```bash
cd /opt/projects/archery-duels && git pull && sudo systemctl restart archery-duels-fetch
```

If you changed a `.service`/`.timer`, re-run the provisioner (it re-copies and
reloads systemd):

```bash
sudo bash /opt/projects/iw-infra/setup.sh archery-duels
```

For cross-project ops (DB shell, role rotation, recovery), see
[`iw-infra/docs/operations.md`](https://github.com/MetisPrometheus/iw-infra/blob/main/docs/operations.md).
