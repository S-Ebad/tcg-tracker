"""Trinity Hobby Yu-Gi-Oh singles via the Hotyon "Ultimate Search & Filter" (USF) API.

Flow: collection page (discover API key) -> /search pages of 200 with skip paging until skip >= data.total.
The run is reported as failed (and nothing is marked out of stock) when the crawl is incomplete.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlencode

import scrapy
from scrapy.exceptions import CloseSpider

STORE = {"slug": "trinity", "name": "Trinity Hobby", "base_url": "https://trinityhobby.com"}
COLLECTION_URL = "https://trinityhobby.com/collections/singles/yugioh"
COLLECTION_TAG = "yugioh"
# Used only if the collection page can't be read; both were current on 2026-10-21.
DEFAULT_SEARCH_URL = "https://svc-2-usf.hotyon.com/"
DEFAULT_COLLECTION_ID = "368535077111"
PAGE_SIZE = 200  # API maximum

# The key is not in usf-boot.js: that script reads it from the inline `window.usf = { settings: {...} }` (siteId).
USF_SETTINGS_RE = re.compile(r"window\.usf\s*=\s*\{\s*settings\s*:\s*")
COLLECTION_ID_RE = re.compile(r"window\._usfCollectionId\s*=\s*(\d+)")


def extract_usf_config(html: str) -> dict | None:
    """Pull api_key / search_url / collection_id out of the collection page, or None if the config isn't there."""
    m = USF_SETTINGS_RE.search(html)
    if not m:
        return None
    try:
        settings, _ = json.JSONDecoder().raw_decode(html, m.end())
    except ValueError:
        return None
    if not isinstance(settings, dict) or not settings.get("siteId"):
        return None
    cid = COLLECTION_ID_RE.search(html)
    return {"api_key": settings["siteId"], "search_url": settings.get("searchSvcUrl"),
            "collection_id": cid.group(1) if cid else None}


def next_skip(skip: int, n_items: int, total: int, pages_done: int, max_pages: int) -> tuple[int | None, str]:
    """Decide what to fetch after the page at `skip`. Returns (next skip or None, reason)."""
    nxt = skip + PAGE_SIZE
    if nxt >= total:
        return None, "done"
    if n_items == 0:
        return None, "empty_page"
    if pages_done >= max_pages:
        return None, "too_many_pages"
    return nxt, "more"


def count_problem(seen: int, total: int | None, tolerance: float) -> str | None:
    """Reason to fail the run if the unique item count doesn't match data.total, else None."""
    if total is None:
        return "no API page was fetched"
    if abs(seen - total) > tolerance * total:
        return f"item count {seen} differs from data.total {total} by more than {tolerance:.1%}"
    return None


class TrinitySpider(scrapy.Spider):
    name = "trinity"
    store = STORE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_ids: set[int] = set()
        self.total: int | None = None
        self.pages = 0
        self.failure: str | None = None

    @property
    def _settings(self):
        return self.crawler.settings

    async def start(self):
        if not self._settings.get("CONTACT_EMAIL"):
            raise CloseSpider("TCG_CONTACT_EMAIL is not set; the User-Agent must carry a contact address")
        yield scrapy.Request(COLLECTION_URL, callback=self.parse_collection, errback=self.collection_failed)

    # --- API key discovery -------------------------------------------------------------------------------------
    def parse_collection(self, response):
        cfg = extract_usf_config(response.text)
        if cfg:
            yield from self._begin(cfg["api_key"], cfg["search_url"], cfg["collection_id"], source="discovered")
        else:
            yield from self._fallback(f"USF config not found in {response.url}")

    def collection_failed(self, failure):
        yield from self._fallback(f"collection page failed: {failure.value!r}")

    def _fallback(self, why: str):
        self.logger.error("!!! %s. Using the hardcoded fallback API key; check the page and update the spider.", why)
        yield from self._begin(self._settings.get("TRINITY_FALLBACK_API_KEY"), None, None, source="fallback")

    def _begin(self, api_key, search_url, collection_id, source):
        if source == "discovered" and api_key != self._settings.get("TRINITY_FALLBACK_API_KEY"):
            self.logger.warning("USF API key changed from the configured fallback; update TRINITY_FALLBACK_API_KEY")
        self.crawler.stats.set_value("trinity/api_key_source", source)
        self.api_key = api_key
        self.search_url = search_url or DEFAULT_SEARCH_URL
        self.collection = f"{collection_id or DEFAULT_COLLECTION_ID}/{COLLECTION_TAG}"
        yield self.page_request(0)

    # --- paging ------------------------------------------------------------------------------------------------
    def page_request(self, skip: int) -> scrapy.Request:
        # sort=-price gives a stable order (all ids unique across pages on the real crawl).
        # No stock facetFilter: the store only exposes in-stock items, which parse_page verifies on every page.
        params = {"q": "", "apiKey": self.api_key, "country": "CA", "locale": "en", "getProductDescription": 0,
                  "collection": self.collection, "skip": skip, "take": PAGE_SIZE, "sort": "-price"}
        return scrapy.Request(f"{self.search_url.rstrip('/')}/search?{urlencode(params)}", callback=self.parse_page,
                              errback=self.page_failed, cb_kwargs={"skip": skip})

    def parse_page(self, response, skip: int):
        try:
            data = response.json()["data"]
            total, items = int(data["total"]), data["items"]
        except (ValueError, KeyError, TypeError) as e:
            self._fail(f"unexpected API response at skip={skip}: {e!r}")
        self.pages += 1
        if self.total is not None and total != self.total:
            self.logger.warning("data.total changed mid-crawl: %s -> %s", self.total, total)
        self.total = total
        self._check_stock_facet(data.get("facets") or [])

        for raw in items:
            if raw.get("id") in self.seen_ids:
                self.crawler.stats.inc_value("trinity/duplicate_ids")
                continue
            self.seen_ids.add(raw.get("id"))
            yield {"raw": raw}

        nxt, why = next_skip(skip, len(items), total, self.pages, self._settings.getint("TRINITY_MAX_PAGES"))
        if nxt is not None:
            yield self.page_request(nxt)
        elif why != "done":
            self._fail(f"paging stopped early ({why}) at skip={skip}, {len(self.seen_ids)}/{total} items")

    def _check_stock_facet(self, facets: list[dict]):
        for f in facets:
            if f.get("facetName") == "stockStatus":
                labels = {str(x.get("label")) for x in f.get("labels") or []}
                if labels - {"1"}:
                    # out-of-stock items would be saved as in stock: stop rather than store wrong data
                    self._fail(f"API now returns non-in-stock items (stockStatus labels {sorted(labels)})")

    def page_failed(self, failure):
        self._fail(f"page request failed after retries: {failure.request.url} {failure.value!r}")

    def _fail(self, reason: str):
        self.failure = self.failure or reason
        self.logger.error("Run failed: %s", reason)
        raise CloseSpider("failed")

    # --- verdict, read by the pipeline when the spider closes ----------------------------------------------------
    def verdict(self, close_reason: str) -> str | None:
        """None if the crawl is complete and trustworthy, else the reason it isn't."""
        if self.failure:
            return self.failure
        if close_reason != "finished":
            return f"spider closed early: {close_reason}"
        return count_problem(len(self.seen_ids), self.total, self._settings.getfloat("TRINITY_COUNT_TOLERANCE"))
