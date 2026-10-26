"""Fusion Gaming adapter: one Shopify products.json product (fusiongamingonline.com, BinderPOS) -> CardRec.

Fusion's listings follow the same BinderPOS conventions as Trinity's ("Bottomless Trap Hole [GEIM-EN045] Rare",
option "Title" with values like "Near Mint 1st Edition", rarity and edition tags), so the product is reshaped into the
USF item form and parsed by parser.parse_item. Differences handled here:
  - Shopify's storefront feed has no stock counts, only `available` per variant: quantity None, in_stock = available.
  - Out-of-stock products are listed too (most variants are unavailable), unlike Trinity's in-stock-only API.
  - No YGO_ set-name tag: the set name is one of ~680 mixed tags and isn't guessed, so set_name stays None and
    "no_set_name" is not a problem for this store (the set code in the card number identifies the set).
"""
from __future__ import annotations

import parser
from parser import CardRec


def to_usf_shape(product: dict) -> tuple[dict, dict[int, bool]]:
    """(item in the shape parser.parse_item reads, variant id -> available)."""
    values = (product.get("options") or [{}])[0].get("values") or []
    variants, available = [], {}
    for v in product.get("variants") or []:
        label = v.get("option1")
        try:
            price = float(v.get("price"))
        except (TypeError, ValueError):
            price = 0.0
        available[v["id"]] = v.get("available") is True
        variants.append({"id": v["id"], "sku": v.get("sku") or None, "price": price,
                         # parse_item needs an int stock figure; the real one is unknown and replaced below
                         "available": 1 if available[v["id"]] else 0,
                         "options": [values.index(label)] if label in values else []})
    item = {"id": product["id"], "title": product["title"], "tags": product.get("tags") or [],
            "urlName": product.get("handle", ""), "options": [{"name": "Title", "values": values}] if values else [],
            "variants": variants}
    return item, available


def parse_item(product: dict) -> CardRec:
    item, available = to_usf_shape(product)
    rec = parser.parse_item(item)
    for v in rec.variants:
        v.quantity = None
        v.in_stock = available.get(v.variant_id, False)
    rec.problems = [p for p in rec.problems if p != "no_set_name"]
    if product.get("product_type") != "Yugioh Single":
        rec.problems.append(f"not_a_single:{product.get('product_type')}")
        rec.card_key = None
    return rec
