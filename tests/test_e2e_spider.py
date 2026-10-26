"""End-to-end: a real `scrapy crawl trinity` in a subprocess, every request answered by tests/mock_site.py.

The subprocess keeps Twisted's reactor out of the pytest process. The database scenarios need TEST_DATABASE_URL.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
URL = os.environ.get("TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not URL.rsplit("/", 1)[-1].endswith("_test"),
                              reason="TEST_DATABASE_URL (a *_test database) not set")

MIDDLEWARES = {"mock_site.SavedSiteMiddleware": 1, "tcg_tracker.middlewares.RetryAfterMiddleware": 560}


def crawl(tmp_path, scenario="ok", database_url="", extra=()):
    log, requests = tmp_path / f"{scenario}.log", tmp_path / f"{scenario}.requests"
    env = os.environ | {
        "PYTHONPATH": os.pathsep.join([str(ROOT / "tests"), str(ROOT)]),
        "TCG_CONTACT_EMAIL": "test@example.com", "DATABASE_URL": database_url,
        "MOCK_SCENARIO": scenario, "MOCK_REQUEST_LOG": str(requests),
        "ALERT_DISCORD_WEBHOOK_URL": "", "ALERT_EMAIL_TO": "",
    }
    cmd = [sys.executable, "-m", "scrapy", "crawl", "trinity",
           "-s", f"DOWNLOADER_MIDDLEWARES={json.dumps(MIDDLEWARES)}",
           "-s", "DOWNLOAD_DELAY=0", "-s", "AUTOTHROTTLE_ENABLED=False", "-s", f"LOG_FILE={log}", *extra]
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    text = log.read_text(encoding="utf-8") if log.exists() else proc.stderr
    urls = requests.read_text(encoding="utf-8").split() if requests.exists() else []
    return proc.returncode, text, urls


def test_full_crawl_to_feed_without_database(tmp_path):
    out = tmp_path / "items.jsonl"
    code, log, urls = crawl(tmp_path, extra=("-s", "ITEM_PIPELINES={}", "-O", str(out)))
    assert code == 0, log[-2000:]
    ids = [json.loads(line)["raw"]["id"] for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(ids) == len(set(ids)) == 11793
    api = [u for u in urls if "/search?" in u]
    assert len(api) == 59 and "'trinity/api_key_source': 'discovered'" in log


@pytest.fixture
def test_db():
    """Fresh schema in the test database. Returns the URL wrapped so a failing test can't print the password."""
    import psycopg

    from migrate import migrate

    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        migrate(conn)
    return _Secret(URL)


class _Secret(str):
    def __repr__(self):
        return "'<TEST_DATABASE_URL>'"


def query(sql):
    import psycopg

    with psycopg.connect(URL) as conn:
        return conn.execute(sql).fetchall()


@needs_db
def test_full_crawl_into_postgres_then_second_run_uses_cached_key(tmp_path, test_db):
    code, log, urls = crawl(tmp_path, database_url=test_db)
    assert code == 0, log[-2000:]
    assert query("SELECT status, items_seen, alerts FROM scrape_runs") == [("ok", 11793, [])]
    assert query("SELECT (SELECT count(*) FROM listings), (SELECT count(*) FROM cards),"
                 " (SELECT count(*) FROM variants)") == [(11793, 11778, 62710)]
    assert query("SELECT value->>'api_key' FROM store_config") == [("04572457-312a-4a58-b5e9-6aff246ee39f",)]
    assert any("trinityhobby.com/collections" in u for u in urls)

    second = tmp_path / "second"
    second.mkdir()
    code, log, urls = crawl(second, database_url=test_db)
    assert code == 0, log[-2000:]
    assert not any("trinityhobby.com" in u for u in urls), "a cached run must not touch the store site"
    assert query("SELECT status FROM scrape_runs ORDER BY id") == [("ok",), ("ok",)]
    assert query("SELECT count(*) FROM price_history")[0][0] == 62710  # nothing changed, no new history


@needs_db
def test_truncated_api_fails_the_run_and_marks_nothing_out(tmp_path, test_db):
    code, log, _ = crawl(tmp_path, database_url=test_db)
    assert code == 0, log[-2000:]
    bad = tmp_path / "bad"
    bad.mkdir()
    crawl(bad, scenario="truncated", database_url=test_db)
    status, notes, alerts = query("SELECT status, notes, alerts FROM scrape_runs ORDER BY id DESC LIMIT 1")[0]
    assert status == "failed" and "empty_page" in notes
    assert alerts[0].startswith("[critical] run_failed")
    assert query("SELECT count(*) FROM listings WHERE NOT in_stock") == [(0,)]


@needs_db
def test_rate_limited_store_page_falls_back_and_alerts(tmp_path, test_db):
    code, log, urls = crawl(tmp_path, scenario="store_429", database_url=test_db)
    assert code == 0, log[-2000:]
    assert sum("trinityhobby.com/collections" in u for u in urls) == 4  # first try + 3 retries
    status, alerts = query("SELECT status, alerts FROM scrape_runs")[0]
    assert status == "ok"
    # 4 x 429 out of ~65 downloads is above the 5% limit, so both alerts are expected
    assert sorted(a.split(":")[0] for a in alerts) == ["[warning] api_key_fallback", "[warning] http_error_rate"]
