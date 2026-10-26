"""Downloader middlewares."""
from __future__ import annotations

import asyncio
import logging

from scrapy.exceptions import NotConfigured

logger = logging.getLogger(__name__)

MAX_RETRY_AFTER = 300  # seconds; a longer ask is treated as "try the next scheduled run"


def parse_retry_after(value: bytes | str | None) -> float | None:
    """Seconds to wait from a Retry-After header (delta-seconds form only), or None if absent/unusable."""
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("latin-1")
    try:
        seconds = float(value.strip())
    except ValueError:
        return None  # HTTP-date form: let normal retry/backoff handle it
    return max(0.0, seconds)


class RetryAfterMiddleware:
    """On 429/503 with Retry-After, wait that long before RetryMiddleware re-schedules the request.

    With CONCURRENT_REQUESTS = 1 this pauses the whole crawl, which is the point.
    """

    async def process_response(self, request, response, spider=None):
        if response.status in (429, 503):
            wait = parse_retry_after(response.headers.get(b"Retry-After"))
            if wait is not None:
                if wait > MAX_RETRY_AFTER:
                    logger.error("Retry-After %ss from %s exceeds %ss; not waiting", wait, request.url, MAX_RETRY_AFTER)
                else:
                    logger.warning("HTTP %s from %s, waiting %ss (Retry-After)", response.status, request.url, wait)
                    await asyncio.sleep(wait)
        return response


class AdaptiveDelayMiddleware:
    """Ride just under a site's rate limit: speed up while pages come through, back off hard on 429.

    Each successful response shrinks the delay between requests (x ADAPTIVE_DELAY_DECREASE, not below
    ADAPTIVE_DELAY_MIN); each 429/503 multiplies it (x ADAPTIVE_DELAY_INCREASE, not above ADAPTIVE_DELAY_MAX), on top
    of RetryAfterMiddleware honouring Retry-After. Scrapy's AutoThrottle reacts to latency, not to 429s, so spiders
    using this turn AutoThrottle off. Enabled per spider with ADAPTIVE_DELAY_ENABLED (Fusion: Shopify store domain).
    """

    def __init__(self, crawler):
        s = crawler.settings
        if not s.getbool("ADAPTIVE_DELAY_ENABLED"):
            raise NotConfigured
        self.crawler = crawler
        self.min = s.getfloat("ADAPTIVE_DELAY_MIN", 3.0)
        self.max = s.getfloat("ADAPTIVE_DELAY_MAX", 120.0)
        self.down = s.getfloat("ADAPTIVE_DELAY_DECREASE", 0.85)
        self.up = s.getfloat("ADAPTIVE_DELAY_INCREASE", 2.0)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def _slot(self, request):
        downloader = self.crawler.engine.downloader
        key = request.meta.get("download_slot") or downloader.get_slot_key(request)
        return downloader.slots.get(key)

    def process_response(self, request, response, spider=None):
        slot = self._slot(request)
        if slot is not None:
            before = slot.delay
            if response.status in (429, 503):
                slot.delay = min(self.max, max(self.min, before * self.up))
                self.crawler.stats.inc_value("adaptive_delay/backoffs")
                logger.info("HTTP %s: delay %.1fs -> %.1fs", response.status, before, slot.delay)
            elif 200 <= response.status < 300:
                slot.delay = max(self.min, before * self.down)
            self.crawler.stats.set_value("adaptive_delay/current", round(slot.delay, 2))
        return response
