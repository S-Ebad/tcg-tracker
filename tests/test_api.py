"""The API against a test database loaded with all three saved crawls (Trinity, 401 Games, Fusion Gaming).
Needs TEST_DATABASE_URL (a *_test database; its schema is rebuilt). Image downloads are faked: no network."""
import gzip
import json
import os
from pathlib import Path

import pytest

URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = [
    pytest.mark.skipif(not URL.rsplit("/", 1)[-1].endswith("_test"),
                       reason="TEST_DATABASE_URL (a *_test database) not set"),
    # Starlette suggests a package named "httpx2" for its test client; we keep the well-known httpx
    pytest.mark.filterwarnings("ignore:Using `httpx` with `starlette.testclient` is deprecated"),
]
TESTS = Path(__file__).parent


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import psycopg
    from fastapi.testclient import TestClient

    import db
    from adapter_401 import parse_item as p401
    from adapter_fusion import parse_item as pfusion
    from migrate import migrate
    from parser import parse_item as ptrinity

    stores = [("trinity", "Trinity Hobby", "https://trinityhobby.com", "trinity_yugioh_usf.json.gz", ptrinity),
              ("401games", "401 Games", "https://store.401games.ca", "games401_fastsimon.json.gz", p401),
              ("fusion", "Fusion Gaming", "https://fusiongamingonline.com", "fusion_products.json.gz", pfusion)]
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        migrate(conn)
        for slug, name, base, fixture, adapter in stores:
            store = db.ensure_store(conn, slug, name, base)
            run = db.start_run(conn, store)
            with gzip.open(TESTS / fixture, "rt", encoding="utf-8") as f:
                pairs = [(adapter(raw), raw) for raw in json.load(f)]
            for i in range(0, len(pairs), 1000):
                with conn.transaction():
                    db.save_items(conn, store, run, pairs[i:i + 1000])
            with conn.transaction():
                db.finish_run(conn, store, run, len(pairs), 0)

    saved = {k: os.environ.get(k) for k in ("DATABASE_URL", "IMAGE_CACHE_DIR")}
    os.environ["DATABASE_URL"] = URL
    os.environ["IMAGE_CACHE_DIR"] = str(tmp_path_factory.mktemp("images"))
    from api.main import app

    with TestClient(app) as c:
        yield c
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_stores_report_last_update(client):
    rows = client.get("/api/stores").json()
    assert [r["slug"] for r in rows] == ["401games", "fusion", "trinity"]  # ordered by name
    assert all(r["last_updated"] and r["listings_in_stock"] > 10000 for r in rows)


def test_search_by_name_finds_every_printing_with_cheapest_offer(client):
    body = client.get("/api/search", params={"q": "dark magician", "limit": 100}).json()
    ysyr = next(i for i in body["items"] if i["card_key"] == "YSYR-EN001|ultimate-rare|base")
    assert (ysyr["min_price"], ysyr["store_count"], ysyr["set_name"]) == (5.0, 3, "Starter Deck: Yugi Reloaded")
    assert body["total"] >= len(body["items"]) > 10


def test_search_ignores_punctuation_and_exact_code_ranks_first(client):
    maxx = client.get("/api/search", params={"q": "maxx c"}).json()["items"]
    assert any(i["card_number"] == "SBC2-ENI28" for i in maxx)
    first = client.get("/api/search", params={"q": "ysyr-en001"}).json()["items"][0]
    assert first["card_number"] == "YSYR-EN001"


def test_search_sort_by_price_and_store_filter(client):
    items = client.get("/api/search", params={"q": "blue-eyes white dragon", "sort": "price", "limit": 50}).json()["items"]
    prices = [i["min_price"] for i in items]
    assert prices == sorted(prices)
    only401 = client.get("/api/search", params={"q": "blue-eyes white dragon", "store": "401games"}).json()["items"]
    assert only401 and all(i["store_count"] == 1 for i in only401)


def test_blank_or_too_long_search_is_handled(client):
    assert client.get("/api/search", params={"q": "!!!"}).json() == {"total": 0, "items": []}
    assert client.get("/api/search", params={"q": "x" * 101}).status_code == 422


