"""Card identity shared by all stores, and the Trinity Hobby (Hotyon USF) adapter.

Shared (every store adapter must use these so the same card gets the same card_key): CardRec / VariantRec,
make_card_key, art_label_from, _slug, _is_rarity_text, GRADE_RE, PAREN_RE.
Trinity-specific: parse_item (raw USF item -> CardRec). Other stores live in their own adapter module.
"""
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
# A newer tag style prefixes some values ("Rarity_Quarter Century Secret Rare", "Printing_1st Edition");
# 1 item on the 2026 crawl. Stripped so they read like the classic tags.
TAG_VALUE_PREFIXES = ("rarity_", "printing_")
CODE_RE = re.compile(r"\[([A-Z0-9]{2,6})-(?:([A-Z]{2})([A-Z]*))?(\d{1,4}[A-Z]?)\]")
RARITY_ABBR = {"UR": "Ultra Rare", "SR": "Super Rare", "SCR": "Secret Rare", "R": "Rare",
               "C": "Common", "CR": "Collector's Rare", "UTR": "Ultimate Rare", "GR": "Gold Rare",
               "PS": "Platinum Secret Rare", "QCSR": "Quarter Century Secret Rare",
               # seen at 401 Games: "Dominus Impulse (PCR) - RA05-EN080 - Prismatic Collector's Rare - 1st Edition"
               "PCR": "Prismatic Collector's Rare", "PUR": "Prismatic Ultimate Rare", "EUR": "Emblazoned Ultra Rare",
               "PSR": "Prismatic Secret Rare", "ESR": "Emblazoned Secret Rare"}
PAREN_RE = re.compile(r"\(([^()]*)\)")
# Graded slabs ("... Ultra Rare - PSA 7") are a different product from raw copies: quarantined, never keyed.
GRADE_RE = re.compile(r"\b(PSA|BGS|CGC|SGC|Beckett)\s*(10|[1-9](?:\.5)?)\b")
PLAIN_RARITIES = ("common", "short print", "super short print")


def _is_rarity_text(s: str) -> bool:
    s = s.lower()
    return "rare" in s or s in PLAIN_RARITIES or s.endswith(" common")  # e.g. "Duel Terminal Technology Common"


@dataclass
class VariantRec:
    variant_id: int
    sku: str | None
    condition: str | None      # NM/LP/MP/PL/HP/DMG or None if unrecognised
    edition: str | None        # per variant: one listing can hold 1st Edition and Unlimited copies
    price: float
    quantity: int | None       # raw stock count (Trinity: -1 = unconfirmed); None when the store doesn't say
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
    title: str = ""            # the store's product title as received (listings.title_raw)
    image_url: str | None = None  # the store's product image (absolute https URL)


def _split_condition(label: str):
    s = label.strip()
    edition = None
    for e in EDITIONS:
        if s.lower().endswith(e.lower()):
            edition, s = e, s[: -len(e)].strip()
            break
    return CONDITIONS.get(s.lower()), edition


def _normalise_tags(tags: list[str]) -> list[str]:
    out = []
    for t in tags:
        for p in TAG_VALUE_PREFIXES:
            if t.lower().startswith(p):
                t = t[len(p):]
                break
        out.append(t)
    return out


def _rarity(tags: list[str]) -> str | None:
    c = [t for t in tags
         if t.lower() not in NON_RARITY and not t.lower().startswith(NON_RARITY_PREFIX) and _is_rarity_text(t)]
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


def _more_specific_rarity(rarity: str | None, parens: list[str]) -> str | None:
    """A title abbreviation that narrows the tagged rarity wins: Fusion tags "Garunix Eternity (ESR) [25LP-EN003]"
    only "Secret Rare", while ESR = Emblazoned Secret Rare (what 401 calls it). Never overrides a different rarity."""
    for p in parens:
        full = RARITY_ABBR.get(p)
        if full and rarity and full != rarity and full.lower().endswith(" " + rarity.lower()):
            return full
    return rarity


def _rarity_from_title_suffix(title: str) -> str | None:
    """Rarity printed after the code: "[HAC1-EN026] Common" or "[PHRE-EN039] - Phantom Revenge ... - Ultra Rare".

    Only accepted when it reads as a rarity; anything else ("Promo") stays unknown.
    """
    if "]" not in title:
        return None
    after = GRADE_RE.sub("", PAREN_RE.sub("", title.split("]", 1)[1])).strip(" -")
    last = after.rsplit(" - ", 1)[-1].strip()
    return last if last and _is_rarity_text(last) else None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def art_label_from(parens: list[str], rarity: str | None) -> str | None:
    """Art / alt-version qualifier: title parentheticals that are not the rarity or a short form of it
    ("(Ghost)" on a Ghost Rare, "(Duel Terminal)" on a Duel Terminal Technology Common, "(UR)")."""
    rar_l = (rarity or "").lower()
    art = [p for p in parens
           if p.lower() != rar_l and not rar_l.startswith(p.lower() + " ")
           and p not in RARITY_ABBR and "rare" not in p.lower()]
    return "; ".join(art) or None


def https_url(url: str | None) -> str | None:
    """Store image links come as "//cdn.shopify.com/..." or full URLs; always return an absolute https URL."""
    if not url:
        return None
    return "https:" + url if url.startswith("//") else url


def _first_image(item: dict) -> str | None:
    images = item.get("images") or []
    return https_url(images[0].get("url")) if images and isinstance(images[0], dict) else None


def make_card_key(card_number: str | None, rarity: str | None, art_label: str | None) -> str | None:
    """The cross-store identity, e.g. "DIFO-EN070|super-rare|base". None when it can't be built (quarantine).
    Edition is not part of it: it lives on each variant."""
    if not card_number or not rarity:
        return None
    return "|".join([card_number, _slug(rarity), _slug(art_label) if art_label else "base"])


def parse_item(item: dict) -> CardRec:
    probs: list[str] = []
    title = item["title"]
    tags = _normalise_tags(item.get("tags") or [])

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
    # most specific first: tags, then a parenthetical, then the text printed after the code
    rarity = _rarity(tags) or _rarity_from_title(parens) or _rarity_from_title_suffix(title)
    rarity = _more_specific_rarity(rarity, parens)
    if not rarity:
        probs.append("no_rarity")
    graded = GRADE_RE.search(title)
    if graded:
        probs.append(f"graded:{graded.group(1)} {graded.group(2)}")
    art_label = art_label_from(parens, rarity)
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
        # the variant's own label wins over the listing's tag (1,954 Trinity listings mix editions)
        variants.append(VariantRec(v["id"], v.get("sku"), cond, ed or tag_ed,
                                   float(price), qty, qty > 0 or qty == -1))
    if len(variants) != len(item["variants"]):
        probs.append("variants_dropped")

    # Edition is not part of the card: it lives on each variant (see VariantRec.edition).
    key = None if graded or not m else make_card_key(f"{set_code}-{lang}{number}", rarity, art_label)
    return CardRec(item["id"], item.get("urlName", ""), name, set_code, lang,
                   f"{set_code}-{lang}{number}" if m else None, set_name, rarity, art_label, key,
                   variants, probs, title=title, image_url=_first_image(item))
