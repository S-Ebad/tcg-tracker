"""Run monitoring: checks after every crawl, alerts to the log, the scrape_runs row, Discord and/or email.

Checks (thresholds are settings, see settings.py):
  - run status is not 'ok' (failed / suspect), or the pipeline never finished the run
  - items_seen below MONITOR_MIN_ITEM_RATIO of the last good run
  - share of items with parse problems above MONITOR_MAX_PROBLEM_RATE
  - any field's NULL share up by more than MONITOR_NULL_RATE_JUMP versus the last good run
  - HTTP error rate (non-2xx responses + download exceptions) above MONITOR_MAX_HTTP_ERROR_RATE
  - parser crashes, API key fallbacks, API key rejections

Why not Spidermon: these checks need the database's run history (last good run, its null rates), which a small
extension reads directly; Spidermon's item-validation features aren't needed since parsing is done by parser.py.
"""
from __future__ import annotations

import json
import logging
import smtplib
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage

from scrapy import signals
from scrapy.exceptions import NotConfigured

logger = logging.getLogger(__name__)

# Sent by the pipeline once finish_run has committed: kwargs run_id, store_id, status, notes, items_seen,
# items_with_problems, field_stats.
run_finished = object()

# Fields whose NULL share is tracked. art_label is left out: NULL is its normal state (96% of listings).
LISTING_FIELDS = ("card_key", "set_code", "card_number", "set_name", "rarity")
VARIANT_FIELDS = ("sku", "condition", "edition")


@dataclass(frozen=True)
class Alert:
    level: str      # "critical" or "warning"
    check: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.check}: {self.message}"


class FieldStats:
    """Counts NULLs per field over a run's parsed records (CardRec / VariantRec)."""

    def __init__(self):
        self.n_listings = self.n_variants = 0
        self.nulls = {f: 0 for f in LISTING_FIELDS} | {f"variant.{f}": 0 for f in VARIANT_FIELDS}

    def add(self, rec) -> None:
        self.n_listings += 1
        for f in LISTING_FIELDS:
            self.nulls[f] += getattr(rec, f) is None
        for v in rec.variants:
            self.n_variants += 1
            for f in VARIANT_FIELDS:
                self.nulls[f"variant.{f}"] += getattr(v, f) is None

    def as_dict(self) -> dict:
        rates = {}
        for k, n in self.nulls.items():
            denom = self.n_variants if k.startswith("variant.") else self.n_listings
            rates[k] = round(n / denom, 5) if denom else None
        return rates | {"n_listings": self.n_listings, "n_variants": self.n_variants}


def http_error_rate(stats: dict) -> tuple[float, int, int]:
    """(rate, errors, attempts) over all downloads: non-2xx/3xx responses plus exceptions (timeouts, DNS...)."""
    prefix = "downloader/response_status_count/"
    responses = {int(k[len(prefix):]): v for k, v in stats.items() if k.startswith(prefix)}
    errors = sum(v for code, v in responses.items() if code >= 400) + stats.get("downloader/exception_count", 0)
    attempts = sum(responses.values()) + stats.get("downloader/exception_count", 0)
    return (errors / attempts if attempts else 0.0), errors, attempts


def evaluate(run: dict | None, prev_ok: dict | None, stats: dict, t: dict) -> list[Alert]:
    """All alerts for a finished crawl.

    run:     this run's scrape_runs fields (status, notes, items_seen, items_with_problems, field_stats),
             or None if the pipeline never recorded it.
    prev_ok: the previous 'ok' run of the same store (items_seen, field_stats), or None.
    stats:   Scrapy stats dict.  t: thresholds (see settings.MONITOR_*).
    """
    alerts: list[Alert] = []
    if run is None:
        alerts.append(Alert("critical", "run_not_recorded",
                            f"the crawl ended ({stats.get('finish_reason')}) without the pipeline finishing a run; "
                            "check DATABASE_URL and the log"))
    else:
        if run["status"] != "ok":
            alerts.append(Alert("critical", f"run_{run['status']}", run.get("notes") or "no details"))
        seen = run["items_seen"]
        if prev_ok and prev_ok["items_seen"] and seen < t["min_item_ratio"] * prev_ok["items_seen"]:
            alerts.append(Alert("critical", "item_count_drop",
                                f"{seen} items, {seen / prev_ok['items_seen']:.0%} of the last good run "
                                f"({prev_ok['items_seen']})"))
        if seen:
            rate = run["items_with_problems"] / seen
            if rate > t["max_problem_rate"]:
                alerts.append(Alert("warning", "parse_problem_rate",
                                    f"{rate:.1%} of items have parse problems ({run['items_with_problems']}/{seen}), "
                                    f"limit {t['max_problem_rate']:.0%}"))
        alerts += _null_rate_jumps(run.get("field_stats"), (prev_ok or {}).get("field_stats"), t["null_rate_jump"])

    rate, errors, attempts = http_error_rate(stats)
    if attempts and rate > t["max_http_error_rate"]:
        alerts.append(Alert("warning", "http_error_rate",
                            f"{errors}/{attempts} downloads failed ({rate:.1%}), limit {t['max_http_error_rate']:.0%}"))
    if stats.get("tcg/parse_exceptions"):
        alerts.append(Alert("critical", "parser_crash", f"parse_item raised on {stats['tcg/parse_exceptions']} items"))
    # each spider reports where its API key/config came from as "<store>/api_key_source" or "<store>/config_source"
    source = next((v for k, v in stats.items() if k.endswith(("/api_key_source", "/config_source"))), None)
    if source == "fallback":
        alerts.append(Alert("warning", "api_key_fallback",
                            "the hardcoded API key was used: the store page could not be read and nothing was cached"))
    elif source == "cached_stale":
        alerts.append(Alert("warning", "api_key_stale", "the store page could not be read; an old cached key was used"))
    if any(v for k, v in stats.items() if k.endswith(("/api_key_rejected", "/config_rejected"))):
        alerts.append(Alert("warning", "api_key_rejected", "the API rejected the cached key; it was re-discovered"))
    return alerts