def test_card_page_has_offers_editions_and_store_links(client):
    c = client.get("/api/cards/YSYR-EN001|ultimate-rare|base").json()
    assert (c["name"], c["rarity"], c["stores_in_stock"], c["cheapest_nm"]) == (
        "Dark Magician", "Ultimate Rare", 3, 7.4)
    assert c["editions"] == ["1st Edition", "Unlimited"]
    eds = [o["edition"] for o in c["offers"]]
    assert eds == sorted(eds, key=["1st Edition", "Unlimited"].index)  # 1st Edition first
    trinity = next(o for o in c["offers"] if o["store"] == "trinity")
    assert trinity["url"].startswith("https://trinityhobby.com/products/")
    assert any(o["card_key"].startswith("LDK2-ENY10") for o in c["other_printings"])


def test_unknown_card_is_404(client):
    assert client.get("/api/cards/NOPE-EN000|rare|base").status_code == 404


def test_history_is_grouped_by_store(client):
    series = client.get("/api/cards/YSYR-EN001|ultimate-rare|base/history",
                        params={"edition": "1st Edition", "condition": "NM"}).json()
    by_store = {s["store"]: s["points"] for s in series}
    assert set(by_store) == {"401games", "fusion", "trinity"}
    assert (by_store["401games"][0]["price"], by_store["401games"][0]["in_stock"]) == (19.0, True)
    # the other stores list 1st Edition NM too, but it was out of stock when recorded
    assert not any(p["in_stock"] for p in by_store["fusion"] + by_store["trinity"])


def test_sets_and_set_page(client):
    sets = {s["set_code"]: s for s in client.get("/api/sets").json()}
    assert sets["MAMO"]["set_name"] == "Magnificent Monsters" and sets["MAMO"]["cards_in_stock"] > 50
    page = client.get("/api/sets/mamo").json()
    numbers = [i["card_number"] for i in page["items"]]
    assert numbers == sorted(numbers) and all(n.startswith("MAMO-") for n in numbers)


def test_fusion_only_cards_get_a_set_name_from_the_other_stores(client):
    # Fusion's feed has no set names; MACR is named via Trinity/401
    assert client.get("/api/sets/MACR").json()["items"][0]["set_name"] == "Maximum Crisis"


def test_deals_compare_the_same_card_edition_and_condition(client):
    top = client.get("/api/deals", params={"limit": 5}).json()
    assert top[0]["name"].startswith("Maxx") and top[0]["card_number"] == "SBC2-ENI28"
    assert (top[0]["cheapest_store"], top[0]["low"], top[0]["high"]) == ("trinity", 10.6, 35.0)
    assert [d["saving"] for d in top] == sorted((d["saving"] for d in top), reverse=True)
    pct = client.get("/api/deals", params={"sort": "percent", "limit": 5}).json()
    assert pct[0]["saving_pct"] >= pct[-1]["saving_pct"]


def test_image_is_downloaded_once_then_served_from_cache(client, monkeypatch):
    from api import images

    calls = []

    def fake_download(url, ua):
        calls.append(url)
        return b"\xff\xd8fake-jpeg", "image/jpeg"

    monkeypatch.setattr(images, "download", fake_download)
    key = "YSYR-EN001|ultimate-rare|base"
    for _ in range(2):
        r = client.get(f"/images/{key}")
        assert r.status_code == 200 and r.content == b"\xff\xd8fake-jpeg"
        assert r.headers["content-type"] == "image/jpeg" and "max-age" in r.headers["cache-control"]
    assert len(calls) == 1 and calls[0].startswith("https://cdn.shopify.com/")


def test_image_hosts_are_restricted_and_resized():
    from api import images

    assert images.allowed("https://cdn.shopify.com/s/files/x.jpg")
    assert not images.allowed("https://evil.example.com/x.jpg") and not images.allowed("http://cdn.shopify.com/x")
    assert images.sized("https://cdn.shopify.com/x.jpg?v=1") == "https://cdn.shopify.com/x.jpg?v=1&width=480"
