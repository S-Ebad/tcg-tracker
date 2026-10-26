# Front end plan (demo)

Status: draft for review, 2026-10-26. Based on the mockups agreed in chat.

## Goal

A public demo where anyone in Canada can find the cheapest copy of a Yu-Gi-Oh! single across Trinity Hobby,
401 Games and Fusion Gaming, see it per edition and condition, and click through to the store.

## Stack

| Layer | Tool | Notes |
|---|---|---|
| Pages | Next.js (App Router, TypeScript) + Tailwind CSS + shadcn/ui | charts with Recharts (shadcn charts) |
| API | FastAPI (Python), read-only | lives in this repo (`api/`), reuses the Postgres schema |
| Data | PostgreSQL + the existing scrapers | unchanged; crawled twice a day |

The website never talks to Postgres directly: only through the API.

## Pages

Working name: **Card Scout CA** (placeholder). Tagline: **Here to serve your Canadian Yu-Gi-Oh! TCG needs.**

### Every page: header
Logo + name, links: Deals, Sets, Stores. Search box always visible (moves into the banner on the home page).
Footer: the three stores with links, "Prices updated twice a day", card art and names (c) Konami, not affiliated.

### 1. Home `/`
- **Tagline banner** (bold, full width): tagline, "Trinity Hobby · 401 Games · Fusion Gaming", one-line pitch,
  big search box.
- **Deal of the day strip**: the single biggest saving today (same card, edition and condition, near mint, cheapest
  store vs priciest), e.g. "Maxx C is 70% cheaper at Trinity ($10.60 vs $35.00)". Links to the card page.
- **Stats**: stores, listings tracked, comparable offers.
- **Browse by set**: sets A–Z with set code, number of cards in stock, cheapest card. Links to the set page.

### 2. Search results `/search?q=`
- Matches card name or card number (e.g. "dark magician", "YSYR-EN001", "MAMO").
- One result per printing (card_key): image, name, code, rarity, set, "from $X", "N stores".
- Sort: **best match** (default), lowest price, most stores, name A–Z.
- Filters: in stock only (default on), rarity, store.

### 3. Set page `/sets/[setCode]`
- Header: set name and code, number of cards in stock.
- **Card tiles** grid (image, name, card number, cheapest price + store), in card-number order (EN001, EN002 …).
- Sort: card number (default), lowest price, name A–Z. Filters: rarity, store, in stock.

