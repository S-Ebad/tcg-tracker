"""Parse raw Trinity Hobby (Hotyon USF) Yu-Gi-Oh items into clean records."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CONDITIONS = {
    "near mint": "NM", "lightly played": "LP", "moderately played": "MP",
    "heavily played": "HP", "damaged": "DMG",
}
EDITIONS = ("1st Edition", "Unlimited", "Limited")
# tags that are never a rarity
NON_RARITY = {
    "singles", "yugioh", "tcg", "main deck monster", "extra deck monster", "spell", "trap",
    "normal monster", "light", "dark", "earth", "water", "fire", "wind", "divine",
    "promo", "spellcaster", "dragon", "quarter century bonanza",
} | {e.lower() for e in EDITIONS}
NON_RARITY_PREFIX = ("ygo_", "attack_", "defense_", "level_", "monster type_",
                     "attribute_", "card type_", "printing_")
CODE_RE = re.compile(r"\[([A-Z0-9]{2,6})-(?:([A-Z]{2})([A-Z]*))?(\d{1,4}[A-Z]?)\]")
RARITY_ABBR = {"UR": "Ultra Rare", "SR": "Super Rare", "SCR": "Secret Rare", "R": "Rare",
               "C": "Common", "CR": "Collector's Rare", "UTR": "Ultimate Rare", "GR": "Gold Rare",
               "PS": "Platinum Secret Rare", "QCSR": "Quarter Century Secret Rare"}
PAREN_RE = re.compile(r"\(([^()]*)\)")


@dataclass
class VariantRec:
    variant_id: int
    sku: str | None
    condition: str | None      # NM/LP/MP/HP/DMG or None if unrecognised
    edition: str | None
    price: float
    quantity: int              # raw "available"; -1 = untracked/unconfirmed, counted as in stock
    in_stock: bool


@dataclass
class CardRec:
    product_id: int
    url_name: str
    name: str
    set_code: str | None
    language: str | None
    card_number: str | None
    set_name: str | None
    rarity: str | None
    art_label: str | None
    card_key: str | None       # canonical cross-store key
    variants: list[VariantRec] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _split_condition(label: str):
    s = label.strip()
    edition = None
    for e in EDITIONS:
        if s.lower().endswith(e.lower()):
            edition, s = e, s[: -len(e)].strip()
            break
    return CONDITIONS.get(s.lower()), edition


def _rarity(tags: list[str]) -> str | None:
    c = [t for t in tags
         if t.lower() not in NON_RARITY and not t.lower().startswith(NON_RARITY_PREFIX)
         and ("rare" in t.lower() or t.lower() in ("common", "short print", "super short print"))]
    return c[0] if len(c) == 1 else (None if not c else sorted(c, key=len)[-1])


def _title_parens(title: str) -> list[str]:
    return [p.strip() for p in PAREN_RE.findall(title.split("[")[0])]


def _rarity_from_title(parens: list[str]) -> str | None:
    for p in parens:
        if p in RARITY_ABBR:
            return RARITY_ABBR[p]
        if "rare" in p.lower():
            return p
    return None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def parse_item(item: dict) -> CardRec:
    probs: list[str] = []
    title = item["title"]
    tags = item.get("tags") or []

    m = CODE_RE.search(title)
    set_code = lang = number = None
    if m:
        set_code, lang, number = m.group(1), m.group(2) or "", (m.group(3) or "") + m.group(4)
    else:
        probs.append("no_set_code")
    name = PAREN_RE.sub("", title.split(" [")[0]).strip() if m else title.strip()
    name = re.sub(r"\s{2,}", " ", name)

    set_name = next((t[4:] for t in tags if t.startswith("YGO_")), None)
    if not set_name:
        probs.append("no_set_name")
    parens = _title_parens(title)
    rarity = _rarity(tags) or _rarity_from_title(parens)
    if not rarity:
        probs.append("no_rarity")
    # art / alt-version qualifier: parentheticals that are not the rarity
    rar_l = (rarity or "").lower()
    art = [p for p in parens
           if p.lower() != rar_l and p not in RARITY_ABBR and "rare" not in p.lower()]
    art_label = "; ".join(art) or None
    tag_ed = next((t for t in tags if t in EDITIONS), None)

    opts = item.get("options") or []
    values = opts[0]["values"] if opts else []
    if not values:
        probs.append("no_option_values")

    variants: list[VariantRec] = []
    for v in item["variants"]:
        idx = (v.get("options") or [None])[0]
        label = values[idx] if isinstance(idx, int) and 0 <= idx < len(values) else None
        cond, ed = _split_condition(label) if label else (None, None)
        if label is None:
            probs.append("variant_option_index_unresolved")
        elif cond is None:
            probs.append(f"unknown_condition:{label}")
        price = v.get("price")
        if not price or price <= 0:
            probs.append("bad_price")
            continue
        qty = v.get("available", 0)
        if not isinstance(qty, int) or isinstance(qty, bool):
            probs.append(f"bad_quantity:{qty!r}")
            continue
        # available = -1: Shopify's "inventory not tracked / unconfirmed" (5 of 62,710 variants on the 2026 crawl).
        # Assumption: such a variant is listed and purchasable, so it counts as in stock; -1 is stored unchanged.
        # Below -1 would mean oversold: kept raw, out of stock, and flagged.
        if qty < -1:
            probs.append(f"negative_quantity:{qty}")
        variants.append(VariantRec(v["id"], v.get("sku"), cond, ed or tag_ed,
                                   float(price), qty, qty > 0 or qty == -1))
    if len(variants) != len(item["variants"]):
        probs.append("variants_dropped")

    ed_key = tag_ed or next((x.edition for x in variants if x.edition), None)
    key = None
    if set_code and number and rarity:
        key = "|".join([f"{set_code}-{lang}{number}", _slug(rarity), _slug(ed_key or "unknown"),
                         _slug(art_label) if art_label else "base"])
    return CardRec(item["id"], item.get("urlName", ""), name, set_code, lang,
                   f"{set_code}-{lang}{number}" if m else None, set_name, rarity, art_label, key,
                   variants, probs)
