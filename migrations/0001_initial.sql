-- TCG price tracker schema (PostgreSQL 14+)
-- Design notes:
--  * A "card" is the canonical identity (set code+number, rarity, edition, art) shared across stores.
--  * A "listing" is one store's product page for a card. Several listings can map to one card.
--  * Cards that couldn't be identified keep card_key NULL (quarantine) and are still tracked.
--  * Nothing is deleted when a card disappears from a crawl: it is marked out of stock.

CREATE TABLE IF NOT EXISTS stores (
    id          smallserial PRIMARY KEY,
    slug        text NOT NULL UNIQUE,
    name        text NOT NULL,
    base_url    text NOT NULL,
    currency    char(3) NOT NULL DEFAULT 'CAD'
);

CREATE TABLE IF NOT EXISTS cards (
    card_key     text PRIMARY KEY,           -- e.g. DIFO-EN070|super-rare|1st-edition|base
    set_code     text NOT NULL,
    card_number  text NOT NULL,              -- e.g. DIFO-EN070
    name         text NOT NULL,
    set_name     text,
    rarity       text NOT NULL,
    edition      text,
    art_label    text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cards_name_idx ON cards (lower(name));
CREATE INDEX IF NOT EXISTS cards_number_idx ON cards (card_number);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id              bigserial PRIMARY KEY,
    store_id        smallint NOT NULL REFERENCES stores(id),
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    status          text NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running','ok','failed','suspect')),
    items_seen      integer NOT NULL DEFAULT 0,
    items_with_problems integer NOT NULL DEFAULT 0,
    notes           text
);

CREATE TABLE IF NOT EXISTS listings (
    id               bigserial PRIMARY KEY,
    store_id         smallint NOT NULL REFERENCES stores(id),
    source_product_id bigint NOT NULL,
    card_key         text REFERENCES cards(card_key),   -- NULL = quarantined (unparsed)
    url_name         text NOT NULL,
    title_raw        text NOT NULL,
    problems         text[] NOT NULL DEFAULT '{}',
    in_stock         boolean NOT NULL DEFAULT true,
    first_seen       timestamptz NOT NULL DEFAULT now(),
    last_seen        timestamptz NOT NULL DEFAULT now(),
    last_run_id      bigint REFERENCES scrape_runs(id),
    raw              jsonb NOT NULL,                    -- latest raw payload, lets us reparse without refetching
    UNIQUE (store_id, source_product_id)
);
CREATE INDEX IF NOT EXISTS listings_card_idx ON listings (card_key) WHERE in_stock;
CREATE INDEX IF NOT EXISTS listings_run_idx ON listings (store_id, last_run_id);

CREATE TABLE IF NOT EXISTS variants (
    id                bigserial PRIMARY KEY,
    listing_id        bigint NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    source_variant_id bigint NOT NULL,
    sku               text,
    condition         text CHECK (condition IN ('NM','LP','MP','HP','DMG')),
    edition           text,
    price             numeric(10,2) NOT NULL CHECK (price > 0),
    quantity          integer NOT NULL,                 -- -1 kept raw: meaning unconfirmed
    in_stock          boolean NOT NULL,
    first_seen        timestamptz NOT NULL DEFAULT now(),
    last_seen         timestamptz NOT NULL DEFAULT now(),
    last_run_id       bigint REFERENCES scrape_runs(id),
    UNIQUE (listing_id, source_variant_id)
);
CREATE INDEX IF NOT EXISTS variants_listing_idx ON variants (listing_id);

-- One row per observed change (price, quantity or stock flag), not one per run.
CREATE TABLE IF NOT EXISTS price_history (
    variant_id   bigint NOT NULL REFERENCES variants(id) ON DELETE CASCADE,
    observed_at  timestamptz NOT NULL DEFAULT now(),
    price        numeric(10,2) NOT NULL,
    quantity     integer NOT NULL,
    in_stock     boolean NOT NULL,
    PRIMARY KEY (variant_id, observed_at)
);

-- What the site would show: cheapest in-stock variant per card and condition.
CREATE OR REPLACE VIEW current_best_prices AS
SELECT c.card_key, c.name, c.set_name, c.rarity, c.edition, c.art_label,
       v.condition, s.slug AS store, v.price, v.quantity, l.url_name
FROM (
    SELECT DISTINCT ON (l.card_key, v.condition)
           l.card_key, v.condition, v.id AS variant_id
    FROM variants v JOIN listings l ON l.id = v.listing_id
    WHERE v.in_stock AND l.in_stock AND l.card_key IS NOT NULL
    ORDER BY l.card_key, v.condition, v.price
) best
JOIN variants v ON v.id = best.variant_id
JOIN listings l ON l.id = v.listing_id
JOIN stores s ON s.id = l.store_id
JOIN cards c ON c.card_key = best.card_key;
