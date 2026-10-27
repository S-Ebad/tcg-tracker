"""Hobbiesville adapter, checked on real products from the saved crawl (tests/hobbiesville_products.json.gz,
4,233 Yu-Gi-Oh singles from the collection's products.json, 2026-10-26)."""
import gzip
import json
from collections import Counter
from pathlib import Path

import pytest

from adapter_401 import parse_item as parse_401
from adapter_hobbiesville import name_part, parse_item

FIXTURE = Path(__file__).parent / "hobbiesville_products.json.gz"


@pytest.fixture(scope="module")
def products() -> list[dict]:
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def by_title(products):
    return {p["title"]: p for p in products}


def test_card_data_comes_from_the_structured_tags(by_title):
    r = parse_item(by_title["Ten Thousand Dragon (BLAR-EN10K) 10000 Secret Rare  1st Edition"])
    assert r.card_key == "BLAR-EN10K|10000-secret-rare|base" and not r.problems
    assert r.name == "Ten Thousand Dragon" and r.set_name == "Battles of Legend: Armageddon"
    assert [v.condition for v in r.variants] == ["NM", "LP", "MP"]
    assert {v.edition for v in r.variants} == {"1st Edition"} and {v.quantity for v in r.variants} == {None}


def test_tag_rarity_wins_over_the_shorter_title_rarity(by_title):
    r = parse_item(by_title["Sophia, Goddess of Rebirth (DT07-EN079) Ultra Rare  Limited"])
    assert r.rarity == "Duel Terminal Ultra Parallel Rare" and r.variants[0].edition == "Limited"


@pytest.mark.parametrize("title,key", [
    # rarity restated in a parenthetical is not an art label
    ("Chaos Angel (Starlight Rare) - BLGG-EN143 Starlight Rare 1st Edition", "BLGG-EN143|starlight-rare|base"),
    ("Sky Striker Ace - Raye (Alternate Art) (Quarter Century Secret Rare) - BLTR-EN116 Quarter Century Secret Rare "
     "1st Edition", "BLTR-EN116|quarter-century-secret-rare|alternate-art"),
    # the third title shape, with the edition before the rarity
    ("Mirrorjade the Iceblade Dragon (Starlight Rare) - PHHY-EN100 - 1st Edition - Starlight Rare - Photon Hypernova",
     "PHHY-EN100|starlight-rare|base"),
    ("Nobleman of Crossout (Secret) (SBCB-EN138) Secret Rare  1st Edition", "SBCB-EN138|secret-rare|base"),
])
def test_title_shapes(by_title, title, key):
    assert parse_item(by_title[title]).card_key == key


def test_name_stops_at_the_card_number():
    assert name_part("Super Starslayer TY-PHON - Sky Crisis - MP24-EN119 Prismatic Secret Rare 1st Edition",
                     "MP24-EN119") == "Super Starslayer TY-PHON - Sky Crisis"
    assert name_part("Ten Thousand Dragon (BLAR-EN10K) 10000 Secret Rare", "BLAR-EN10K") == "Ten Thousand Dragon"


def test_number_tag_disagreeing_with_the_title_is_quarantined(by_title):
    r = parse_item(by_title["Token (Akiza) - L5DD-ENS04 Secret Rare 1st Edition"])  # tag says L5DD-ENS05
    assert r.card_key is None and r.problems == ["number_conflict:L5DD-ENS05"]


def test_old_code_without_a_two_letter_language_is_quarantined(by_title):
    r = parse_item(by_title["Neo the Magic Swordsman (MRL-E105) Common / Short Print  Unlimited"])
    assert r.card_key is None and r.problems == ["no_set_code"]


def test_whole_crawl(products):
    recs = [parse_item(p) for p in products]
    assert len(recs) == 4233 and all(p["product_type"] == "Single" for p in products)
    assert sum(1 for r in recs if r.card_key is None) == 4
    assert Counter(x.split(":")[0] for r in recs for x in r.problems) == {
        "no_set_code": 3, "no_rarity": 1, "number_conflict": 1}
    assert {v.condition for r in recs for v in r.variants} == {"NM", "LP", "MP"}
    assert {v.edition for r in recs for v in r.variants} == {"1st Edition", "Unlimited", "Limited"}
    assert all(r.image_url.startswith("https://cdn.shopify.com/") for r in recs if r.image_url)
    # unlike Fusion's feed, 69 products are listed with every condition sold out
    assert sum(1 for r in recs if not any(v.in_stock for v in r.variants)) == 69


def test_card_keys_line_up_with_401(products):
    with gzip.open(Path(__file__).parent / "games401_fastsimon.json.gz", "rt", encoding="utf-8") as f:
        g401 = {parse_401(i).card_key for i in json.load(f)} - {None}
    hv = {parse_item(p).card_key for p in products} - {None}
    numbers = {k.split("|")[0] for k in hv} & {k.split("|")[0] for k in g401}
    matched = {k.split("|")[0] for k in hv & g401}
    # misses are mostly a different printing of the same number (Starlight vs Ultra Rare), not a naming difference
    assert len(matched) / len(numbers) > 0.9
