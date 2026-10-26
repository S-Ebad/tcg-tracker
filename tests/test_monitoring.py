import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from scrapy.utils.test import get_crawler

import tcg_tracker.monitoring as mon
from parser import parse_item
from tcg_tracker.monitoring import Alert, FieldStats, evaluate, format_message, http_error_rate
from tcg_tracker.spiders.trinity import TrinitySpider

T = {"min_item_ratio": 0.9, "max_problem_rate": 0.02, "null_rate_jump": 0.02, "max_http_error_rate": 0.05}
BASE_FIELDS = {"card_key": 0.0057, "set_name": 0.0007, "variant.sku": 0.0491, "n_listings": 11793}
OK_STATS = {"downloader/response_status_count/200": 62, "trinity/api_key_source": "cached"}


def run(**kw):
    return {"status": "ok", "notes": None, "items_seen": 11763, "items_with_problems": 78,
            "field_stats": BASE_FIELDS} | kw


PREV = {"items_seen": 11793, "field_stats": BASE_FIELDS}


def checks(alerts):
    return [a.check for a in alerts]


def test_healthy_run_has_no_alerts():
    assert evaluate(run(), PREV, OK_STATS, T) == []


def test_first_run_without_history_only_checks_itself():
    assert evaluate(run(), None, OK_STATS, T) == []


@pytest.mark.parametrize("status", ["failed", "suspect"])
def test_failed_or_suspect_run_is_critical(status):
    alerts = evaluate(run(status=status, notes="paging stopped early"), PREV, OK_STATS, T)
    assert alerts[0] == Alert("critical", f"run_{status}", "paging stopped early")


def test_item_count_below_90_percent_of_last_good_run():
    alerts = evaluate(run(status="suspect", items_seen=10000), PREV, OK_STATS, T)
    assert "item_count_drop" in checks(alerts) and "85%" in str(alerts[1])


def test_parse_problem_rate_above_2_percent():
    assert checks(evaluate(run(items_with_problems=300), PREV, OK_STATS, T)) == ["parse_problem_rate"]
    assert evaluate(run(items_with_problems=200), PREV, OK_STATS, T) == []  # 1.7%


def test_null_rate_jump_against_last_good_run():
    alerts = evaluate(run(field_stats=BASE_FIELDS | {"set_name": 0.25}), PREV, OK_STATS, T)
    assert checks(alerts) == ["null_rate_jump"] and "set_name is NULL on 25.0% (was 0.1%" in str(alerts[0])
    small = BASE_FIELDS | {"variant.sku": 0.06}  # +1.1 points: normal drift
    assert evaluate(run(field_stats=small), PREV, OK_STATS, T) == []


def test_http_error_rate_from_real_runs():
    run1 = {"downloader/response_status_count/200": 62, "downloader/response_status_count/429": 2}
    run2 = {"downloader/response_status_count/200": 61, "downloader/response_status_count/429": 4}
    assert http_error_rate(run1) == (2 / 64, 2, 64)
    assert checks(evaluate(run(), PREV, run1, T)) == []
    assert checks(evaluate(run(), PREV, run2, T)) == ["http_error_rate"]


def test_download_exceptions_count_as_http_errors():
    stats = {"downloader/response_status_count/200": 10, "downloader/exception_count": 2}
    assert http_error_rate(stats) == (2 / 12, 2, 12)


@pytest.mark.parametrize("stats,check", [
    ({"tcg/parse_exceptions": 3}, "parser_crash"),
    ({"trinity/api_key_source": "fallback"}, "api_key_fallback"),
    ({"trinity/api_key_source": "cached_stale"}, "api_key_stale"),
    ({"trinity/api_key_rejected": 1}, "api_key_rejected"),
])
def test_spider_stat_alerts(stats, check):
    assert checks(evaluate(run(), PREV, stats, T)) == [check]


def test_run_never_recorded_is_critical():
    alerts = evaluate(None, None, {"finish_reason": "shutdown"}, T)
    assert alerts[0].level == "critical" and alerts[0].check == "run_not_recorded"


def test_field_stats_on_real_crawl_match_measured_baseline(real_crawl):
    fs = FieldStats()
    for r in real_crawl:
        fs.add(parse_item(r))
    d = fs.as_dict()
    assert (d["n_listings"], d["n_variants"]) == (11793, 62710)
    assert d["card_key"] == pytest.approx(2 / 11793, abs=1e-5) and d["rarity"] == pytest.approx(1 / 11793, abs=1e-5)
    assert d["variant.sku"] == pytest.approx(0.0491, abs=1e-4)
    assert d["set_code"] == 0.0 and "art_label" not in d


