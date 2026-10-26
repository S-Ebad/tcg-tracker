# tcg-tracker

Tracks Yu-Gi-Oh! single-card prices and stock at Canadian online stores, with price history.
Currently one store: **Trinity Hobby** (trinityhobby.com, ~11,800 in-stock singles, prices in CAD).

Built with Scrapy and PostgreSQL. Priorities: reliable data, loud failures, tests on real data.

## Quick start

Requires Python 3.12+ and PostgreSQL 16 (Docker or a local install).

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt     # Windows; on Linux/macOS: .venv/bin/pip
cp .env.example .env                                  # then edit: DATABASE_URL, TCG_CONTACT_EMAIL, alerts
docker compose up -d db                               # or a local Postgres, see below
python migrate.py                                     # applies migrations/NNNN_*.sql in order
scrapy crawl trinity                                  # one full crawl, about a minute
```

`.env` must be loaded into the environment before running (`set -a; . ./.env; set +a` in bash).
A crawl needs `TCG_CONTACT_EMAIL`: it goes in the User-Agent so the site owner can reach us.

**Without Docker on Windows:** PostgreSQL 16 from conda-forge, installed into the git-ignored `.tools/` folder:

```bash
.tools/micromamba.exe create -y -p .tools/pg -c conda-forge --override-channels postgresql=16
.tools/pg/Library/bin/pg_ctl.exe -D .tools/pgdata -l .tools/postgres.log start
```

`scripts/localdb.ps1` (init/start/stop/status) wraps this, reading passwords from `.env` (its `init` hasn't been
run end to end yet; the current database was set up by hand). The server isn't a Windows service: start it again
after a reboot.

**Schedule:** run `scrapy crawl trinity` a couple of times a day (Task Scheduler / cron). Not more: be polite.

## Architecture

```
 trinityhobby.com collection page ──(only when needed)──► API key
                                                             │
 Hotyon "USF" search API ◄── 59 GETs, 200 items each ────────┘
          │
          ▼
 tcg_tracker/spiders/trinity.py   paging, completeness checks, run verdict
          │  raw items
          ▼
 tcg_tracker/pipelines.py         parser.parse_item -> db.save_items in batches of 500
          │                        start_run / finish_run bookkeeping
          ▼
 PostgreSQL                        stores, cards, listings, variants, price_history, scrape_runs
          │
          ▼
 tcg_tracker/monitoring.py        post-run checks -> log, scrape_runs.alerts, Discord, email
