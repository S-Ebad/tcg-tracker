"""Hobbiesville adapter: one Shopify products.json product (hobbiesville.com, Yu-Gi-Oh singles) -> CardRec.

Unlike the BinderPOS stores, Hobbiesville carries the card's data as structured "Key:Value" tags on every product
(2026-10-26 crawl, 4,233 products): Number:BLAR-EN10K, Rarity:10000 Secret Rare, Printing:1st Edition|Unlimited|
Limited, Set:Battles of Legend: Armageddon. Those are the primary source. The title is only used for the name and for
art / version parentheticals in front of the card number. Titles come in three shapes:
  "Ten Thousand Dragon (BLAR-EN10K) 10000 Secret Rare  1st Edition"
  "Chaos Angel (Starlight Rare) - BLGG-EN143 Starlight Rare 1st Edition"
  "Mirrorjade the Iceblade Dragon (Starlight Rare) - PHHY-EN100 - 1st Edition - Starlight Rare - Photon Hypernova"
One product per printing (edition from the Printing tag), three variants NM / LP / MP with only an `available` flag
(no quantities). Identity rules (card_key, art labels, grading) are the shared ones in parser.py.
"""
from __future__ import annotations

import re

from parser import (
    GRADE_RE,
    PAREN_RE,
    CardRec,
    VariantRec,
    _is_rarity_text,
    _more_specific_rarity,
    art_label_from,
    https_url,
    make_card_key,
)

CODE_RE = re.compile(r"^([A-Z0-9]{2,6})-(?:([A-Z]{2})([A-Z]*))?(\d{1,4}[A-Z]?)$")
CONDITIONS = {"NM": "NM", "LP": "LP", "MP": "MP", "HP": "HP", "DMG": "DMG"}
EDITIONS = {"1st Edition", "Unlimited", "Limited"}
SINGLES_TYPE = "Single"


def tag_values(tags: list[str], key: str) -> list[str]:
    return [t[len(key) + 1:].strip() for t in tags if t.startswith(key + ":")]


def name_part(title: str, number: str) -> str:
    """Title text in front of the card number: "Chaos Angel (Starlight Rare)" from "... - BLGG-EN143 ..." or
    "Ten Thousand Dragon" from "Ten Thousand Dragon (BLAR-EN10K) ..."."""
    i = title.find(number)
    if i < 0:
        return title
    head = title[:i].rstrip()
    return head[:-1].rstrip() if head.endswith(("(", "-")) else head


def parse_item(product: dict) -> CardRec:
    probs: list[str] = []
    title = product["title"].strip()
    tags = product.get("tags") or []

    numbers = tag_values(tags, "Number")
    m = CODE_RE.match(numbers[0]) if len(numbers) == 1 else None
    set_code = lang = number = card_number = None
    if m:
        set_code, lang, number = m.group(1), m.group(2) or "", (m.group(3) or "") + m.group(4)
        card_number = f"{set_code}-{lang}{number}"
        if card_number not in title:
            probs.append(f"number_conflict:{card_number}")
    else:
        probs.append("no_set_code")
    head = name_part(title, numbers[0]) if numbers else title
    name = re.sub(r"\s{2,}", " ", PAREN_RE.sub("", head)).strip(" -")
    # parentheticals in front of the number; a bracketed copy of the number itself ("(MRL-E130) (MRL-E130)") isn't one
    parens = [p.strip() for p in PAREN_RE.findall(head) if p.strip() and not CODE_RE.match(p.strip())]

    rarities = [r.replace("’", "'").replace("�", "'") for r in tag_values(tags, "Rarity")]
    rarity = rarities[0] if len(rarities) == 1 and _is_rarity_text(rarities[0]) else None
    rarity = _more_specific_rarity(rarity, parens)
    if not rarity:
        probs.append(f"no_rarity:{'/'.join(rarities)}" if rarities else "no_rarity")

    printings = tag_values(tags, "Printing")
    edition = printings[0] if len(printings) == 1 and printings[0] in EDITIONS else None
    if edition is None:
        probs.append(f"no_edition:{'/'.join(printings)}")
    set_name = (tag_values(tags, "Set") or [None])[0]
    if not set_name:
        probs.append("no_set_name")

    graded = GRADE_RE.search(title)
    if graded:
        probs.append(f"graded:{graded.group(1)} {graded.group(2)}")
    if product.get("product_type") != SINGLES_TYPE:
        probs.append(f"not_a_single:{product.get('product_type')}")

    variants: list[VariantRec] = []
    for v in product.get("variants") or []:
        cond = CONDITIONS.get((v.get("option1") or "").strip())
        if cond is None:
            probs.append(f"unknown_condition:{v.get('option1')}")
        try:
            price = float(v.get("price"))
        except (TypeError, ValueError):
            price = 0.0
        if price <= 0:
            probs.append(f"bad_price:{v.get('price')}")
            continue
        variants.append(VariantRec(v["id"], v.get("sku") or None, cond, edition, price, None,
                                   v.get("available") is True))
    if not variants:
        probs.append("no_variants")

    art_label = art_label_from(parens, rarity)
    key = None
    if m and not graded and product.get("product_type") == SINGLES_TYPE and not any(
            p.startswith("number_conflict") for p in probs):
        key = make_card_key(card_number, rarity, art_label)
    images = product.get("images") or []
    return CardRec(product["id"], product.get("handle", ""), name, set_code, lang, card_number, set_name, rarity,
                   art_label, key, variants, probs, title=title,
                   image_url=https_url(images[0].get("src")) if images else None)
