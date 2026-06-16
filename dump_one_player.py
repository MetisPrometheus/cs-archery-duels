"""
Archery Duels — single-player DataStore inspector (discovery tool).

Purpose: before we design the Postgres schema and the dashboard, we want to
SEE the real shape of a player's save as it actually sits in Roblox Open
Cloud — not infer it from the Lua config. This tool reaches into the
universe's DataStores and pretty-prints what's there.

It is deliberately stdlib-only (no venv needed) and makes only a handful of
requests, so there's no rate limiter — that machinery lives in the full
`dump_all_players.py` we'll build once the structure is known.

Credentials come from `.env` (copy `.env.example`):
    ROBLOX_API_KEY        Open Cloud key with DataStore read scope on the
                          Archery Duels universe
    ROBLOX_UNIVERSE_ID    the Archery Duels universe id (NOT ocean-quest's)

──────────────────────────────────────────────────────────────────────────
Modes (run them in this order when you don't yet know the layout):

  # 1. What DataStores exist in this universe? (reveals naming convention)
  python dump_one_player.py --list-stores

  # 2. What do the keys look like inside a given store?
  python dump_one_player.py --store PlayerData --list-keys

  # 3. Dump one specific entry, pretty-printed (and saved to ./samples/)
  python dump_one_player.py --store PlayerData --key Player_12345678

  # 4. Don't know where a player lives? Best-effort auto-probe: scan every
  #    store, try a bunch of key patterns derived from the user id, dump hits.
  python dump_one_player.py --user 12345678

  # Ordered DataStores (used by ocean-quest for "latest version key"):
  python dump_one_player.py --list-ordered
──────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ── .env loading (same lightweight pattern as ocean-quest) ──────────────
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

API_KEY = os.environ.get("ROBLOX_API_KEY", "")
UNIVERSE_ID = os.environ.get("ROBLOX_UNIVERSE_ID", "")

BASE = (
    f"https://apis.roblox.com/datastores/v1/universes/{UNIVERSE_ID}"
    f"/standard-datastores"
)
ORDERED_BASE = (
    f"https://apis.roblox.com/ordered-datastores/v1/universes/{UNIVERSE_ID}"
    f"/orderedDataStores"
)

SAMPLES_DIR = Path(__file__).parent / "samples"
TIMEOUT = 30


# ── HTTP ────────────────────────────────────────────────────────────────
def _get(url: str) -> tuple[int, object]:
    """Returns (http_status, parsed_json_or_text). Never raises on HTTP error."""
    req = urllib.request.Request(url, headers={"x-api-key": API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            pass
        return e.code, body
    except urllib.error.URLError as e:
        print(f"  ! network error: {e}", file=sys.stderr)
        return 0, None


def _q(s: str) -> str:
    return urllib.parse.quote(s, safe="")


# ── Operations ──────────────────────────────────────────────────────────
def list_stores() -> list[str]:
    """List every standard DataStore name in the universe (paginated)."""
    names: list[str] = []
    cursor = ""
    while True:
        url = f"{BASE}?limit=100"
        if cursor:
            url += f"&cursor={_q(cursor)}"
        status, data = _get(url)
        if status != 200 or not isinstance(data, dict):
            print(f"  ! list-stores failed (HTTP {status}): {data}", file=sys.stderr)
            break
        for ds in data.get("datastores", []):
            names.append(ds.get("name", ""))
        cursor = data.get("nextPageCursor", "")
        if not cursor:
            break
    return names


def list_keys(store: str, limit: int = 100, prefix: str = "") -> list[str]:
    """List entry keys in a standard DataStore (first `limit`)."""
    keys: list[str] = []
    cursor = ""
    while len(keys) < limit:
        url = f"{BASE}/datastore/entries?datastoreName={_q(store)}&limit=100"
        if prefix:
            url += f"&prefix={_q(prefix)}"
        if cursor:
            url += f"&cursor={_q(cursor)}"
        status, data = _get(url)
        if status != 200 or not isinstance(data, dict):
            print(f"  ! list-keys failed (HTTP {status}): {data}", file=sys.stderr)
            break
        for k in data.get("keys", []):
            keys.append(k.get("key", ""))
        cursor = data.get("nextPageCursor", "")
        if not cursor:
            break
    return keys[:limit]


def get_entry(store: str, key: str) -> tuple[int, object]:
    url = f"{BASE}/datastore/entries/entry?datastoreName={_q(store)}&entryKey={_q(key)}"
    return _get(url)


def list_ordered() -> object:
    status, data = _get(f"{ORDERED_BASE}?max_page_size=100")
    if status != 200:
        print(f"  ! list-ordered failed (HTTP {status}): {data}", file=sys.stderr)
        return None
    return data


def _save_sample(name: str, payload: object) -> Path:
    SAMPLES_DIR.mkdir(exist_ok=True)
    safe = name.replace("/", "_").replace(" ", "_")
    path = SAMPLES_DIR / f"{safe}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def _pretty(payload: object) -> str:
    if isinstance(payload, str):
        # Roblox often stores the save as a JSON string inside the entry —
        # try to parse it so we see real structure, not an escaped string.
        try:
            return json.dumps(json.loads(payload), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            return payload
    return json.dumps(payload, indent=2, ensure_ascii=False)


# Key patterns to try in --user auto-probe. Covers the common Roblox save
# libraries (ProfileService, DataStore2, raw user-id keys, ocean-quest's
# DATA/{uid} convention).
def _key_candidates(uid: int) -> list[str]:
    return [
        str(uid),
        f"Player_{uid}",
        f"Player{uid}",
        f"player_{uid}",
        f"user_{uid}",
        f"DATA/{uid}",
        f"DATA_{uid}",
        f"{uid}_data",
        f"profile_{uid}",
        f"Data_{uid}",
    ]


def auto_probe(uid: int) -> None:
    print(f"[auto-probe] scanning every DataStore for user {uid}\n")
    stores = list_stores()
    if not stores:
        print("  no DataStores found (or no read access). Check creds/scopes.")
        return
    print(f"  {len(stores)} stores to probe: {stores}\n")
    hits = 0
    for store in stores:
        for key in _key_candidates(uid):
            status, data = get_entry(store, key)
            if status == 200 and data is not None:
                hits += 1
                print(f"  ✓ HIT  store={store!r}  key={key!r}")
                saved = _save_sample(f"{store}__{key}", data)
                print(f"        saved → {saved}")
    if hits == 0:
        print(
            "  no hits. The key pattern is unusual — run --list-stores then\n"
            "  --store <name> --list-keys to see the real key format, then\n"
            "  --store <name> --key <key> to dump it."
        )
    else:
        print(f"\n  {hits} entry(ies) dumped to {SAMPLES_DIR}/")


# ── CLI ─────────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(
        description="Archery Duels single-player DataStore inspector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--list-stores", action="store_true",
                   help="List all DataStore names in the universe")
    p.add_argument("--list-ordered", action="store_true",
                   help="List ordered DataStores in the universe")
    p.add_argument("--store", help="DataStore name to operate on")
    p.add_argument("--key", help="Entry key to dump (with --store)")
    p.add_argument("--list-keys", action="store_true",
                   help="List keys in --store (use with --store, optional --prefix)")
    p.add_argument("--prefix", default="", help="Key prefix filter for --list-keys")
    p.add_argument("--user", type=int,
                   help="Auto-probe: scan every store for this user id")
    args = p.parse_args()

    if not API_KEY:
        print("ERROR: ROBLOX_API_KEY is not set (copy .env.example → .env)")
        sys.exit(1)
    if not UNIVERSE_ID:
        print("ERROR: ROBLOX_UNIVERSE_ID is not set (Archery Duels universe id)")
        sys.exit(1)

    if args.list_stores:
        names = list_stores()
        print(f"{len(names)} DataStore(s) in universe {UNIVERSE_ID}:")
        for n in names:
            print(f"  • {n}")
        return

    if args.list_ordered:
        print(_pretty(list_ordered()))
        return

    if args.user:
        auto_probe(args.user)
        return

    if args.store and args.list_keys:
        keys = list_keys(args.store, prefix=args.prefix)
        print(f"{len(keys)} key(s) in {args.store!r}"
              + (f" (prefix {args.prefix!r})" if args.prefix else "") + ":")
        for k in keys:
            print(f"  • {k}")
        return

    if args.store and args.key:
        status, data = get_entry(args.store, args.key)
        print(f"HTTP {status}  store={args.store!r}  key={args.key!r}\n")
        if status == 200 and data is not None:
            print(_pretty(data))
            saved = _save_sample(f"{args.store}__{args.key}", data)
            print(f"\nsaved → {saved}")
        else:
            print(_pretty(data))
        return

    p.print_help()


if __name__ == "__main__":
    main()
