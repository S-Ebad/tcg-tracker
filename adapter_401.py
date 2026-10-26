"""401 Games adapter: one Fast Simon item (Yu-Gi-Oh singles, 401games.ca) -> CardRec.

Item shape (api.fastsimon.com categories_navigation, with_product_attributes=true):
  id "8417621868731", l (title) "Nightmare-Eyes Restrict - MAMO-EN122 - Secret Rare - 1st Edition", u "/products/...",
  att [["Tag", ["Rarity_Secret Rare", "Set_Magnificent Monsters 1st Edition", "TCG_714650", ...]], ["Type", [...]]],
  vra [[variant_id, [["Condition", ["NM"]], ["Price", ["CAD:2.00"]], ["Sellable", [true]], ...]], ...]
Differences from Trinity: one product per edition (edition in the title), no stock quantities (only Sellable),
conditions NM / PLD / HP. Identity rules (card_key, art labels, grading) are the shared ones in parser.py.
"""
from __future__ import annotations

import re

from parser import (
    EDITIONS,
    GRADE_RE,
    PAREN_RE,
    CardRec,
    VariantRec,
    _is_rarity_text,
    art_label_from,
    https_url,
    make_card_key,
)

# "MAMO-EN122", "SDP-040", "GENF-ENSE1", "MDP2-EN006K" as a whole " - " segment of the title
CODE_SEG_RE = re.compile(r"^([A-Z0-9]{2,6})-(?:([A-Z]{2})([A-Z]*))?(\d{1,4}[A-Z]?)$")
# 401's grades. "PLD" (played) has no published definition matching LP or MP, so it is its own grade.
CONDITIONS = {"NM": "NM", "LP": "LP", "MP": "MP", "PLD": "PL", "PL": "PL", "HP": "HP", "DMG": "DMG"}
SINGLES_TYPE = "Yugioh Singles"
# Edition segment at the end of the title (2026-10-26 crawl): "1st Edition", "Unlimited", "Limited Edition" (714),
# "25th Anniversary Edition Unlimited" (541, reprints that reuse the original card numbers), "Unlimited (2020 Reprint)"
# (59), "Unlimited Worldwide" (56), "1st Edition (Skill Card)" (30).
EDITION_SEG_RE = re.compile(
    r"^(?P<anniv>25th Anniversary Edition )?(?P<ed>1st Edition|Unlimited|Limited)(?: Edition)?"
    r"(?: Worldwide)?(?: \((?P<note>[^()]+)\))?$")
# A reprint marker becomes a version label, like Trinity's "(25th Anniversary)", so reprints never share a key with
# the original printing. "Skill Card" is a card type the code already identifies.
IGNORED_NOTES = {"Skill Card"}
# Graded slabs without "PSA" in the title: "... - Mint 9", "... - GEM MT 10"
GRADE_WORDS_RE = re.compile(r"^(Gem MT|Gem Mint|Mint|NM-MT|EX-MT|VG-EX|Pristine|Black Label)\s*(10|[1-9](?:\.5)?)$",
                            re.I)


def parse_edition_segment(seg: str) -> tuple[str | None, str | None]:
    """(edition, version label) from a title segment, or (None, None) if it isn't an edition."""
    m = EDITION_SEG_RE.match(seg)
    if not m:
        return None, None
    edition = {"1st Edition": "1st Edition", "Unlimited": "Unlimited", "Limited": "Limited"}[m["ed"]]
    note = m["note"] if m["note"] not in IGNORED_NOTES else None
    version = "25th Anniversary" if m["anniv"] else note
    return edition, version


def _attrs(pairs) -> dict[str, list]:
    return {k: v for k, v in (pairs or [])}


def parse_item(item: dict) -> CardRec:
    probs: list[str] = []
    title = item["l"].strip()
    att = _attrs(item.get("att"))
    tags = att.get("Tag", [])

    segs = [s.strip() for s in title.split(" - ")]
    # the code is the last segment that looks like one (card names can contain " - ")
    code_i = next((i for i in range(len(segs) - 1, 0, -1) if CODE_SEG_RE.match(segs[i])), None)
    set_code = lang = number = None
    if code_i is None:
        probs.append("no_set_code")
        name_part, after = title, []
    else:
        m = CODE_SEG_RE.match(segs[code_i])
        set_code, lang, number = m.group(1), m.group(2) or "", (m.group(3) or "") + m.group(4)
        name_part, after = " - ".join(segs[:code_i]), segs[code_i + 1:]
    name = re.sub(r"\s{2,}", " ", PAREN_RE.sub("", name_part)).strip()
    parens = [p.strip() for p in PAREN_RE.findall(name_part)]

    title_ed, version = next((parse_edition_segment(s) for s in after if parse_edition_segment(s)[0]), (None, None))
    if version:
        parens.append(version)  # becomes part of the art / version label, e.g. "...|25th-anniversary"
    title_rarity = next((s for s in after if not parse_edition_segment(s)[0]
                         and _is_rarity_text(GRADE_RE.sub("", s).strip())), None)
    tag_rarity = next((t[len("Rarity_"):] for t in tags if t.startswith("Rarity_")), None)
    rarity = tag_rarity or title_rarity
    if not rarity:
        probs.append("no_rarity")

    set_tag = next((t[len("Set_"):] for t in tags if t.startswith("Set_")), None)
    set_ed = next((e for e in EDITIONS if set_tag and set_tag.endswith(" " + e)), None)
    set_name = set_tag[: -len(set_ed)].strip() if set_ed else set_tag
    if not set_name:
        probs.append("no_set_name")
    # the title is the more specific source: special printings (PTDN-ENSP1, "Limited Edition") sit in sets whose tag
    # carries the set's usual edition (189 on the 2026-10-26 crawl, all Limited vs 1st Edition)
    edition = title_ed or set_ed
    if title_ed and set_ed and title_ed != set_ed and title_ed != "Limited":
        probs.append(f"edition_conflict:{title_ed}/{set_ed}")

    graded = GRADE_RE.search(title) or GRADE_WORDS_RE.match(segs[-1])
    if graded:
        probs.append(f"graded:{graded.group(1)} {graded.group(2)}")
    if SINGLES_TYPE not in att.get("Type", []):
        probs.append(f"not_a_single:{','.join(att.get('Type', [])) or 'no type'}")

    variants: list[VariantRec] = []
    for vid, pairs in item.get("vra") or []:
        a = _attrs(pairs)
        raw_cond = (a.get("Condition") or [None])[0]
        cond = CONDITIONS.get(raw_cond)
        if cond is None:
            probs.append(f"unknown_condition:{raw_cond}")
        price_raw = (a.get("Price") or [""])[0]
        currency, _, amount = str(price_raw).partition(":")
        try:
            price = float(amount)
        except ValueError:
            price = 0.0
        if currency != "CAD" or price <= 0:
            probs.append(f"bad_price:{price_raw}")
            continue
        sellable = (a.get("Sellable") or [False])[0] is True
        variants.append(VariantRec(int(vid), None, cond, edition, price, None, sellable))
    if not variants:
        probs.append("no_variants")

    key = None
    if code_i is not None and not graded and SINGLES_TYPE in att.get("Type", []):
        key = make_card_key(f"{set_code}-{lang}{number}", rarity, art_label_from(parens, rarity))
    return CardRec(int(item["id"]), (item.get("u") or "").removeprefix("/products/"), name, set_code, lang,
                   f"{set_code}-{lang}{number}" if code_i is not None else None, set_name, rarity,
                   art_label_from(parens, rarity), key, variants, probs, title=title,
                   image_url=https_url(item.get("t")))
