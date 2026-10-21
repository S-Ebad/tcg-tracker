"""Downloader middlewares."""
from __future__ import annotations

import asyncio
import logging

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
