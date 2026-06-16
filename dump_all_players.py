"""
Roblox player save dumper for Archery Duels.

Two-phase, resumable, Postgres-backed (ported from cs-ocean-quest — the
DataStore mechanics are identical: one DATA/{userId} store per player with
numeric version keys, latest = highest):
  PHASE 1 — Discovery: scan DataStores for DATA/{userId}, insert each new
            player ID into the Postgres `players` table.
  PHASE 2 — Fetch: pull the latest combined save for each player whose
            `last_fetched_at IS NULL`, then for `status='failed'`, then
            (if --refresh-after) for stale rows. ETL lives in db.record_fetch.

Resume is automatic — every fetch result is persisted immediately.

Modes:
  python dump_all_players.py                  # one-shot: discover + fetch + exit
  python dump_all_players.py --daemon         # forever: phase2 loop with idle sleep
  python dump_all_players.py --discover-only  # used by the discover.timer
  python dump_all_players.py --rediscover     # one-shot but rescan for new IDs

Throttle handling:
  - Adaptive token bucket halves rate on 429.
  - Long-term cooldown: if rate has stayed below 30 req/s for >5 min,
    sleep 10 min, then reset to the initial rate.

Connection string comes from $DATABASE_URL.
"""

from __future__ import annotations

import os, sys, time, re, argparse, threading, queue, signal, socket
import json
import urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import db

# ── .env loading ──────────────────────────────────────────────
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
    f"https://apis.roblox.com/datastores/v1/universes/{UNIVERSE_ID}/standard-datastores"
)

MAX_RETRIES = 3
SOCKET_TIMEOUT = 30


# ─── Token bucket + long-term cooldown ──────────────────────────────────
class _TokenBucket:
    """All threads share one bucket. Halves rate on 429, slowly recovers."""

    def __init__(self, rate: float):
        self._initial_rate = float(rate)
        self._rate = float(rate)
        self._tokens = float(rate)
        self._last = time.monotonic()
        self._lock = threading.Lock()
        self._consecutive_ok = 0
        self._last_throttle = 0.0
        self._below_threshold_since: float | None = None

    @property
    def rate(self) -> float:
        with self._lock:
            return self._rate

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            time.sleep(min(wait, 0.5))

    def on_success(self) -> None:
        with self._lock:
            self._consecutive_ok += 1
            if self._consecutive_ok % 50 == 0:
                self._rate = min(self._rate * 1.1, self._initial_rate)

    def on_throttle(self) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_throttle < 2.0:
                return
            self._last_throttle = now
            new_rate = max(5.0, self._rate * 0.6)
            if new_rate < self._rate:
                self._rate = new_rate
                self._consecutive_ok = 0
                print(
                    f"\n  [rate limiter] 429 — throttled to {self._rate:.0f} req/s",
                    flush=True,
                )

    def reset_to_initial(self) -> None:
        with self._lock:
            self._rate = self._initial_rate
            self._tokens = self._initial_rate
            self._consecutive_ok = 0
            self._below_threshold_since = None
            print(
                f"  [rate limiter] reset to {self._initial_rate:.0f} req/s after cooldown",
                flush=True,
            )

    def needs_cooldown(self, threshold: float, sustained_seconds: float) -> bool:
        with self._lock:
            now = time.monotonic()
            if self._rate < threshold:
                if self._below_threshold_since is None:
                    self._below_threshold_since = now
                return (now - self._below_threshold_since) >= sustained_seconds
            self._below_threshold_since = None
            return False


_bucket: _TokenBucket | None = None


# ─── Shutdown ───────────────────────────────────────────────────────────
_shutdown = threading.Event()


def _install_sigint_handler():
    def _handler(_sig, _frame):
        if _shutdown.is_set():
            print("\n[interrupt] forcing exit", flush=True)
            os._exit(1)
        _shutdown.set()
        print(
            "\n[interrupt] stopping gracefully — finishing in-flight requests"
            " (Ctrl+C again to force quit)",
            flush=True,
        )

    signal.signal(signal.SIGINT, _handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handler)


# ─── Counters ───────────────────────────────────────────────────────────
_lock = threading.Lock()
_request_count = 0
_run_ok = 0
_run_empty = 0
_run_failed = 0
_run_done = 0
_start_time = 0.0


def inc_requests():
    global _request_count
    with _lock:
        _request_count += 1


def inc_result(kind: str):
    global _run_ok, _run_empty, _run_failed, _run_done
    with _lock:
        if kind == "ok":
            _run_ok += 1
        elif kind == "empty":
            _run_empty += 1
        else:
            _run_failed += 1
        _run_done += 1