def test_store_webhook_overrides_the_default_only_for_that_store():
    env = {"ALERT_DISCORD_WEBHOOK_URL_401GAMES": "https://discord.test/401"}
    assert mon.store_webhook_var("401games") == "ALERT_DISCORD_WEBHOOK_URL_401GAMES"
    assert mon.discord_url_for("401games", "https://discord.test/default", env) == "https://discord.test/401"
    assert mon.discord_url_for("trinity", "https://discord.test/default", env) == "https://discord.test/default"
    assert mon.discord_url_for(None, "https://discord.test/default", env) == "https://discord.test/default"
    assert mon.discord_url_for("401games", "", {}) == ""


def test_monitor_sends_401_alerts_through_its_own_webhook(monkeypatch):
    from tcg_tracker.spiders.games401 import Games401Spider

    sent = []
    monkeypatch.setattr(mon, "send_discord", lambda url, text: sent.append(url))
    monkeypatch.setenv("ALERT_DISCORD_WEBHOOK_URL_401GAMES", "https://discord.test/401")
    crawler = get_crawler(Games401Spider, T | {"ALERT_DISCORD_WEBHOOK_URL": "https://discord.test/default",
                                               "MONITOR_MIN_ITEM_RATIO": 0.9, "MONITOR_MAX_PROBLEM_RATE": 0.02,
                                               "MONITOR_NULL_RATE_JUMP": 0.02, "MONITOR_MAX_HTTP_ERROR_RATE": 0.05})
    crawler.spider = Games401Spider.from_crawler(crawler)
    mon.RunMonitor.from_crawler(crawler)._notify("x", [])
    assert sent == ["https://discord.test/401"]


def test_message_names_the_worst_level_and_every_alert():
    text = format_message("trinity", 12, [Alert("warning", "a", "x"), Alert("critical", "b", "y")])
    assert text.splitlines() == ["tcg-tracker CRITICAL: trinity run 12", "- [warning] a: x", "- [critical] b: y"]


def test_discord_webhook_posts_json():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.headers["Content-Type"], json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    mon.send_discord(f"http://127.0.0.1:{server.server_port}/webhook", "hello")
    server.server_close()
    assert received == [("application/json", {"content": "hello"})]


def test_email_uses_starttls_and_login(monkeypatch):
    log = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            log.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def starttls(self):
            log.append(("starttls",))

        def login(self, user, password):
            log.append(("login", user))

        def send_message(self, msg):
            log.append(("send", msg["To"], msg["Subject"]))

    monkeypatch.setattr(mon.smtplib, "SMTP", FakeSMTP)
    cfg = {"to": "me@example.com", "from": "bot@example.com", "host": "smtp.example.com", "port": 587,
           "user": "bot", "password": "x", "starttls": True}
    mon.send_email(cfg, "subject line", "body")
    assert log == [("connect", "smtp.example.com", 587), ("starttls",), ("login", "bot"),
                   ("send", "me@example.com", "subject line")]


# --- the extension against a real database ------------------------------------------------------------------------

URL = os.environ.get("TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not URL.rsplit("/", 1)[-1].endswith("_test"),
                              reason="TEST_DATABASE_URL (a *_test database) not set")


@needs_db
def test_monitor_compares_with_last_good_run_stores_alerts_and_notifies(monkeypatch):
    import psycopg

    import db
    from migrate import migrate

    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        migrate(conn)
        store = db.ensure_store(conn, "trinity", "Trinity Hobby", "https://trinityhobby.com")
        good = db.start_run(conn, store)
        db.finish_run(conn, store, good, 11793, 77, field_stats=BASE_FIELDS)
        bad = db.start_run(conn, store)
        db.finish_run(conn, store, bad, 9000, 77, field_stats=BASE_FIELDS | {"card_key": 0.3})

    sent = []
    monkeypatch.setattr(mon, "send_discord", lambda url, text: sent.append((url, text)))
    crawler = get_crawler(TrinitySpider, T | {"DATABASE_URL": URL, "ALERT_DISCORD_WEBHOOK_URL": "https://discord.test/x",
                                              "MONITOR_MIN_ITEM_RATIO": 0.9, "MONITOR_MAX_PROBLEM_RATE": 0.02,
                                              "MONITOR_NULL_RATE_JUMP": 0.02, "MONITOR_MAX_HTTP_ERROR_RATE": 0.05})
    ext = mon.RunMonitor.from_crawler(crawler)
    ext.on_run_finished(run_id=bad, store_id=store, status="suspect", notes="9000 items vs 11793 last good run",
                        items_seen=9000, items_with_problems=77, field_stats=BASE_FIELDS | {"card_key": 0.3})
    ext.on_engine_stopped()

    assert checks(ext.sent) == ["run_suspect", "item_count_drop", "null_rate_jump"]
    with psycopg.connect(URL) as conn:
        stored = conn.execute("SELECT alerts FROM scrape_runs WHERE id=%s", (bad,)).fetchone()[0]
    assert len(stored) == 3 and stored[0].startswith("[critical] run_suspect")
    assert sent and sent[0][0] == "https://discord.test/x" and "CRITICAL" in sent[0][1]
