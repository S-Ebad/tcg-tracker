"""Fusion Gaming (fusiongamingonline.com, Shopify + BinderPOS) Yu-Gi-Oh singles via Shopify's storefront feed.

Flow: /collections/yugioh-singles.json (products_count) -> /collections/yugioh-singles/products.json, 250 per page,
until an empty page. The collection (13,886 products on 2026-10-26) is well under Shopify's 25,000 page*limit cap.
The feed only lists products with at least one copy available, so as with the other stores a product missing from a
complete crawl is out of stock. No API key: the feed is public.

Completeness: the unique product count must be within FUSION_COUNT_TOLERANCE of products_count. products_count
counts a few products the feed doesn't list (13,886 vs 13,848, 0.27%), hence 1% rather than the usual 0.5%.
These requests go to the store's own site, so the spider waits longer between them.
"""
from __future__ import annotations

import scrapy
from scrapy.exceptions import CloseSpider

import adapter_fusion
from tcg_tracker.spiders.trinity import count_problem

STORE = {"slug": "fusion", "name": "Fusion Gaming", "base_url": "https://fusiongamingonline.com"}
COLLECTION = "https://fusiongamingonline.com/collections/yugioh-singles"
PAGE_SIZE = 250


class FusionSpider(scrapy.Spider):
    name = "fusion"
    store = STORE
    adapter = staticmethod(adapter_fusion.parse_item)  # Shopify product -> CardRec
    custom_settings = {"DOWNLOAD_DELAY": 2.0}

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
        yield scrapy.Request(f"{COLLECTION}.json", callback=self.parse_collection, errback=self.request_failed)

    def parse_collection(self, response):
        try:
            self.total = int(response.json()["collection"]["products_count"])
        except (ValueError, KeyError, TypeError) as e:
            self._fail(f"could not read products_count from {response.url}: {e!r}")
        yield self.page_request(1)

    def page_request(self, page: int) -> scrapy.Request:
        return scrapy.Request(f"{COLLECTION}/products.json?limit={PAGE_SIZE}&page={page}", callback=self.parse_page,
                              errback=self.request_failed, cb_kwargs={"page": page})

    def parse_page(self, response, page: int):
        try:
            products = response.json()["products"]
        except (ValueError, KeyError, TypeError) as e:
            self._fail(f"unexpected products.json response on page {page}: {e!r}")
        self.pages += 1
        for p in products:
            if p.get("id") in self.seen_ids:
                self.crawler.stats.inc_value("fusion/duplicate_ids")
                continue
            self.seen_ids.add(p.get("id"))
            yield {"raw": p}
        if not products:
            return  # the end; the count check in verdict() catches an early stop
        if page >= self._settings.getint("FUSION_MAX_PAGES", 100):
            self._fail(f"more than {page} pages: the collection grew past what the spider expects")
        yield self.page_request(page + 1)

    def request_failed(self, failure):
        self._fail(f"request failed after retries: {failure.request.url} {failure.value!r}")

    def _fail(self, reason: str):
        self.failure = self.failure or reason
        self.logger.error("Run failed: %s", reason)
        raise CloseSpider("failed")

    def verdict(self, close_reason: str) -> str | None:
        """None if the crawl is complete and trustworthy, else the reason it isn't."""
        if self.failure:
            return self.failure
        if close_reason != "finished":
            return f"spider closed early: {close_reason}"
        return count_problem(len(self.seen_ids), self.total, self._settings.getfloat("FUSION_COUNT_TOLERANCE", 0.01))