# ─── HTTP helpers ───────────────────────────────────────────────────────
def api_get(url: str):
    for attempt in range(MAX_RETRIES):
        if _shutdown.is_set():
            return None
        _bucket.acquire()
        inc_requests()
        req = urllib.request.Request(url, headers={"x-api-key": API_KEY})
        try:
            with urllib.request.urlopen(req, timeout=SOCKET_TIMEOUT) as resp:
                _bucket.on_success()
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                _bucket.on_throttle()
                backoff = (2**attempt) * (0.5 + (time.monotonic() % 1.0))
                end = time.monotonic() + backoff
                while time.monotonic() < end and not _shutdown.is_set():
                    time.sleep(0.2)
                continue
            elif e.code == 404:
                _bucket.on_success()
                return None
            else:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2**attempt)
                    continue
                return None
        except (urllib.error.URLError, socket.timeout, TimeoutError):
            if attempt < MAX_RETRIES - 1:
                time.sleep(2**attempt)
                continue
            return None
    return None


def get_usernames_bulk(user_ids: list[int]) -> dict[int, tuple[str | None, str | None]]:
    results: dict[int, tuple[str | None, str | None]] = {}
    for i in range(0, len(user_ids), 100):
        if _shutdown.is_set():
            break
        batch = user_ids[i : i + 100]
        time.sleep(0.1)
        body = json.dumps({"userIds": batch, "excludeBannedUsers": False}).encode()
        req = urllib.request.Request(
            "https://users.roblox.com/v1/users",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=SOCKET_TIMEOUT) as r:
                data = json.loads(r.read().decode())
                for u in data.get("data", []):
                    results[u["id"]] = (u.get("name"), u.get("displayName"))
        except Exception:
            pass
    return results


# ─── DataStore helpers ─────────────────────────────────────────────────
def list_all_keys(ds_name: str) -> list[str]:
    encoded = urllib.request.quote(ds_name, safe="")
    keys, cursor = [], ""
    while not _shutdown.is_set():
        url = f"{BASE}/datastore/entries?datastoreName={encoded}&limit=100"
        if cursor:
            url += f"&cursor={cursor}"
        data = api_get(url)
        if not data:
            break
        keys.extend([k["key"] for k in data.get("keys", [])])
        cursor = data.get("nextPageCursor", "")
        if not cursor:
            break
    return keys


def get_entry(ds_name: str, key: str):
    encoded = urllib.request.quote(ds_name, safe="")
    return api_get(
        f"{BASE}/datastore/entries/entry?datastoreName={encoded}&entryKey={key}"
    )


def fetch_latest(ds_name: str):
    """Archery Duels stores numeric version keys (1, 2, 3, …) per player;
    the latest save is the highest key. (Ocean Quest used an ordered
    DataStore pointer; Archery doesn't, so we list + max directly.)"""
    keys = list_all_keys(ds_name)
    int_keys = [int(k) for k in keys if k.isdigit()]
    if int_keys:
        latest = max(int_keys)
        return get_entry(ds_name, str(latest)), latest
    return None, None


# ─── Cooldown watcher ──────────────────────────────────────────────────
def cooldown_watcher_loop(
    threshold: float = 30.0,
    sustained_seconds: float = 300.0,
    cooldown_seconds: float = 600.0,
):
    while not _shutdown.is_set():
        time.sleep(30)
        if _shutdown.is_set():
            break
        if _bucket and _bucket.needs_cooldown(threshold, sustained_seconds):
            print(
                f"\n  [cooldown] rate stuck below {threshold:.0f} req/s for "
                f"{sustained_seconds/60:.0f}m — sleeping {cooldown_seconds/60:.0f}m",
                flush=True,
            )
            end = time.monotonic() + cooldown_seconds
            while time.monotonic() < end and not _shutdown.is_set():
                time.sleep(2)
            if not _shutdown.is_set():
                _bucket.reset_to_initial()


