# Second store: research (2026-10-26)

No code. About 40 polite requests in total: homepages, robots.txt, `agents.md`, Shopify `/collections.json`, and one or
two data samples per store. Contact address in the User-Agent throughout.

## Candidates

| Store | Platform / search | Yu-Gi-Oh singles | Data access | Verdict |
|---|---|---|---|---|
| **401 Games** (Toronto) | Shopify + **Fast Simon** | 57,952 singles; 35,315 Yu-Gi-Oh products in stock | Fast Simon JSON API: plain GET, store id + UUID from the homepage, in-stock facet, 50 per page | **Recommended** |
| **Fusion Gaming** | Shopify + BinderPOS + Boost | 13,889 (incl. out of stock) | `products.json` works (under the 25,000 cap, 250 per page, ~56 requests). Boost API returned 403 | Good second choice |
| **Face to Face Games** (Montreal) | Shopify, Search & Discovery | 59,159 | Only Shopify itself: `products.json` stops at 25,000, no third-party API, no tags | Most work, most fragile |
| Hairy Tarantula | Shopify + BinderPOS + Boost | none (Magic / Pokémon store) | — | Dropped |
| Game Knight, Wizard's Tower | Shopify | 58 and 75 products | — | Dropped (barely any Yu-Gi-Oh online) |
| Dolly's, Gauntlet Games | Crystal Commerce | not measured | HTML only, no `agents.md` | Not probed further |

All six Shopify stores serve the **same Shopify `agents.md` as Trinity** (only names and policy links differ): identify
agent traffic, back off on 429, public pages may be read. Trinity's store pages rate-limit unregistered bots, so expect
the same here; a third-party search API (Fast Simon, Boost, Hotyon) avoids the store's own pages. `api.fastsimon.com`
has an empty robots.txt; `services.mybcapps.com` (Boost) allows `/bc-sf-filter/*`. **Terms of service were not read for
any store** — do that (or email the store) before building.

## What the data looks like

**401 Games** (Fast Simon item):
```
"Nightmare-Eyes Restrict - MAMO-EN122 - Secret Rare - 1st Edition"   CAD 2.00
tags: Rarity_Secret Rare, Set_Magnificent Monsters 1st Edition, Card Type_Monster, TCG_714650
variants: NM (sellable) / PLD / HP
```
- One product per printing: edition is in the title, so no mixed-edition products.
- `TCG_<id>` tag = TCGplayer product id: a strong extra identity signal for matching.
- No quantities, only `Sellable` yes/no. Conditions NM / PLD / HP (Trinity: NM / LP / MP / HP / DMG).
- Open: combining two facet filters (singles + in stock) returned nothing; in-stock alone works. Page size above 50
  untested. At 50 per page a full in-stock crawl is ~700 requests (~10 min at our pace).

**Face to Face** (`products.json`): `"Graceful Charity - SDP-040 - Super Rare - Unlimited"`, variants NM / PL,
`available` yes/no, no tags, no quantities.

**Fusion Gaming** (`products.json`): BinderPOS format like Trinity, `"Bottomless Trap Hole [GEIM-EN045] Rare"`,
variants "Near Mint 1st Edition", tags with edition and set name. Trinity's parser keys it as-is. No quantities.
One sample's edition tag (1st Edition) contradicts its variants (Unlimited).

## Would the cards match Trinity's card_key?

Keys built from the samples (Fusion with Trinity's parser unchanged, 401 / F2F from the `Name - CODE - Rarity -
Edition` title) against the saved Trinity crawl:

| Store | Sampled | Same card number at Trinity | Exact card_key match |
|---|---|---|---|
| 401 Games | 42 | 37 | 33 (89%) |
| Face to Face | 250 | 101 | 80 (79%) |
| Fusion Gaming | 250 | 114 | 89 (78%) |

Most non-matches are **different printings** stocked by each store (Trinity has the Unlimited copy, F2F the 1st
Edition; RA01 reprints exist in several rarities) — correctly different keys. Real mismatches seen:

1. **Edition (biggest issue, Trinity-side):** 1,954 Trinity listings (17%) mix 1st Edition and Unlimited variants in
   one product, but `card_key` holds one edition (tag, else first variant), so half their variants sit under the wrong
   edition. The 401 / F2F one-product-per-edition format exposes this immediately.
2. **Duel Terminal naming:** Fusion `HAC1-EN003|parallel-rare|...|duel-terminal` vs Trinity
   `HAC1-EN003|duel-terminal-technology-ultra-rare|...|base` — same card, different rarity wording.
3. **Version labels:** "(25th Anniversary)" is in some stores' titles and not others (LC01 cards).

## Recommendation

1. **First, fix edition identity** (needed whatever store comes next): move edition out of `card_key` into the variant,
   so a card is `code|rarity|art` and prices compare per (card, edition, condition). Needs a migration that re-keys
   cards and a decision on `current_best_prices`.
2. **Then 401 Games**: biggest in-stock catalogue, a third-party JSON API like Trinity's, the cleanest titles, and
   TCGplayer ids. Before building: read its terms, settle the facet filter and page size, map PLD/HP conditions, and
   decide how to handle "no quantity" (in stock = sellable).
3. **Rarity normalisation table** (shared): e.g. Duel Terminal names, "Parallel Rare", version labels like
   "(25th Anniversary)", grown from real cross-store mismatches with tests.
4. Fusion Gaming is the easy fallback: Trinity's parser almost works and `products.json` covers it.
