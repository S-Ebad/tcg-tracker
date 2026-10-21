"""Apply numbered SQL migrations (migrations/NNNN_name.sql) in order, each once, each in its own transaction.

Usage: python migrate.py            (uses DATABASE_URL)
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
NAME_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[tuple[int, Path]]:
    """Return (version, path) sorted by version. Fails loudly on bad names, duplicates or gaps."""
    found = []
    for p in directory.iterdir():
        if p.suffix != ".sql":
            continue
        m = NAME_RE.match(p.name)
        if not m:
            raise ValueError(f"bad migration file name: {p.name} (expected NNNN_lower_snake.sql)")
        found.append((int(m.group(1)), p))
    found.sort()
    versions = [v for v, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise ValueError(f"migration versions must be 1..N with no gaps or duplicates, got {versions}")
    return found


def migrate(conn) -> list[int]:
    """Apply pending migrations. Returns the versions applied."""
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                        version integer PRIMARY KEY, name text NOT NULL,
                        applied_at timestamptz NOT NULL DEFAULT now())""")
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for version, path in migration_files():
        if version in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (version, name) VALUES (%s, %s)", (version, path.name))
        applied.append(version)
    return applied


def main() -> int:
    import psycopg

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    with psycopg.connect(url, autocommit=True) as conn:
        applied = migrate(conn)
    print(f"applied: {applied or 'nothing, up to date'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
