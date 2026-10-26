"""Entry point for scheduled jobs (Windows Task Scheduler or cron).

  python scripts/scheduled.py crawl [--no-crawl]   start local Postgres if needed, migrate, crawl every store
                                                    spider, then back up the database
  python scripts/scheduled.py check-freshness      alert if the newest good run is older than FRESHNESS_MAX_HOURS
  python scripts/scheduled.py test-alert           send a test message to the configured alert channels

Reads .env from the project root. Logs go to logs/ (git-ignored). Problems that happen before Scrapy's own
monitoring can run (database won't start, crawl process crashes, backup fails) are alerted from here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SPIDERS = ["trinity", "401games", "fusion"]
PG_BIN = ROOT / ".tools" / "pg" / "Library" / "bin"   # conda-forge Postgres; skipped when absent (Docker)
PG_DATA = ROOT / ".tools" / "pgdata"
LOG_DIR = ROOT / "logs"
KEEP_LOGS = 60
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flashing up when run by Task Scheduler

log = logging.getLogger("scheduled")


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader: KEY=value lines; values already in the environment win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2).strip()


def setup_logging(job: str) -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    logs = sorted(LOG_DIR.glob("*.log"))
    for old in logs[:-KEEP_LOGS]:
        old.unlink()
    path = LOG_DIR / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{job}.log"
    handlers: list[logging.Handler] = [logging.FileHandler(path, encoding="utf-8")]
    if sys.stderr:  # None under pythonw.exe (Task Scheduler)
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    return path


def alert(text: str, store: str | None = None) -> None:
    """Send to Discord / email if configured (same settings as the Scrapy monitor). With `store`, Discord uses that
    store's own webhook (ALERT_DISCORD_WEBHOOK_URL_<SLUG>) when it has one."""
    from tcg_tracker import monitoring

    log.error(text)
    sent = False
    discord_url = monitoring.discord_url_for(store, os.environ.get("ALERT_DISCORD_WEBHOOK_URL", ""))
    if discord_url:
        try:
            monitoring.send_discord(discord_url, text)
            sent = True
        except Exception as e:
            log.error("Discord alert failed: %r", e)
    if os.environ.get("ALERT_EMAIL_TO"):
        cfg = {"to": os.environ["ALERT_EMAIL_TO"], "from": os.environ.get("ALERT_EMAIL_FROM", ""),
               "host": os.environ.get("SMTP_HOST", ""), "port": int(os.environ.get("SMTP_PORT", "587")),
               "user": os.environ.get("SMTP_USER", ""), "password": os.environ.get("SMTP_PASSWORD", ""),
               "starttls": os.environ.get("SMTP_STARTTLS", "1") != "0"}
        try:
            monitoring.send_email(cfg, text.splitlines()[0], text)
            sent = True
        except Exception as e:
            log.error("email alert failed: %r", e)
    if not sent:
        log.warning("no alert channel delivered this (ALERT_DISCORD_WEBHOOK_URL / ALERT_EMAIL_TO)")


def db_params() -> dict:
    """libpq connection pieces from DATABASE_URL; the password goes in PGPASSWORD, never on a command line."""
    m = re.match(r"^postgresql://([^:]+):([^@]+)@([^:/]+)(?::(\d+))?/(\w+)$", os.environ.get("DATABASE_URL", ""))
    if not m:
        raise RuntimeError("DATABASE_URL is missing or not postgresql://user:pass@host[:port]/db")
    user, password, host, port, name = m.groups()
    return {"user": user, "password": password, "host": host, "port": port or "5432", "dbname": name}


def ensure_postgres() -> None:
    """Start the local conda-forge server if this project uses one and it isn't running."""
    pg_ctl = PG_BIN / "pg_ctl.exe"
    if not pg_ctl.exists() or not PG_DATA.exists():
        return  # Docker or another server: not ours to start
    status = subprocess.run([pg_ctl, "-D", PG_DATA, "status"], capture_output=True, text=True,
                            creationflags=NO_WINDOW)
    if status.returncode == 0:
        return
    log.info("starting local Postgres")
    started = subprocess.run([pg_ctl, "-D", PG_DATA, "-l", ROOT / ".tools" / "postgres.log", "-w", "start"],
                             capture_output=True, text=True, creationflags=NO_WINDOW)
    if started.returncode != 0:
        raise RuntimeError(f"pg_ctl start failed: {started.stdout.strip()} {started.stderr.strip()}")


def migrate() -> None:
    import psycopg

    from migrate import migrate as apply

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        applied = apply(conn)
    if applied:
        log.info("applied migrations %s", applied)


def run_spider(name: str) -> int:
    log_file = LOG_DIR / f"{dt.datetime.now():%Y%m%d-%H%M%S}-scrapy-{name}.log"
    proc = subprocess.run([sys.executable, "-m", "scrapy", "crawl", name, "-s", f"LOG_FILE={log_file}"],
                          cwd=ROOT, env=os.environ.copy(), creationflags=NO_WINDOW)
    log.info("spider %s exited with %s (log: %s)", name, proc.returncode, log_file.name)
    return proc.returncode