def _null_rate_jumps(now: dict | None, before: dict | None, jump: float) -> list[Alert]:
    if not now or not before:
        return []
    out = []
    for field, rate in now.items():
        if field.startswith("n_") or rate is None or before.get(field) is None:
            continue
        if rate - before[field] > jump:
            out.append(Alert("warning", "null_rate_jump",
                             f"{field} is NULL on {rate:.1%} (was {before[field]:.1%} in the last good run)"))
    return out


# --- notifiers ----------------------------------------------------------------------------------------------------

def format_message(store: str, run_id, alerts: list[Alert]) -> str:
    worst = "CRITICAL" if any(a.level == "critical" for a in alerts) else "WARNING"
    lines = [f"tcg-tracker {worst}: {store} run {run_id if run_id is not None else '?'}"]
    lines += [f"- {a}" for a in alerts]
    return "\n".join(lines)


def send_discord(webhook_url: str, text: str, timeout: float = 10) -> None:
    body = json.dumps({"content": text[:1900]}).encode()  # Discord's limit is 2000 characters
    req = urllib.request.Request(webhook_url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "tcg-tracker-monitor"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Discord webhook returned HTTP {resp.status}")


def send_email(cfg: dict, subject: str, text: str) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, cfg["from"], cfg["to"]
    msg.set_content(text)
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as smtp:
        if cfg["starttls"]:
            smtp.starttls()
        if cfg["user"]:
            smtp.login(cfg["user"], cfg["password"])
        smtp.send_message(msg)


# --- Scrapy extension ---------------------------------------------------------------------------------------------

class RunMonitor:
    """Evaluates the run when the engine stops (after the pipeline has finished the run) and sends alerts."""

    def __init__(self, crawler):
        s = crawler.settings
        if not s.getbool("MONITOR_ENABLED", True):
            raise NotConfigured
        self.crawler = crawler
        self.database_url = s.get("DATABASE_URL", "")
        self.thresholds = {
            "min_item_ratio": s.getfloat("MONITOR_MIN_ITEM_RATIO"),
            "max_problem_rate": s.getfloat("MONITOR_MAX_PROBLEM_RATE"),
            "null_rate_jump": s.getfloat("MONITOR_NULL_RATE_JUMP"),
            "max_http_error_rate": s.getfloat("MONITOR_MAX_HTTP_ERROR_RATE"),
        }
        self.discord_url = s.get("ALERT_DISCORD_WEBHOOK_URL", "")
        self.email = {"to": s.get("ALERT_EMAIL_TO", ""), "from": s.get("ALERT_EMAIL_FROM", ""),
                      "host": s.get("SMTP_HOST", ""), "port": s.getint("SMTP_PORT", 587),
                      "user": s.get("SMTP_USER", ""), "password": s.get("SMTP_PASSWORD", ""),
                      "starttls": s.getbool("SMTP_STARTTLS", True)}
        self.run: dict | None = None
        self.sent: list[Alert] = []

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls(crawler)
        crawler.signals.connect(ext.on_run_finished, signal=run_finished)
        crawler.signals.connect(ext.on_engine_stopped, signal=signals.engine_stopped)
        return ext

    def on_run_finished(self, **run):
        self.run = run

    def on_engine_stopped(self):
        stats = self.crawler.stats.get_stats()
        prev = self._previous_ok_run() if self.run else None
        alerts = evaluate(self.run, prev, stats, self.thresholds)
        self.sent = alerts
        store = getattr(self.crawler.spider, "name", "?")
        run_id = (self.run or {}).get("run_id")
        if not alerts:
            logger.info("monitor: run %s passed all checks", run_id)
            return
        for a in alerts:
            logger.error("monitor: %s", a)
        self._record(alerts)
        self._notify(format_message(store, run_id, alerts), alerts)

    def _connect(self):
        import psycopg

        return psycopg.connect(self.database_url, autocommit=True)

    def _previous_ok_run(self) -> dict | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """SELECT items_seen, field_stats FROM scrape_runs
                       WHERE store_id=%s AND status='ok' AND id < %s ORDER BY id DESC LIMIT 1""",
                    (self.run["store_id"], self.run["run_id"])).fetchone()
        except Exception as e:
            logger.error("monitor: could not read run history: %r", e)
            return None
        return {"items_seen": row[0], "field_stats": row[1]} if row else None

    def _record(self, alerts: list[Alert]) -> None:
        if not self.run:
            return
        try:
            with self._connect() as conn:
                conn.execute("UPDATE scrape_runs SET alerts=%s WHERE id=%s",
                             ([str(a) for a in alerts], self.run["run_id"]))
        except Exception as e:
            logger.error("monitor: could not store alerts: %r", e)

    def _notify(self, text: str, alerts: list[Alert]) -> None:
        if not self.discord_url and not self.email["to"]:
            logger.warning("monitor: no alert channel configured (ALERT_DISCORD_WEBHOOK_URL / ALERT_EMAIL_TO)")
        if self.discord_url:
            try:
                send_discord(self.discord_url, text)
            except Exception as e:
                logger.error("monitor: Discord alert failed: %r", e)
        if self.email["to"]:
            try:
                send_email(self.email, text.splitlines()[0], text)
            except Exception as e:
                logger.error("monitor: email alert failed: %r", e)
