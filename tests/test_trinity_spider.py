import json
from pathlib import Path

import pytest
from scrapy.exceptions import CloseSpider
from scrapy.http import HtmlResponse, Request, TextResponse
from scrapy.utils.test import get_crawler

from tcg_tracker.spiders.trinity import (
    COLLECTION_URL,
    PAGE_SIZE,
    TrinitySpider,
    count_problem,
    extract_usf_config,
    next_skip,
)

DATA = Path(__file__).parent / "data"
SETTINGS = {"CONTACT_EMAIL": "test@example.com", "TRINITY_FALLBACK_API_KEY": "fallback-key",
            "TRINITY_MAX_PAGES": 100, "TRINITY_COUNT_TOLERANCE": 0.005}


@pytest.fixture
def spider():
    crawler = get_crawler(TrinitySpider, SETTINGS)
    return TrinitySpider.from_crawler(crawler)


def collection_response(body: str) -> HtmlResponse:
    return HtmlResponse(COLLECTION_URL, body=body.encode(), encoding="utf-8")


def api_response(request: Request, items, total, stock_labels=("1",)) -> TextResponse:
    data = {"data": {"items": items, "total": total,
                     "facets": [{"facetName": "stockStatus", "labels": [{"label": x, "value": 1} for x in stock_labels]}]}}
    return TextResponse(request.url, body=json.dumps(data).encode(), encoding="utf-8", request=request)


def run_page(spider, request, response):
    return list(request.callback(response, **request.cb_kwargs))


# --- API key discovery ------------------------------------------------------------------------------------------

def test_api_key_is_read_from_inline_usf_settings_on_real_page():
    cfg = extract_usf_config((DATA / "trinity_collection_page.html").read_text(encoding="utf-8"))
    assert cfg == {"api_key": "04572457-312a-4a58-b5e9-6aff246ee39f",
                   "search_url": "https://svc-2-usf.hotyon.com/", "collection_id": "368535077111"}


@pytest.mark.parametrize("html", ["<html></html>", "window.usf = { settings: {broken", 'window.usf = { settings: {"x": 1}\n}'])
def test_missing_or_broken_config_is_none(html):
    assert extract_usf_config(html) is None


def test_discovered_key_is_used_for_api_requests(spider):
    out = list(spider.parse_collection(collection_response((DATA / "trinity_collection_page.html").read_text("utf-8"))))
    assert len(out) == 1 and "apiKey=04572457-312a-4a58-b5e9-6aff246ee39f" in out[0].url
    assert "collection=368535077111%2Fyugioh" in out[0].url and "take=200" in out[0].url and "skip=0" in out[0].url
    assert spider.crawler.stats.get_value("trinity/api_key_source") == "discovered"


def test_fallback_key_is_used_loudly_when_page_has_no_config(spider, caplog):
    out = list(spider.parse_collection(collection_response("<html>redesigned theme</html>")))
    assert "apiKey=fallback-key" in out[0].url
    assert spider.crawler.stats.get_value("trinity/api_key_source") == "fallback"
    assert any(r.levelname == "ERROR" and "fallback" in r.getMessage() for r in caplog.records)


# --- paging -----------------------------------------------------------------------------------------------------

def test_next_skip_walks_to_the_end():
    assert next_skip(0, 200, 11793, 1, 100) == (200, "more")
    assert next_skip(11600, 193, 11793, 59, 100) == (None, "done")


def test_next_skip_stops_on_empty_page_and_page_cap():
    assert next_skip(400, 0, 11793, 3, 100) == (None, "empty_page")
    assert next_skip(19800, 200, 50000, 100, 100) == (None, "too_many_pages")


def test_count_tolerance():
    assert count_problem(11793, 11793, 0.005) is None
    assert count_problem(11750, 11793, 0.005) is None
    assert "differs" in count_problem(11000, 11793, 0.005)
    assert count_problem(0, None, 0.005) == "no API page was fetched"


def items(start, n):
    return [{"id": i, "title": f"Card {i}"} for i in range(start, start + n)]


def test_full_paged_crawl_yields_every_item_and_is_ok(spider):
    req = list(spider._begin("k", None, None, "discovered"))[0]
    total, got = 450, []
    while req is not None:
        skip = req.cb_kwargs["skip"]
        out = run_page(spider, req, api_response(req, items(skip, min(PAGE_SIZE, total - skip)), total))
        got += [o for o in out if isinstance(o, dict)]
        req = next((o for o in out if isinstance(o, Request)), None)
    assert len(got) == 450 and spider.pages == 3
    assert spider.verdict("finished") is None


def test_empty_page_before_total_fails_the_run(spider):
    req = list(spider._begin("k", None, None, "discovered"))[0]
    run_page(spider, req, api_response(req, items(0, 200), 1000))
    req2 = spider.page_request(200)
    with pytest.raises(CloseSpider):
        run_page(spider, req2, api_response(req2, [], 1000))
    assert "empty_page" in spider.verdict("failed")


def test_out_of_stock_items_appearing_fails_the_run(spider):
    req = list(spider._begin("k", None, None, "discovered"))[0]
    with pytest.raises(CloseSpider):
        run_page(spider, req, api_response(req, items(0, 10), 10, stock_labels=("1", "0")))
    assert "non-in-stock" in spider.verdict("failed")


def test_duplicate_ids_are_skipped(spider):
    req = list(spider._begin("k", None, None, "discovered"))[0]
    out = run_page(spider, req, api_response(req, items(0, 5) + items(0, 5), 1000))
    assert len([o for o in out if isinstance(o, dict)]) == 5
    assert spider.crawler.stats.get_value("trinity/duplicate_ids") == 5


def test_count_mismatch_fails_the_run(spider):
    spider.total, spider.seen_ids = 11793, set(range(11000))
    assert "differs" in spider.verdict("finished")


def test_early_close_is_a_failure(spider):
    spider.total, spider.seen_ids = 10, set(range(10))
    assert spider.verdict("shutdown") == "spider closed early: shutdown"
