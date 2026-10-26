"""Time a full load of the real-crawl fixture into a throwaway database.

Usage: python scripts/bench_load.py            (uses TEST_DATABASE_URL; the database name must end in _test)
Drops and recreates the public schema of that database, applies migrations, then loads every item twice:
the first load is a fresh store, the second is an unchanged re-crawl (the normal daily case).
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import db  # noqa: E402
from migrate import migrate  # noqa: E402
from parser import parse_item  # noqa: E402

BATCH = 500


def reset(conn):
    conn.execute("DROP SCHEMA public CASCADE")
    conn.execute("CREATE SCHEMA public")
    migrate(conn)


def load(conn, store_id, pairs) -> tuple[float, int]:
    run_id = db.start_run(conn, store_id)
    t = time.perf_counter()
    for i in range(0, len(pairs), BATCH):
        with conn.transaction():
            db.save_items(conn, store_id, run_id, pairs[i:i + BATCH])
    elapsed = time.perf_counter() - t
    with conn.transaction():
        db.finish_run(conn, store_id, run_id, len(pairs), sum(1 for r, _ in pairs if r.problems))
    return elapsed, run_id


def main() -> int:
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url.rsplit("/", 1)[-1].endswith("_test"):
        print("TEST_DATABASE_URL must point at a database whose name ends in _test", file=sys.stderr)
        return 2
    with gzip.open(ROOT / "tests" / "trinity_yugioh_usf.json.gz", "rt", encoding="utf-8") as f:
        raws = json.load(f)
    pairs = [(parse_item(r), r) for r in raws]
    with psycopg.connect(url, autocommit=True) as conn:
        reset(conn)
        store_id = db.ensure_store(conn, "trinity", "Trinity Hobby", "https://trinityhobby.com")
        first, _ = load(conn, store_id, pairs)
        second, _ = load(conn, store_id, pairs)
        counts = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("listings", "cards", "variants", "price_history")}
    print(f"first load {first:.1f}s, unchanged re-load {second:.1f}s, {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