```

| Path | What it does |
|---|---|
| `tcg_tracker/spiders/trinity.py` | Gets the API key (cached), pages the API until `skip >= data.total`, decides if the crawl is complete |
| `parser.py` | Turns one raw store item into a `CardRec` (card identity) with `VariantRec`s (condition, edition, price, quantity) |
| `db.py` | Batched upserts (COPY into staging tables + set-based SQL), price history, closing a run |
| `tcg_tracker/pipelines.py` | Glue: parse, save in transactions of 500, finish the run, tell the monitor |
| `tcg_tracker/monitoring.py` | Checks every run and sends alerts |
| `tcg_tracker/middlewares.py` | Honours `Retry-After` on 429/503 |
| `migrate.py`, `migrations/` | Numbered SQL migrations, each applied once in its own transaction |

### Data model

- **cards**: one row per canonical card (see *Card identity*), shared by all stores.
- **listings**: one store's product. Keeps the latest raw JSON (`raw`), so data can be re-parsed without
  re-fetching. `card_key` is NULL when the card couldn't be identified (quarantine); it is still tracked.
- **variants**: condition × edition offers within a listing, with price, quantity and `in_stock`.
- **price_history**: a row only when price, quantity or stock changes (`source='seen'`), or when a variant
  disappears from a complete crawl and is marked out of stock (`source='missing'`).
- **scrape_runs**: one row per crawl: status (`ok` / `suspect` / `failed`), counts, null rates per field, alerts.
- **current_best_prices** (view): cheapest in-stock offer per card and condition across stores.

### Why runs can be "suspect" or "failed"

The API only returns in-stock items, so a card that sold out simply disappears. Disappearing is only trusted from a
**complete** crawl. A run is:

- **failed**: paging stopped early, an API page failed after retries, the item count differs from the API's
  `data.total` by more than 0.5%, out-of-stock items started appearing, or a database error happened;
- **suspect**: fewer than 90% of the items of the last good run;
- **ok**: otherwise. Only an ok run marks missing listings and variants out of stock (with history rows).

Nothing is ever deleted: a restocked card reappears with its history.

## Why the USF API and not Shopify's products.json

Trinity runs on Shopify, and Shopify stores expose `/collections/<handle>/products.json`. It doesn't work here:

- There is no Yu-Gi-Oh-only collection (`/collections/yugioh/` is empty). Yu-Gi-Oh singles are in the `singles`
  collection together with every other game: **258,643 products**.
- Shopify caps `page × limit` at **25,000** products per collection listing, so most of it can't be reached.

The store's search widget, Hotyon's "Ultimate Search & Filter" (USF), has an API filtered to exactly the Yu-Gi-Oh
singles (`collection=368535077111/yugioh`): plain GETs, no cookies, 200 items per page, all 11,793 items in 59
requests, ids unique across pages with `sort=-price`. It also returns per-variant quantities.

**The API key** is a public frontend key. It isn't in `usf-boot.js`; it's the `siteId` in the inline
`window.usf = { settings: {...} }` block of the collection page. The spider caches it in `store_config` and only
re-reads the page when the cache is older than 7 days or the API rejects the key (HTTP 400 "Missing or invalid
ApiKey."). That matters because trinityhobby.com answers unregistered bots with **429** on that page, while the
API never has. A hardcoded key in settings is the last resort and raises an alert.

**Politeness:** robots.txt obeyed on both hosts, one request at a time, 0.5 s delay plus AutoThrottle,
`Retry-After` honoured, contact address in the User-Agent. We don't use Shopify's Web Bot Auth: Shopify only
honours it after manually reviewing a registration, which a project like this is unlikely to get.

## Card identity

The same physical card is sold by many stores under different titles. `card_key` is the shared identity:

```
DIFO-EN070|super-rare|1st-edition|base
│          │          │           └ art / version label, or "base"
│          │          └ edition: 1st-edition, unlimited, limited, or unknown
│          └ rarity (slug)
└ set code + language + number, as printed on the card
```

Rarity, edition and art are part of the key because they change the price: a Starlight Rare and an Ultra Rare of the
same card number are different products, and so are 1st Edition and Unlimited, and Extended Art and base art.

Where each part comes from (Trinity):

- **Card number**: `[DIFO-EN070]` in the title. Handles old codes without a language (`[MRD-142]`), special codes
  (`ENSE1`) and letter suffixes (`EN006K`).
- **Rarity**, most specific first: a tag (`Super Rare`, `Duel Terminal Technology Common`,
  `Rarity_Quarter Century Secret Rare`), a title parenthetical (`(UR)`, `(Starlight Rare)`), then the text after the
  code (`[HAC1-EN026] Common`, `[PHRE-EN039] - Phantom Revenge 1st Edition - Ultra Rare`). Text that isn't a
  rarity (`Promo`) is not used.
- **Edition**: an edition tag (`1st Edition`, `Printing_1st Edition`), else the variant's option label.
- **Art label**: other title parentheticals (`(Extended Art)`, `(Green)`, `(MISCENTERED)`). A parenthetical that
  restates the rarity, like `(Ghost)` on a Ghost Rare, is not an art label.

**Quarantine:** anything that can't be identified gets `card_key = NULL` and a `problems` list instead of a guess.
On the saved crawl that is 2 of 11,793 listings: a "Promo" with no rarity, and a graded slab ("- PSA 7"). Graded
cards are never keyed, so they can't compete with raw copies. Variants are keyed by the store's variant id, never by
SKU (SKU is missing on ~5% of variants).

## Monitoring

After every crawl `RunMonitor` checks the run and raises alerts:

| Level | Check |
|---|---|
| critical | run failed or suspect; run never recorded (e.g. database down); items < 90% of the last good run; parser crashed |
| warning | > 2% of items with parse problems; a field's NULL share up > 2 points vs the last good run; > 5% of downloads failed; hardcoded or stale API key used; API key rejected |

Alerts always go to the log and to `scrape_runs.alerts`. Set `ALERT_DISCORD_WEBHOOK_URL` and/or the `ALERT_EMAIL_*`
/ `SMTP_*` variables in `.env` to also receive them. Thresholds are in `tcg_tracker/settings.py`.

## Tests

```bash
pytest                    # 111 tests, about a minute
ruff check .
```

- `tests/trinity_yugioh_usf.json.gz` is a real full crawl (11,793 items) stored gzipped (2.3 MB instead of 23 MB).
  Parser and adapter tests run on it.
- `test_e2e_spider.py` runs real `scrapy crawl` processes against `tests/mock_site.py`, which serves the saved crawl
  as API pages: no network.
- Database tests need `TEST_DATABASE_URL` pointing at a database whose name ends in `_test` (its schema is wiped);
  they're skipped otherwise. `scripts/bench_load.py` times a full load into that database.
- CI (`.github/workflows/ci.yml`) runs ruff and pytest on Python 3.12 and 3.14 with a Postgres 16 service.

## Adding a store

Ask first (see `CLAUDE.md`): each store is a commitment to keep its scraper working.

1. **Find the data source.** Prefer a structured API the site itself uses (search widget, JSON endpoints) over
   HTML. Check robots.txt, terms and any `agents.md`. Count the items and confirm a full crawl is reachable.
2. **Save a real crawl** as a gzipped fixture in `tests/` before writing the parser.
3. **Write the adapter**: a function `raw item -> CardRec` for that store's format, in its own module. Reuse the
   shared card-identity rules: the `card_key` format, `_slug`, the rarity vocabulary, quarantine instead of guessing.
   The adapter must produce the same `card_key` as Trinity for the same physical card; test that on cards both
   stores carry.
4. **Write the spider** in `tcg_tracker/spiders/<slug>.py` with a `store` dict (`slug`, `name`, `base_url`) and a
   `verdict(close_reason)` method saying whether the crawl was complete, like `trinity.py`.
5. **Pipeline:** `pipelines.py` currently calls `parser.parse_item` (Trinity's adapter) directly. A second store
   needs the pipeline to take the adapter from the spider. That change belongs with the second store.
6. **Tests:** adapter tests on real items, an end-to-end test with a mock of the site, monitoring baselines.

## Known limitations

- **One store.** The pipeline is wired to Trinity's parser (see *Adding a store*).
- **History is per run.** Changes between two crawls are seen as one change; sell-outs and restocks between runs are
  invisible.
- **Stock is inferred from absence.** The API hides out-of-stock cards, so "out of stock" means "missing from a
  complete crawl". A suspect or failed run changes nothing, so stock can be stale until the next good run.
- **Paging needs a stable snapshot.** If many prices change during the ~1-minute crawl, `sort=-price` paging can
  skip or repeat items; the 0.5% count tolerance turns large drift into a failed run rather than bad data.
- **`available = -1`** (inventory unconfirmed, 4 variants) is counted as in stock. Below -1 (oversold) is stored as-is,
  out of stock, and flagged.
- **Unknown condition:** a product without option values (the graded slab) has variants with condition NULL.
- **Re-keying leaves old card rows.** When identity rules change, listings get their new `card_key` on the next
  crawl, but `cards` rows for keys no longer used remain (harmless; nothing references them). Raw JSON is kept in
  `listings.raw` if a re-parse tool is ever needed.
- **13 card keys are shared by two listings** of the same card at Trinity. Allowed: the view picks the cheaper.
- **The store page is rate-limited** (429). Runs normally don't need it (cached key); after 7 days the spider tries
  it again and falls back to the cached key if it's still blocked.
- **A run that never starts isn't detected.** Monitoring runs inside the crawl; a stopped scheduler needs an
  external check (e.g. alert when the newest `scrape_runs.started_at` is more than a day old).
- **CI hasn't run on GitHub yet** (no remote); it was verified locally on Python 3.12 and 3.14.
