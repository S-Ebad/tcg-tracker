"""Per-store settings cached in Postgres (store_config table), used by spiders before the pipeline is running."""
from __future__ import annotations

import logging

import db

logger = logging.getLogger(__name__)


class StoreConfigCache:
    """Short-lived connections so a spider can read/write its cached settings at start-up.

    A database problem here is logged and treated as "nothing cached": the pipeline fails the run loudly anyway.
    """

    def __init__(self, database_url: str, store: dict):
        self.database_url = database_url
        self.store = store

    def _connect(self):
        import psycopg

        return psycopg.connect(self.database_url, autocommit=True)

    def load(self, key: str):
        """(value, age_seconds) or None."""
        if not self.database_url:
            return None
        try:
            with self._connect() as conn:
                store_id = db.ensure_store(conn, self.store["slug"], self.store["name"], self.store["base_url"])
                return db.get_store_config(conn, store_id, key)
        except Exception as e:
            logger.error("could not read cached %s for %s: %r", key, self.store["slug"], e)
            return None

    def save(self, key: str, value) -> None:
        if not self.database_url:
            return
        try:
            with self._connect() as conn:
                store_id = db.ensure_store(conn, self.store["slug"], self.store["name"], self.store["base_url"])
                db.set_store_config(conn, store_id, key, value)
        except Exception as e:
            logger.error("could not cache %s for %s: %r", key, self.store["slug"], e)