def backup_dir() -> Path:
    # Windows environment names are case-insensitive: this is the OneDrive folder when OneDrive is set up
    default = Path(os.environ.get("ONEDRIVE") or Path.home()) / "tcg-tracker-backups"
    return Path(os.environ.get("BACKUP_DIR") or default)


def backup() -> Path:
    """pg_dump in custom format, verified with pg_restore --list, keeping the newest BACKUP_KEEP files."""
    p = db_params()
    pg_dump = PG_BIN / "pg_dump.exe" if (PG_BIN / "pg_dump.exe").exists() else "pg_dump"
    pg_restore = PG_BIN / "pg_restore.exe" if (PG_BIN / "pg_restore.exe").exists() else "pg_restore"
    target_dir = backup_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"tcg-{dt.datetime.now():%Y%m%d-%H%M%S}.dump"
    env = os.environ | {"PGPASSWORD": p["password"]}
    dump = subprocess.run([pg_dump, "-h", p["host"], "-p", p["port"], "-U", p["user"], "-d", p["dbname"],
                           "-Fc", "-Z", "6", "-f", target], env=env, capture_output=True, text=True,
                          creationflags=NO_WINDOW)
    if dump.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {dump.stderr.strip()}")
    check = subprocess.run([pg_restore, "--list", target], capture_output=True, text=True, creationflags=NO_WINDOW)
    if check.returncode != 0 or "TABLE DATA public price_history" not in check.stdout:
        raise RuntimeError(f"backup {target.name} failed verification: {check.stderr.strip()[:300]}")
    keep = int(os.environ.get("BACKUP_KEEP", "14"))
    for old in sorted(target_dir.glob("tcg-*.dump"))[:-keep]:
        old.unlink()
    log.info("backup written: %s (%.1f MB)", target, target.stat().st_size / 1e6)
    return target


def job_crawl(no_crawl: bool) -> int:
    try:
        ensure_postgres()
        migrate()
    except Exception as e:
        alert(f"tcg-tracker CRITICAL: scheduled crawl could not start: {e}")
        return 2
    failed = []
    if not no_crawl:
        failed = [s for s in SPIDERS if run_spider(s) != 0]
        if failed:
            # run quality is alerted by the in-crawl monitor; a non-zero exit means the process itself broke
            alert(f"tcg-tracker CRITICAL: scrapy process failed for {', '.join(failed)}; see logs/")
    try:
        backup()
    except Exception as e:
        alert(f"tcg-tracker WARNING: database backup failed: {e}")
        return 3
    return 1 if failed else 0


def newest_ok_run_age_hours() -> dict[str, float | None]:
    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(
            """SELECT s.slug, extract(epoch FROM now() - max(r.finished_at)) / 3600
               FROM stores s LEFT JOIN scrape_runs r ON r.store_id = s.id AND r.status = 'ok'
               GROUP BY s.slug""").fetchall()
    return {slug: (float(age) if age is not None else None) for slug, age in rows}


def job_check_freshness() -> int:
    limit = float(os.environ.get("FRESHNESS_MAX_HOURS", "26"))
    try:
        ensure_postgres()
        ages = newest_ok_run_age_hours()
    except Exception as e:
        alert(f"tcg-tracker CRITICAL: freshness check could not read the database: {e}")
        return 2
    stale = {s: a for s, a in ages.items() if a is None or a > limit}
    for s, a in ages.items():
        log.info("store %s: newest good run %s", s, "never" if a is None else f"{a:.1f} h ago")
    if stale:
        detail = ", ".join(f"{s} ({'never' if a is None else f'{a:.0f} h ago'})" for s, a in stale.items())
        alert(f"tcg-tracker CRITICAL: no good crawl in the last {limit:.0f} h for: {detail}. "
              "Is the scheduled task running and the PC on?")
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="job", required=True)
    c = sub.add_parser("crawl")
    c.add_argument("--no-crawl", action="store_true", help="only start the database, migrate and back up")
    sub.add_parser("check-freshness")
    t = sub.add_parser("test-alert")
    t.add_argument("--store", help="send through this store's own webhook, e.g. 401games")
    args = ap.parse_args(argv)
    load_env()
    path = setup_logging(args.job)
    log.info("job %s started (log %s)", args.job, path.name)
    if args.job == "crawl":
        code = job_crawl(args.no_crawl)
    elif args.job == "check-freshness":
        code = job_check_freshness()
    else:
        who = f" for {args.store}" if args.store else ""
        alert(f"tcg-tracker test alert{who}: if you can read this, alerts work.", store=args.store)
        code = 0
    log.info("job %s finished with exit code %s", args.job, code)
    return code


if __name__ == "__main__":
    sys.exit(main())
