"""Fusion Gaming adapter, checked on real products from the saved crawl (tests/fusion_products.json.gz,
13,848 Yu-Gi-Oh singles from the collection's products.json, 2026-10-26)."""
import gzip
import json
from collections import Counter
from pathlib import Path

import pytest

from adapter_401 import parse_item as parse_401
from adapter_fusion import parse_item
from parser import parse_item as parse_trinity

FIXTURE = Path(__file__).parent / "fusion_products.json.gz"


@pytest.fixture(scope="module")
def fusion() -> list[dict]:
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def by_id(fusion):
    return {p["id"]: p for p in fusion}


def test_mixed_edition_product_keeps_each_variant_edition(by_id):
    r = parse_item(by_id[7476301332558])  # Lyrilusc - Assembled Nightingale [MACR-EN043] Super Rare, 10 variants
    assert r.card_key == "MACR-EN043|super-rare|base" and not r.problems
    assert {v.edition for v in r.variants} == {"1st Edition", "Unlimited"}
    assert [v.condition for v in r.variants[:5]] == ["NM", "LP", "MP", "HP", "DMG"]


def test_stock_is_available_flag_and_quantity_is_unknown(by_id):
    p = by_id[7476301332558]
    r = parse_item(p)
    assert [v.in_stock for v in r.variants] == [v["available"] for v in p["variants"]]
    assert {v.quantity for v in r.variants} == {None}
    assert r.title == p["title"] and r.url_name == p["handle"] and r.set_name is None


@pytest.mark.parametrize("pid,key", [
    (7432025210958, "LODT-EN029|common|25th-anniversary"),  # Unifrog (25th Anniversary): 1st, Unlimited and Limited
    (7265383120974, "LC01-EN005|ultra-rare|25th-anniversary"),
])
def test_version_labels(by_id, pid, key):
    assert parse_item(by_id[pid]).card_key == key


def test_esr_in_the_title_matches_401s_emblazoned_secret_rare(by_id):
    # Fusion tags it only "Secret Rare"; 401 calls the same card "Emblazoned Secret Rare"
    assert parse_item(by_id[7710314594382]).card_key == "25LP-EN003|emblazoned-secret-rare|base"
    assert parse_item(by_id[7690633576526]).card_key == "25LP-EN003|secret-rare|base"  # the plain printing


def test_every_product_with_an_image_gets_an_https_link(fusion):
    urls = [parse_item(p).image_url for p in fusion]
    assert sum(u is not None for u in urls) == 13836
    assert all(u.startswith("https://cdn.shopify.com/") for u in urls if u)


def test_token_without_card_number_is_quarantined(by_id):
    r = parse_item(by_id[7476190150734])  # Token [SR01-ENTKN] Common
    assert r.card_key is None and r.problems == ["no_set_code"]


def test_whole_crawl(fusion):
    recs = [parse_item(p) for p in fusion]
    assert len(recs) == 13848 and all(p["product_type"] == "Yugioh Single" for p in fusion)
    assert Counter(x.split(":")[0] for r in recs for x in r.problems) == {"no_set_code": 11, "no_rarity": 4}
    assert sum(1 for r in recs if r.card_key is None) == 11
    assert {v.condition for r in recs for v in r.variants} == {"NM", "LP", "MP", "HP", "DMG"}
    assert {v.edition for r in recs for v in r.variants} == {"1st Edition", "Unlimited", "Limited"}
    # the feed only lists products with at least one copy available, like the other stores' APIs
    assert all(any(v.in_stock for v in r.variants) for r in recs)


def test_card_keys_line_up_with_the_other_stores(fusion, real_crawl):
    with gzip.open(Path(__file__).parent / "games401_fastsimon.json.gz", "rt", encoding="utf-8") as f:
        k401 = {r.card_key for r in map(parse_401, json.load(f)) if r.card_key}
    kfus = {r.card_key for r in map(parse_item, fusion) if r.card_key}
    ktrin = {r.card_key for r in map(parse_trinity, real_crawl) if r.card_key}
    assert (len(kfus), len(kfus & ktrin), len(kfus & k401), len(kfus & ktrin & k401)) == (13825, 4166, 11456, 3723)
