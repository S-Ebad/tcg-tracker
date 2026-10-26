-- Per-store settings discovered at crawl time, e.g. Trinity's USF API key read from its collection page.
-- Caching them means the store's own site (which rate-limits unregistered bots) is only fetched when the
-- cached value is old or the API rejects it, not on every run.
CREATE TABLE IF NOT EXISTS store_config (
    store_id    smallint NOT NULL REFERENCES stores(id),
    key         text NOT NULL,
    value       jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (store_id, key)
);
