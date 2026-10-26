"""401 Games (Fast Simon) adapter, checked on real items from the saved crawl (tests/games401_fastsimon.json.gz,
35,027 in-stock Yu-Gi-Oh singles, 2026-10-26)."""
import gzip
import json
from collections import Counter
from pathlib import Path

import pytest

from adapter_401 import parse_edition_segment, parse_item
from parser import parse_item as trinity_parse

FIXTURE = Path(__file__).parent / "games401_fastsimon.json.gz"


@pytest.fixture(scope="module")
def crawl401() -> list[dict]:
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def by_id(crawl401):
    return {it["id"]: it for it in crawl401}


def summary(r):
    return (r.card_key, r.name, r.set_name, sorted({v.edition for v in r.variants}, key=str),
            [v.condition for v in r.variants], r.problems)


def test_plain_title_and_variants(by_id):
    r = parse_item(by_id["8529646977211"])  # Nightmare-Eyes Restrict - MAMO-EN122 - Secret Rare - 1st Edition
    assert summary(r) == ("MAMO-EN122|secret-rare|base", "Nightmare-Eyes Restrict", "Magnificent Monsters",
                          ["1st Edition"], ["NM", "PL", "HP"], [])
    assert [(v.price, v.quantity, v.in_stock) for v in r.variants] == [(2.0, None, True), (1.6, None, False),
                                                                        (1.2, None, False)]
    assert r.title == by_id["8529646977211"]["l"] and r.url_name and r.product_id == 8529646977211


def test_card_name_containing_a_dash(by_id):
    r = parse_item(by_id["8529651040443"])  # Divine Arsenal AA-ZEUS - Sky Thunder - MAMO-EN035 - Starlight Rare - ...
    assert (r.name, r.card_key) == ("Divine Arsenal AA-ZEUS - Sky Thunder", "MAMO-EN035|starlight-rare|base")


def test_rarity_abbreviation_in_parentheses_is_not_art(by_id):
    r = parse_item(by_id["8385627259067"])  # Dominus Impulse (PCR) - RA05-EN080 - Prismatic Collector's Rare - ...
    assert (r.card_key, r.art_label) == ("RA05-EN080|prismatic-collector-s-rare|base", None)


@pytest.mark.parametrize("pid,key,edition", [
    ("6959137587387", "LOB-EN001|ultra-rare|25th-anniversary", "Unlimited"),  # 25th Anniversary Edition Unlimited
    ("8156827156667", "LDK2-ENY04|common|2020-reprint", "Unlimited"),          # Unlimited (2020 Reprint)
    ("7327618465979", "PTDN-ENSP1|super-rare|base", "Limited"),                # Limited Edition (set tag: 1st Ed.)
    ("6982971195579", "LODT-EN052|ultimate-rare|base", "Unlimited"),           # Unlimited Worldwide
    ("3957578629195", "SBSC-ENS05|ultra-rare|base", "1st Edition"),            # 1st Edition (Skill Card)
    ("6937355026619", "SDP-001|ultra-rare|base", "1st Edition"),               # old code without language
])
def test_edition_endings(by_id, pid, key, edition):
    r = parse_item(by_id[pid])
    assert (r.card_key, {v.edition for v in r.variants}, r.problems) == (key, {edition}, [])


def test_sets_that_print_no_edition_stay_unknown(by_id):
    r = parse_item(by_id["11836637839"])  # Snatch Steal - DB1-EN021 - Ultra Rare (Dark Beginning 1)
    assert r.card_key == "DB1-EN021|ultra-rare|base" and {v.edition for v in r.variants} == {None}


def test_graded_slab_without_psa_in_the_title_is_quarantined(by_id):
    r = parse_item(by_id["8505755074747"])  # The Winged Dragon of Ra (000) - LED7 1st Edition - Ghost Rare - Mint 9
    assert r.card_key is None and "graded:Mint 9" in r.problems


def test_sealed_envelope_listed_as_a_single_is_quarantined(by_id):
    r = parse_item(by_id["7680948109499"])
    assert r.card_key is None and {"no_set_code", "no_rarity"} <= set(r.problems)


@pytest.mark.parametrize("seg,expected", [
    ("1st Edition", ("1st Edition", None)), ("Limited Edition", ("Limited", None)),
    ("25th Anniversary Edition Unlimited", ("Unlimited", "25th Anniversary")),
    ("Unlimited (2020 Reprint)", ("Unlimited", "2020 Reprint")), ("Unlimited Worldwide", ("Unlimited", None)),
    ("1st Edition (Skill Card)", ("1st Edition", None)), ("Ultra Rare", (None, None)),
])
def test_edition_segment(seg, expected):
    assert parse_edition_segment(seg) == expected


def test_whole_crawl(crawl401):
    recs = [parse_item(it) for it in crawl401]
    assert len(recs) == 35027
    kinds = Counter(p.split(":")[0] for r in recs for p in r.problems)
    assert kinds == {"unknown_condition": 33, "no_set_code": 21, "no_rarity": 15, "graded": 10, "no_set_name": 5}
    assert sum(1 for r in recs if r.problems) / len(recs) < 0.002
    assert sum(1 for r in recs if r.card_key is None) == 21
    assert {v.condition for r in recs for v in r.variants} == {"NM", "PL", "HP", "MP", None}
    assert all(v.quantity is None for r in recs for v in r.variants)


def test_card_keys_line_up_with_trinity(crawl401, real_crawl):
    k401 = {r.card_key for r in map(parse_item, crawl401) if r.card_key}
    trin = [trinity_parse(r) for r in real_crawl]
    ktrin = {r.card_key for r in trin if r.card_key}
    assert len(k401) == 30176 and len(k401 & ktrin) == 8987
    # of the card numbers both stores carry, nearly all share at least one exact key
    nums = {k.split("|")[0] for k in k401} & {k.split("|")[0] for k in ktrin}
    assert len({k.split("|")[0] for k in k401 & ktrin}) / len(nums) > 0.95
