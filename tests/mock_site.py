"""Downloader middleware that answers every request from saved data, for end-to-end spider tests.

Nothing reaches the network: unknown URLs get a 404. Serves
  - robots.txt for both hosts (allow all),
  - the collection page (tests/data/trinity_collection_page.html),
  - the USF /search API, paging the real saved crawl (tests/trinity_yugioh_usf.json.gz) like the live API.
Environment:
  MOCK_SCENARIO     "ok" (default) | "truncated" (empty pages from skip=1000) | "store_429" (collection page 429)
  MOCK_REQUEST_LOG  file to append every requested URL to
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scrapy.http import HtmlResponse, TextResponse

HERE = Path(__file__).parent
API_KEY = "04572457-312a-4a58-b5e9-6aff246ee39f"


class SavedSiteMiddleware:
    def __init__(self):
        with gzip.open(HERE / "trinity_yugioh_usf.json.gz", "rt", encoding="utf-8") as f:
            self.items = json.load(f)
        self.page = (HERE / "data" / "trinity_collection_page.html").read_bytes()
        self.scenario = os.environ.get("MOCK_SCENARIO", "ok")
        self.request_log = os.environ.get("MOCK_REQUEST_LOG")

    def process_request(self, request, spider=None):
        if self.request_log:
            with open(self.request_log, "a", encoding="utf-8") as f:
                f.write(request.url + "\n")
        u = urlparse(request.url)
        if u.path == "/robots.txt":
            return TextResponse(request.url, body=b"User-agent: *\nAllow: /\n", request=request)
        if u.netloc == "trinityhobby.com" and u.path == "/collections/singles/yugioh":
            if self.scenario == "store_429":
                return HtmlResponse(request.url, status=429, headers={"Retry-After": "0"}, body=b"", request=request)
            return HtmlResponse(request.url, body=self.page, encoding="utf-8", request=request)
        if u.netloc == "svc-2-usf.hotyon.com" and u.path == "/search":
            return self._search(request, parse_qs(u.query))
        return TextResponse(request.url, status=404, body=b"not mocked", request=request)

    def _search(self, request, q):
        if q.get("apiKey", [""])[0] != API_KEY:
            return TextResponse(request.url, status=400, request=request,
                                body=b'{"meta":{"status":400,"description":"Missing or invalid ApiKey."}}')
        skip, take = int(q["skip"][0]), min(int(q["take"][0]), 200)
        items = self.items[skip:skip + take]
        if self.scenario == "truncated" and skip >= 1000:
            items = []
        total = len(self.items)
        body = {"data": {"items": items, "total": total,
                         "facets": [{"facetName": "stockStatus", "labels": [{"label": "1", "value": total}]}]}}
        return TextResponse(request.url, body=json.dumps(body).encode(), encoding="utf-8", request=request)