### 4. Card page `/cards/[cardKey]`
- Image, name, card number, set, rarity badge, art/version label (e.g. 25th Anniversary) if any.
- Quick facts: cheapest near mint, stores in stock, last updated.
- **Edition tabs** (1st Edition / Unlimited / Limited / unknown) – only the editions that exist.
- **Price table**: store, condition, price, "Cheapest" badge, Visit (link to the store's product page).
  Conditions shown as the store gives them; 401's PLD is "Played (PL)", never merged with LP/MP.
- **Price history chart**: one line per store for the chosen edition and condition; 30 days / all.
- "Other printings" of the same card name (links to their card pages).

### 5. Deals `/deals`
- Biggest savings: same card, edition and condition, at 2+ stores, cheapest vs priciest.
- Sort: biggest saving in $ (default) or %. Filters: condition (default NM), minimum price (default $5),
  store you'd buy from.

### 6. Stores `/stores`
- The three stores, what we track, when each was last crawled, link to each store. A thank-you for their permission.

## Design spec (Tailwind + shadcn/ui)

From mobile layout feedback on the mockups (2026-10-26). Mobile first; dark mode supported throughout.

**1. Hero banner** (`<Hero>`)
- Extra top padding above the store line: `pt-8 pb-6 px-5 sm:pt-10` (was ~22px).
- Search input: no light-lavender block on a dark banner. Translucent surface with an accent ring on focus:
  `bg-white/10 text-white placeholder:text-white/60 ring-1 ring-white/20 focus-visible:ring-2
  focus-visible:ring-violet-300 rounded-lg h-11` (light theme variant: `bg-white text-zinc-900 ring-zinc-200
  focus-visible:ring-violet-500`).

**2. Card tiles** (`<CardTile>`)
- Image box locked to card proportions, scans never stretched:
  `aspect-[59/86] w-full overflow-hidden rounded-md bg-muted` + `<Image className="h-full w-full object-contain">`.
- Price and store visually separate: price `text-sm font-semibold tabular-nums`, store as a shadcn `<Badge
  variant="secondary" className="text-[11px] font-normal">401 Games</Badge>` next to it.
- Multi-store offers as a tappable chip that opens the comparison (sheet on mobile, card page link on desktop):
  `<Button variant="outline" size="sm" className="h-7 rounded-full px-2.5 text-xs">3 stores <ChevronRight
  className="size-3" /></Button>`.

**3. Sort and filter controls** (`<SortPill>`, `<FilterPill>`)
- Pill buttons with a chevron opening a shadcn `DropdownMenu` (sort) / `Popover` with checkboxes (filters):
  `<Button variant="outline" size="sm" className="h-8 rounded-full gap-1">Sort: Number <ChevronDown
  className="size-3.5 opacity-60" /></Button>`. Active filters use `variant="secondary"` and show a count.
- Row of pills scrolls horizontally on small screens: `flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none]`.
- Touch targets at least 32px tall (`h-8`), 44px for primary actions.

**4. Back-to-top button** (`<BackToTop>`)
- Bottom-right, elevated, appears after scrolling ~600px:
  `fixed bottom-[max(1rem,env(safe-area-inset-bottom))] right-4 z-40 size-11 rounded-full shadow-lg
  bg-primary text-primary-foreground` with `aria-label="Back to top"`; never centred over the grid.

## API (FastAPI, read-only, JSON)

| Endpoint | Used by | Returns |
|---|---|---|
| `GET /api/search?q=&sort=&rarity=&store=&in_stock=` | search | printings with image, name, code, rarity, set, min price, store count |
| `GET /api/cards/{card_key}` | card page | card info + offers (store, edition, condition, price, url, in stock) + other printings |
| `GET /api/cards/{card_key}/history?edition=&condition=` | card chart | price points per store over time |
| `GET /api/sets` | home, sets | set code, name, cards in stock, cheapest |
| `GET /api/sets/{set_code}?sort=&rarity=&store=` | set page | the set's printings like search results |
| `GET /api/deals?condition=&min_price=&store=&sort=&limit=` | home strip, deals | savings rows |
| `GET /api/stores` | footer, stores, "updated" | store, last good crawl time, listings in stock |
| `GET /images/{card_key}.jpg` | everywhere | the card's image, served by us |

Paging on lists (`limit`, `offset`). Prices in CAD. Only in-stock offers unless asked.

## Data work needed first (step 2) — done 2026-10-26 (migration 0007)

Result: `listings.image_url` (all adapters), views `card_images` (401 > Trinity > Fusion) and `set_names`; cards fill a
missing set name from a later store; PSR / ESR abbreviations, and a title abbreviation that narrows the tagged
rarity wins (Fusion "(ESR) ... Secret Rare" now matches 401's Emblazoned Secret Rare). Visit links and "last
updated" need no schema change: `stores.base_url + '/products/' + listings.url_name`, newest ok `scrape_runs`.

1. **Set names for every card**: Fusion has none; fill from Trinity / 401 via the shared set code
   (`set_code` -> most common `set_name`).
2. **One image per card_key**: pick from the stores' images (401 first, then Trinity, then Fusion), download once,
   store and serve ourselves; YGOPRODeck (download once, never hotlink) only for the ~1% without a store image.
3. **"(PSR)" rarity abbreviation**: add to the shared list (it currently becomes an art label).
4. **Store product URLs**: build the "Visit" link per store (Trinity / Fusion: `/products/<handle>`, 401: `u`).
5. **Last updated per store**: from `scrape_runs` (newest ok run).

## Build order

1. This plan (review)
2. Data work above, with tests
3. API with tests (against the test database), browsable at `/docs`
4. Next.js app: layout + header/footer -> home -> search -> set page -> card page -> deals -> stores
5. Docker (Postgres, crawlers + schedule, API, website) and hosting

## Out of scope for the demo

Accounts, watchlists, price alerts, set release dates, mobile app, more stores.
