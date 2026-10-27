"""Hobbiesville (hobbiesville.com, Shopify) Yu-Gi-Oh singles via Shopify's storefront feed.

Same flow and completeness check as Fusion (FusionSpider): /collections/yugioh-singles.json for products_count, then
products.json 250 per page until an empty page (4,171 products, 17 pages on 2026-10-26). robots.txt allows
/collections/ (it blocks sort_by and filter URLs, which we don't use). Permission: the user phoned the store
(2026-10-26).
"""
from __future__ import annotations

import adapter_hobbiesville
from tcg_tracker.spiders.fusion import FusionSpider

STORE = {"slug": "hobbiesville", "name": "Hobbiesville", "base_url": "https://www.hobbiesville.com"}
COLLECTION = "https://www.hobbiesville.com/collections/yugioh-singles"


class HobbiesvilleSpider(FusionSpider):
    name = "hobbiesville"
    store = STORE
    collection = COLLECTION
    setting_prefix = "HOBBIESVILLE"
    adapter = staticmethod(adapter_hobbiesville.parse_item)
    # Shopify store domain. 17 pages at 15 s each got no 429 (2026-10-26), so 5 s (~1.5 min a crawl); a 429 is still
    # honoured (Retry-After) and retried up to 15 times.
    custom_settings = {"DOWNLOAD_DELAY": 5.0, "AUTOTHROTTLE_START_DELAY": 5.0, "AUTOTHROTTLE_MAX_DELAY": 120,
                       "RETRY_TIMES": 15, "CLOSESPIDER_TIMEOUT": 6000}
