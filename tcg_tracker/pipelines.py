"""Parse raw items and store them in Postgres in batched transactions, with run bookkeeping."""
from __future__ import annotations

import logging

import psycopg
from scrapy import signals

import db
from parser import parse_item

logger = logging.getLogger(__name__)


class PostgresPipeline:
    def __init__(self, crawler):
        self.crawler = crawler
        self.database_url = crawler.settings.get("DATABASE_URL")
        self.batch_size = crawler.settings.getint("DB_BATCH_SIZE", 500)
        self.stats = crawler.stats
        self.buffer: list[tuple] = []
        self.saved = 0
        self.with_problems = 0
        self.db_error: str | None = None
        self.conn = None

    @classmethod
    def from_crawler(cls, crawler):
        p = cls(crawler)
        # finish_run needs the close reason, which close_spider doesn't get
        crawler.signals.connect(p.spider_closed, signal=signals.spider_closed)
        return p

    # Scrapy >= 2.14 no longer passes `spider` to pipeline methods; the crawler holds it.
    def open_spider(self, spider=None):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is not set")
        self.conn = psycopg.connect(self.database_url, autocommit=True)
        s = self.crawler.spider.store
        self.store_id = db.ensure_store(self.conn, s["slug"], s["name"], s["base_url"])
        self.run_id = db.start_run(self.conn, self.store_id)
        logger.info("scrape run %s started for store %s", self.run_id, s["slug"])

    def process_item(self, item, spider=None):
        if self.db_error:
            return item
        raw = item["raw"]
        try:
            rec = parse_item(raw)
        except Exception:
            # a crash is a parser bug, not a data gap: count it loudly so monitoring sees it
            logger.exception("parse_item crashed on product %s", raw.get("id"))
            self.stats.inc_value("tcg/parse_exceptions")
            return item
        if rec.problems:
            self.with_problems += 1
            self.stats.inc_value("tcg/items_with_problems")
        self.buffer.append((rec, raw))
        if len(self.buffer) >= self.batch_size:
            self._flush()
        return item

    def _flush(self):
        if not self.buffer or self.db_error:
            return
        try:
            with self.conn.transaction():
                db.save_items(self.conn, self.store_id, self.run_id, self.buffer)
        except psycopg.Error as e:
            self.db_error = f"database error while saving a batch: {e!r}"
            logger.error(self.db_error)
            self.crawler.engine.close_spider(self.crawler.spider, "db_error")
            return
        self.saved += len(self.buffer)
        self.stats.set_value("tcg/items_saved", self.saved)
        self.buffer.clear()

    def close_spider(self, spider=None):
        self._flush()

    def spider_closed(self, spider, reason):
        if self.conn is None:
            return
        error = self.db_error or spider.verdict(reason)
        try:
            with self.conn.transaction():
                status, notes = db.finish_run(self.conn, self.store_id, self.run_id, self.saved,
                                              self.with_problems, error=error)
        finally:
            self.conn.close()
        self.stats.set_value("tcg/run_status", status)
        log = logger.info if status == "ok" else logger.error
        log("scrape run %s finished: %s (%s items, %s with problems)%s", self.run_id, status, self.saved,
            self.with_problems, f" - {notes}" if notes else "")
