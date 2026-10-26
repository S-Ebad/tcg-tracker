from parser import parse_item


def item(title, tags, values, variants):
    return {"id": 1, "urlName": "x", "title": title, "tags": tags,
            "options": [{"name": "Title", "values": values}],
            "variants": [{"id": i, "sku": None, "available": a, "price": p, "options": [i]}
                         for i, (a, p) in enumerate(variants)]}


def test_basic_card():
    r = parse_item(item("Therion Cross [DIFO-EN070] Super Rare",
                        ["1st Edition", "Super Rare", "YGO_Dimension Force"],
                        ["Near Mint 1st Edition", "Lightly Played 1st Edition"], [(3, 0.6), (0, 0.5)]))
    assert (r.set_code, r.card_number, r.rarity, r.set_name) == ("DIFO", "DIFO-EN070", "Super Rare", "Dimension Force")
    assert [(v.condition, v.edition, v.in_stock) for v in r.variants] == [("NM", "1st Edition", True), ("LP", "1st Edition", False)]
    assert r.card_key == "DIFO-EN070|super-rare|1st-edition|base" and not r.problems


def test_letter_suffix_and_special_prefix_codes():
    assert parse_item(item("X [MDP2-EN006K] Rare", ["Rare", "YGO_S"], ["Near Mint"], [(1, 1)])).card_number == "MDP2-EN006K"
    assert parse_item(item("X [GENF-ENSE1] Super Rare", ["Super Rare", "YGO_S"], ["Near Mint"], [(1, 1)])).card_number == "GENF-ENSE1"


def test_old_style_code_without_language():
    r = parse_item(item("Heavy Storm [MRD-142] Super Rare", ["Super Rare", "YGO_S"], ["Near Mint"], [(1, 1)]))
    assert r.card_number == "MRD-142" and r.set_code == "MRD"


def test_art_variants_get_different_keys():
    a = parse_item(item("Starjunk Synchron (Extended Art) [MAMO-EN008] Ultra Rare", ["Ultra Rare", "YGO_S", "1st Edition"], ["Near Mint"], [(1, 1)]))
    b = parse_item(item("Starjunk Synchron [MAMO-EN008] Ultra Rare", ["Ultra Rare", "YGO_S", "1st Edition"], ["Near Mint"], [(1, 1)]))
    assert a.card_key != b.card_key and a.name == b.name == "Starjunk Synchron"


def test_rarity_from_title_abbreviation():
    assert parse_item(item("Odd-Eyes (UR) [LEDD-EN001]", ["YGO_S"], ["Near Mint"], [(1, 1)])).rarity == "Ultra Rare"


def test_unconfirmed_quantity_minus_one_is_kept_raw_and_counts_as_in_stock():
    r = parse_item(item("X [AAAA-EN001] Rare", ["Rare", "YGO_S"], ["Near Mint"], [(-1, 1)]))
    assert (r.variants[0].quantity, r.variants[0].in_stock) == (-1, True) and not r.problems


def test_oversold_quantity_is_kept_out_of_stock_and_flagged():
    r = parse_item(item("X [AAAA-EN001] Rare", ["Rare", "YGO_S"], ["Near Mint"], [(-3, 1)]))
    assert (r.variants[0].quantity, r.variants[0].in_stock) == (-3, False)
    assert r.problems == ["negative_quantity:-3"]


def test_non_integer_quantity_drops_the_variant_and_is_flagged():
    r = parse_item(item("X [AAAA-EN001] Rare", ["Rare", "YGO_S"], ["Near Mint"], [(None, 1)]))
    assert r.variants == [] and r.problems == ["bad_quantity:None", "variants_dropped"]


def test_real_crawl_quality_threshold(real_crawl):
    recs = [parse_item(x) for x in real_crawl]
    assert len(recs) == 11793
    bad = sum(1 for r in recs if r.problems)
    assert bad / len(recs) < 0.01, f"{bad} items with parse problems"
    assert sum(1 for r in recs if r.card_key is None) / len(recs) < 0.01
