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


def crawl(tmp_path, scenario="ok", database_url="", extra=(), spider="trinity"):
    log, requests = tmp_path / f"{spider}-{scenario}.log", tmp_path / f"{spider}-{scenario}.requests"
    # never let a test crawl reach real alert channels: drop every ALERT_* / SMTP_* setting (incl. per-store webhooks)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("ALERT_", "SMTP_"))} | {
        "PYTHONPATH": os.pathsep.join([str(ROOT / "tests"), str(ROOT)]),
        "TCG_CONTACT_EMAIL": "test@example.com", "DATABASE_URL": database_url,
        "MOCK_SCENARIO": scenario, "MOCK_REQUEST_LOG": str(requests),
    }
    cmd = [sys.executable, "-m", "scrapy", "crawl", spider,
           "-s", f"DOWNLOADER_MIDDLEWARES={json.dumps(MIDDLEWARES)}",
           "-s", "DOWNLOAD_DELAY=0", "-s", "AUTOTHROTTLE_ENABLED=False", "-s", f"LOG_FILE={log}", *extra]
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    text = log.read_text(encoding="utf-8") if log.exists() else proc.stderr
    urls = requests.read_text(encoding="utf-8").split() if requests.exists() else []
    return proc.returncode, text, urls


def test_crawls_never_get_real_alert_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ALERT_DISCORD_WEBHOOK_URL_401GAMES", "https://discord.test/should-not-be-used")
    seen = {}

    def fake_run(cmd, cwd, env, **kw):
        seen.update(env)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    crawl(tmp_path, spider="401games")
    assert not [k for k in seen if k.upper().startswith(("ALERT_", "SMTP_"))]


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


# --- 401 Games (Fast Simon) ---------------------------------------------------------------------------------------

def fixture401_count():
    import gzip

    with gzip.open(ROOT / "tests" / "games401_fastsimon.json.gz", "rt", encoding="utf-8") as f:
        return len(json.load(f))


@needs_db
def test_401_full_crawl_then_cached_run(tmp_path, test_db):
    n = fixture401_count()
    code, log, urls = crawl(tmp_path, database_url=test_db, spider="401games")
    assert code == 0, log[-2000:]
    status, seen, alerts = query("SELECT status, items_seen, alerts FROM scrape_runs")[0]
    assert (status, seen, alerts) == ("ok", n, [])
    assert query("SELECT count(*) FROM listings")[0][0] == n
    assert query("SELECT count(*) FROM variants WHERE quantity IS NOT NULL")[0][0] == 0  # 401 has no quantities
    assert any("store.401games.ca/collections/yugioh-singles" in u for u in urls)
    assert sum("api.fastsimon.com" in u for u in urls) == -(-n // 250)

    second = tmp_path / "second"
    second.mkdir()
    code, log, urls = crawl(second, database_url=test_db, spider="401games")
    assert code == 0, log[-2000:]
    assert not any("store.401games.ca" in u for u in urls if "robots.txt" not in u)
    assert query("SELECT status FROM scrape_runs ORDER BY id") == [("ok",), ("ok",)]


@needs_db
def test_401_truncated_api_fails_and_marks_nothing_out(tmp_path, test_db):
    code, log, _ = crawl(tmp_path, database_url=test_db, spider="401games")
    assert code == 0, log[-2000:]
    bad = tmp_path / "bad"
    bad.mkdir()
    crawl(bad, scenario="truncated", database_url=test_db, spider="401games")
    status, notes = query("SELECT status, notes FROM scrape_runs ORDER BY id DESC LIMIT 1")[0]
    assert status == "failed" and "empty_page" in notes
    assert query("SELECT count(*) FROM listings WHERE NOT in_stock") == [(0,)]


@needs_db
def test_both_stores_share_card_keys(tmp_path, test_db):
    for spider in ("trinity", "401games"):
        d = tmp_path / spider
        d.mkdir()
        code, log, _ = crawl(d, database_url=test_db, spider=spider)
        assert code == 0, log[-2000:]
    shared = query("""SELECT count(*) FROM (SELECT l.card_key FROM listings l JOIN stores s ON s.id = l.store_id
                      WHERE l.card_key IS NOT NULL GROUP BY l.card_key HAVING count(DISTINCT s.slug) = 2) x""")[0][0]
    assert shared > 1000, f"only {shared} card keys appear at both stores"
    stores = {r[0] for r in query("SELECT DISTINCT store FROM current_best_prices")}
    assert stores == {"trinity", "401games"}


# --- Fusion Gaming (Shopify products.json) -------------------------------------------------------------------------

@needs_db
def test_fusion_full_crawl_and_truncated_feed(tmp_path, test_db):
    code, log, urls = crawl(tmp_path, database_url=test_db, spider="fusion",
                            extra=("-s", "DOWNLOAD_DELAY=0"))
    assert code == 0, log[-2000:]
    status, seen, alerts = query("SELECT status, items_seen, alerts FROM scrape_runs")[0]
    assert (status, seen, alerts) == ("ok", 13848, [])
    assert query("SELECT count(*) FROM listings WHERE card_key IS NULL")[0][0] == 11
    assert sum("products.json" in u for u in urls) == 57  # 56 pages with products + the empty one that ends it

    bad = tmp_path / "bad"
    bad.mkdir()
    crawl(bad, scenario="truncated", database_url=test_db, spider="fusion", extra=("-s", "DOWNLOAD_DELAY=0"))
    status, notes = query("SELECT status, notes FROM scrape_runs ORDER BY id DESC LIMIT 1")[0]
    assert status == "failed" and "differs from data.total" in notes
    assert query("SELECT count(*) FROM listings WHERE NOT in_stock") == [(0,)]


@needs_db
def test_three_stores_line_up(tmp_path, test_db):
    for spider in ("trinity", "401games", "fusion"):
        d = tmp_path / spider
        d.mkdir()
        code, log, _ = crawl(d, database_url=test_db, spider=spider)
        assert code == 0, log[-2000:]
    at_all_three = query("""SELECT count(*) FROM (SELECT l.card_key FROM listings l JOIN stores s ON s.id = l.store_id
                            WHERE l.card_key IS NOT NULL GROUP BY l.card_key HAVING count(DISTINCT s.slug) = 3) x""")
    assert at_all_three[0][0] == 3723
    assert {r[0] for r in query("SELECT DISTINCT store FROM current_best_prices")} == {"trinity", "401games", "fusion"}
