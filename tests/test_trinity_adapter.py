"""Trinity (USF) adapter quirks, each checked on a real item from the saved crawl (tests/trinity_yugioh_usf.json.gz).

Synthetic edge cases live in test_parser.py; these pin down what the parser does with the store's actual data.
"""
from collections import Counter

import pytest

from parser import parse_item


@pytest.fixture(scope="module")
def by_id(real_crawl):
    return {r["id"]: r for r in real_crawl}


def parsed(by_id, pid):
    return parse_item(by_id[pid])


def variants(rec):
    return [(v.condition, v.edition, v.quantity, v.in_stock) for v in rec.variants]


def test_condition_option_layout_with_edition_in_title(by_id):
    # ~2,300 items: option name "Condition", plain values ("Near Mint"); edition comes from the tags
    r = parsed(by_id, 9985940619511)  # Dominus Impulse (Starlight Rare) [BLGG-EN146] - ... 1st Edition - Starlight Rare
    assert by_id[9985940619511]["options"][0]["name"] == "Condition"
    assert r.card_key == "BLGG-EN146|starlight-rare|1st-edition|base" and r.name == "Dominus Impulse"
    assert variants(r)[:2] == [("NM", "1st Edition", 1, True), ("LP", "1st Edition", 0, False)]
    assert r.set_name == "Battles of Legend: Glorious Gallery" and not r.problems


def test_title_option_layout_condition_plus_edition(by_id):
    r = parsed(by_id, 7940843929847)  # Blue-Eyes White Dragon [GLD5-EN001] Ghost/Gold Rare
    assert by_id[7940843929847]["options"][0]["name"] == "Title"
    assert r.card_key == "GLD5-EN001|ghost-gold-rare|limited|base"
    assert variants(r)[:3] == [("NM", "Limited", 0, False), ("LP", "Limited", 1, True), ("MP", "Limited", 0, False)]
    assert [v.condition for v in r.variants] == ["NM", "LP", "MP", "HP", "DMG"]


def test_rarity_from_title_abbreviation_when_tags_have_none(by_id):
    r = parsed(by_id, 9596349972727)  # Odd-Eyes Pendulum Dragon (UR) [LEDD-ENC01] Ultra Rare
    assert (r.rarity, r.art_label, r.card_number) == ("Ultra Rare", None, "LEDD-ENC01")


@pytest.mark.parametrize("pid,label,key", [
    (7941167513847, "Green", "DL11-EN019|rare|unlimited|green"),
    (10072597594359, "Extended Art", "MAMO-EN016|starlight-rare|1st-edition|extended-art"),
    (7941424251127, "Redemption Replacement", "MDP2-EN006K|rare|unlimited|redemption-replacement"),
    (9672516600055, "MISCENTERED", "RA04-EN048|quarter-century-secret-rare|1st-edition|miscentered"),
])
def test_art_and_version_labels_get_their_own_card_key(by_id, pid, label, key):
    r = parsed(by_id, pid)
    assert (r.art_label, r.card_key) == (label, key)


def test_rarity_parenthetical_is_not_an_art_label(by_id):
    r = parsed(by_id, 10072597594359)  # (Starlight Rare) (Extended Art)
    assert r.rarity == "Starlight Rare" and r.art_label == "Extended Art"


def test_old_code_without_language_and_unconfirmed_quantity(by_id):
    r = parsed(by_id, 7940947738871)  # Heavy Storm [MRD-142] Super Rare, LP variant available = -1
    assert (r.card_number, r.language, r.set_code) == ("MRD-142", "", "MRD")
    assert ("LP", "Unlimited", -1, True) in variants(r) and not r.problems


def test_oversold_quantity_from_the_real_crawl(by_id):
    r = parsed(by_id, 7940329079031)  # Number 39: Utopia Double [DUPO-EN008], NM available = -2
    assert ("NM", -2, False) in [(v.condition, v.quantity, v.in_stock) for v in r.variants]
    assert r.problems == ["negative_quantity:-2"] and r.card_key is not None


@pytest.mark.parametrize("pid,number", [(7940842160375, "GENF-ENSE1"), (7941424251127, "MDP2-EN006K")])
def test_special_card_numbers(by_id, pid, number):
    assert parsed(by_id, pid).card_number == number


def test_prefixed_tag_style_is_read_like_classic_tags(by_id):
    # tags "Rarity_Quarter Century Secret Rare" / "Printing_1st Edition" (one item on the 2026 crawl)
    r = parsed(by_id, 9672516600055)
    assert (r.rarity, r.card_key.split("|")[2]) == ("Quarter Century Secret Rare", "1st-edition")


def test_no_rarity_is_quarantined_not_guessed(by_id):
    r = parsed(by_id, 7941423431927)  # Waboku (Duel Terminal) [HAC1-EN026] Common
    assert r.card_key is None and r.problems == ["no_rarity"]
    assert len(r.variants) == 5  # still tracked as a listing


def test_missing_set_name_tag_keeps_the_card_key(by_id):
    r = parsed(by_id, 9496937627895)  # Dark Magician [RP01-EN003] Ultra Rare, no YGO_ tag
    assert r.set_name is None and r.card_key == "RP01-EN003|ultra-rare|unlimited|base"
    assert r.problems == ["no_set_name"]


def test_item_without_option_values_keeps_variant_with_unknown_condition(by_id):
    r = parsed(by_id, 10001299833079)  # The Black Stone of Legend ... - PSA 7
    assert r.problems == ["no_option_values", "variant_option_index_unresolved"]
    assert [v.condition for v in r.variants] == [None]


def test_variant_key_is_variant_id_even_when_sku_is_missing(by_id):
    r = parsed(by_id, 9985940619511)
    assert [v.sku is None for v in r.variants][:3] == [False, True, True]
    assert len({v.variant_id for v in r.variants}) == len(r.variants)


def test_real_crawl_problem_breakdown(real_crawl):
    recs = [parse_item(r) for r in real_crawl]
    kinds = Counter(p.split(":")[0] for r in recs for p in r.problems)
    assert kinds == {"no_rarity": 67, "no_set_name": 8, "no_option_values": 1, "variant_option_index_unresolved": 1,
                     "negative_quantity": 1}
    keys = Counter(r.card_key for r in recs if r.card_key)
    assert sum(1 for n in keys.values() if n > 1) == 13  # same card listed twice: allowed
    assert {v.condition for r in recs for v in r.variants} == {"NM", "LP", "MP", "HP", "DMG", None}