# ─── Phase 1: Discovery ────────────────────────────────────────────────
def run_discovery() -> int:
    """Scan DataStores for DATA/{uid}; insert new IDs into Postgres."""
    print("\n[Discovery] Scanning DataStores for player IDs...")
    new_count = 0
    page_count = 0
    cursor = ""
    with db.connect() as conn:
        while not _shutdown.is_set():
            url = f"{BASE}?limit=100"
            if cursor:
                url += f"&cursor={cursor}"
            data = api_get(url)
            if not data:
                break
            page_count += 1
            for ds in data.get("datastores", []):
                m = re.match(r"^DATA/(\d{5,})$", ds["name"])
                if not m:
                    continue
                uid = int(m.group(1))
                if db.record_discovered(conn, uid):
                    new_count += 1
            conn.commit()
            cursor = data.get("nextPageCursor", "")
            if page_count % 10 == 0:
                print(
                    f"  [discovery] {page_count} pages scanned, "
                    f"{new_count} new IDs this run",
                    flush=True,
                )
            if not cursor:
                break

    print(f"  [discovery] done — {new_count} new IDs added", flush=True)
    return new_count


# ─── Phase 2: Fetch ────────────────────────────────────────────────────
def fetch_one(uid: int, username: str | None, display_name: str | None) -> str:
    """Returns 'ok' | 'empty' | 'failed' | 'shutdown'. Writes to Postgres."""
    try:
        combined, _key = fetch_latest(f"DATA/{uid}")
    except Exception:
        combined = None

    if isinstance(combined, dict) and combined:
        status = "ok"
    elif combined is None and _shutdown.is_set():
        return "shutdown"
    elif combined is None:
        status = "failed"
    else:
        status = "empty"

    try:
        with db.connect() as conn:
            db.record_fetch(conn, uid, status, username, display_name, combined)
    except Exception as e:
        print(f"  [db] write failed for {uid}: {e}", flush=True)
        return "failed"

    return status


def fetch_worker(uid: int, username: str | None, display_name: str | None, total: int):
    label = f"@{username}" if username else f"id:{uid}"
    try:
        status = fetch_one(uid, username, display_name)
    except Exception as e:
        status = "failed"
        print(f"  [worker] {label} crashed: {e}", flush=True)

    if status == "shutdown":
        return
    inc_result("ok" if status == "ok" else ("empty" if status == "empty" else "fail"))

    with _lock:
        elapsed = time.time() - _start_time
        rps = _request_count / elapsed if elapsed > 0 else 0
        print(
            f"  [{_run_done}/{total}] {label:30s} {status:6s} "
            f"({rps:.0f} req/s, bucket={_bucket.rate:.0f})",
            flush=True,
        )


def _process_uids(uids: list[int], unames: dict, workers: int, total: int) -> None:
    work_q: queue.Queue = queue.Queue()
    for uid in uids:
        work_q.put(uid)
    SENTINEL = object()
    for _ in range(workers):
        work_q.put(SENTINEL)

    def dump_worker():
        while True:
            try:
                item = work_q.get(timeout=0.5)
            except queue.Empty:
                if _shutdown.is_set():
                    break
                continue
            if item is SENTINEL:
                break
            if _shutdown.is_set():
                continue
            uname, dname = unames.get(item, (None, None))
            fetch_worker(item, uname, dname, total)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(dump_worker) for _ in range(workers)]
        for f in futs:
            try:
                f.result()
            except Exception as e:
                print(f"  [worker] crashed: {e}", flush=True)


def run_fetch_pass(
    refresh_after_hours: float | None,
    max_n: int,
    workers: int,
    batch_size: int = 0,
    batch_pause: float = 0.0,
) -> int:
    """One pass through pending players. Returns number of UIDs processed."""
    with db.connect() as conn:
        targets = db.select_targets(conn, refresh_after_hours, limit=max_n or 10_000_000)

    if not targets:
        return 0

    print(f"\n[Fetch] {len(targets)} players to fetch this pass", flush=True)
    print("  Resolving usernames...", flush=True)
    unames = get_usernames_bulk(targets)

    total = len(targets)

    if batch_size and batch_size > 0:
        for start in range(0, total, batch_size):
            if _shutdown.is_set():
                break
            chunk = targets[start : start + batch_size]
            print(
                f"\n  [batch] processing {len(chunk)} players "
                f"({start + 1}..{start + len(chunk)} of {total})",
                flush=True,
            )
            _process_uids(chunk, unames, workers, total)
            if (start + batch_size) < total and not _shutdown.is_set() and batch_pause > 0:
                print(f"  [batch] sleeping {batch_pause:.0f}s before next burst", flush=True)
                end = time.monotonic() + batch_pause
                while time.monotonic() < end and not _shutdown.is_set():
                    time.sleep(0.5)
    else:
        _process_uids(targets, unames, workers, total)

    return total


