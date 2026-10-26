import json

import pytest
from scrapy.exceptions import CloseSpider
from scrapy.http import Request, TextResponse
from scrapy.utils.test import get_crawler

from tcg_tracker.spiders.fusion import COLLECTION, PAGE_SIZE, FusionSpider

SETTINGS = {"CONTACT_EMAIL": "test@example.com", "FUSION_MAX_PAGES": 100, "FUSION_COUNT_TOLERANCE": 0.01}


@pytest.fixture
def spider():
    return FusionSpider.from_crawler(get_crawler(FusionSpider, SETTINGS))


def json_response(request, body):
    return TextResponse(request.url, body=json.dumps(body).encode(), encoding="utf-8", request=request)


def products(start, n):
    return [{"id": i, "title": f"Card {i}"} for i in range(start, start + n)]


def run(request, response):
    return list(request.callback(response, **request.cb_kwargs))


def crawl(spider, total, available):
    """Walk collection.json + every products.json page; `available` is how many products the feed lists."""
    req = Request(f"{COLLECTION}.json", callback=spider.parse_collection)
    out = run(req, json_response(req, {"collection": {"products_count": total}}))
    got = []
    while out:
        req = next((o for o in out if isinstance(o, Request)), None)
        if req is None:
            break
        p = req.cb_kwargs["page"]
        start = (p - 1) * PAGE_SIZE
        out = run(req, json_response(req, {"products": products(start, max(0, min(PAGE_SIZE, available - start)))}))
        got += [o for o in out if isinstance(o, dict)]
    return got


def test_full_crawl_reads_until_an_empty_page(spider):
    got = crawl(spider, total=13886, available=13848)  # the real gap: 0.27%
    assert len(got) == 13848 and spider.pages == 57  # 56 with products + the empty page that ends it
    assert spider.verdict("finished") is None


def test_feed_stopping_early_fails_the_count_check(spider):
    crawl(spider, total=13886, available=5000)
    assert "differs from data.total" in spider.verdict("finished")


def test_missing_products_count_fails(spider):
    req = Request(f"{COLLECTION}.json", callback=spider.parse_collection)
    with pytest.raises(CloseSpider):
        run(req, json_response(req, {"oops": {}}))
    assert "products_count" in spider.verdict("failed")


def test_duplicates_are_skipped(spider):
    spider.total = 3
    req = spider.page_request(1)
    out = run(req, json_response(req, {"products": products(0, 3) + products(0, 2)}))
    assert len([o for o in out if isinstance(o, dict)]) == 3
    assert spider.crawler.stats.get_value("fusion/duplicate_ids") == 2


def test_page_cap(spider):
    spider.total = 10 ** 6
    req = spider.page_request(100)
    with pytest.raises(CloseSpider):
        run(req, json_response(req, {"products": products(0, 250)}))


def test_rides_the_rate_limit_and_is_patient_with_the_store():
    s = FusionSpider.custom_settings
    assert s["ADAPTIVE_DELAY_ENABLED"] and s["ADAPTIVE_DELAY_MIN"] >= 3 and not s["AUTOTHROTTLE_ENABLED"]
    assert s["RETRY_TIMES"] >= 15  # ~15 min of honouring Retry-After: 60 per page


def test_adaptive_delay_speeds_up_on_success_and_backs_off_on_429():
    from types import SimpleNamespace

    from scrapy.exceptions import NotConfigured

    from tcg_tracker.middlewares import AdaptiveDelayMiddleware

    crawler = get_crawler(FusionSpider, {"ADAPTIVE_DELAY_ENABLED": True, "ADAPTIVE_DELAY_MIN": 3.0,
                                         "ADAPTIVE_DELAY_MAX": 120.0})
    slot = SimpleNamespace(delay=10.0)
    crawler.engine = SimpleNamespace(downloader=SimpleNamespace(slots={"s": slot}, get_slot_key=lambda r: "s"))
    mw = AdaptiveDelayMiddleware.from_crawler(crawler)
    req = Request("https://fusiongamingonline.com/x")
    ok, slow = TextResponse(req.url, status=200, body=b""), TextResponse(req.url, status=429, body=b"")
    mw.process_response(req, ok)
    assert slot.delay == pytest.approx(8.5)
    for _ in range(30):
        mw.process_response(req, ok)
    assert slot.delay == 3.0  # floor
    mw.process_response(req, slow)
    mw.process_response(req, slow)
    assert slot.delay == 12.0
    for _ in range(10):
        mw.process_response(req, slow)
    assert slot.delay == 120.0  # cap
    from scrapy import Spider

    with pytest.raises(NotConfigured):  # other spiders (Trinity, 401) don't turn it on
        AdaptiveDelayMiddleware.from_crawler(get_crawler(Spider))