# ─── CLI ───────────────────────────────────────────────────────────────
def _print_summary(interrupted: bool):
    elapsed = time.time() - _start_time
    try:
        with db.connect() as conn:
            counts = db.count_by_status(conn)
            total = db.count_total(conn)
    except Exception as e:
        print(f"  [db] summary read failed: {e}", flush=True)
        counts, total = {}, -1

    print(f"\n{'=' * 60}")
    print(f"{'INTERRUPTED' if interrupted else 'Done'} in {elapsed:.0f}s "
          f"({_request_count} API requests this run)")
    print(f"  This run — ok: {_run_ok}  empty: {_run_empty}  failed: {_run_failed}")
    print(f"  All time:")
    for k in sorted(counts):
        print(f"    {k:11s} {counts[k]}")
    print(f"  Total known: {total}")
    if elapsed > 0 and _run_done > 0:
        print(
            f"  Speed:       {_run_done / elapsed:.1f} players/s, "
            f"{_request_count / elapsed:.1f} req/s"
        )


def main():
    global _bucket, _start_time

    parser = argparse.ArgumentParser(
        description="Roblox player save dumper (Postgres-backed, resumable)"
    )
    parser.add_argument("--daemon", action="store_true",
                        help="Run forever: keep fetching, idle-sleep when nothing pending")
    parser.add_argument("--discover-only", action="store_true",
                        help="Run only Phase 1 (DataStore scan) and exit")
    parser.add_argument("--rediscover", action="store_true",
                        help="In one-shot mode, also re-run discovery before fetching")
    parser.add_argument("--max", type=int, default=0,
                        help="Cap on players to fetch per pass (0 = unlimited)")
    parser.add_argument("--refresh-after", type=float, default=None,
                        help="Re-fetch players whose last_fetched_at is older than N hours")
    parser.add_argument("--workers", type=int, default=20,
                        help="Parallel fetch threads (default 20)")
    parser.add_argument("--rate", type=float, default=120.0,
                        help="Target requests/sec across all threads (default 120)")
    parser.add_argument("--idle-sleep", type=int, default=300,
                        help="Seconds to sleep between passes in --daemon when idle (default 300)")
    parser.add_argument("--batch-size", type=int, default=0,
                        help="Players per burst before pausing (0 = continuous, recommended: 100)")
    parser.add_argument("--batch-pause", type=float, default=0.0,
                        help="Seconds to sleep between bursts (used with --batch-size)")
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: ROBLOX_API_KEY is not set"); sys.exit(1)
    if not UNIVERSE_ID:
        print("ERROR: ROBLOX_UNIVERSE_ID is not set"); sys.exit(1)

    _bucket = _TokenBucket(args.rate)
    _install_sigint_handler()

    print("=" * 60)
    print("Archery Duels player dumper")
    print(f"Universe:   {UNIVERSE_ID}")
    print(f"Workers:    {args.workers}")
    print(f"Rate:       {args.rate:.0f} req/s")
    if args.batch_size:
        print(f"Batching:   {args.batch_size} players → {args.batch_pause:.0f}s pause")
    print(f"Mode:       "
          + ("--discover-only" if args.discover_only
             else "--daemon" if args.daemon
             else "one-shot"))
    print(f"Started:    {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    try:
        db.init_schema()
    except Exception as e:
        print(f"FATAL: cannot initialise schema: {e}")
        sys.exit(2)

    _start_time = time.time()

    cooldown_thread = threading.Thread(
        target=cooldown_watcher_loop, daemon=True, name="cooldown-watcher"
    )
    cooldown_thread.start()

    try:
        if args.discover_only:
            run_discovery()
        elif args.daemon:
            with db.connect() as conn:
                if db.count_total(conn) == 0:
                    run_discovery()
            while not _shutdown.is_set():
                processed = run_fetch_pass(
                    args.refresh_after, args.max, args.workers,
                    batch_size=args.batch_size, batch_pause=args.batch_pause,
                )
                if processed == 0:
                    print(
                        f"\n[Fetch] nothing pending — sleeping {args.idle_sleep}s",
                        flush=True,
                    )
                    end = time.monotonic() + args.idle_sleep
                    while time.monotonic() < end and not _shutdown.is_set():
                        time.sleep(2)
        else:
            with db.connect() as conn:
                known = db.count_total(conn)
            if args.rediscover or known == 0:
                run_discovery()
            run_fetch_pass(
                args.refresh_after, args.max, args.workers,
                batch_size=args.batch_size, batch_pause=args.batch_pause,
            )
    finally:
        _print_summary(_shutdown.is_set())

    if _shutdown.is_set():
        sys.exit(130)


if __name__ == "__main__":
    main()
