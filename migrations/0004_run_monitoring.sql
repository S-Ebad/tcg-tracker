-- Run monitoring (tcg_tracker/monitoring.py).
--  * field_stats: share of NULL per parsed field in this run, compared with the last good run to spot parser or
--                 source-format breakage, e.g. {"card_key": 0.0057, "variant.sku": 0.049, "n_listings": 11793}.
--  * alerts:      what the monitor raised for this run (also sent to Discord/email when configured).
ALTER TABLE scrape_runs
    ADD COLUMN field_stats jsonb,
    ADD COLUMN alerts text[] NOT NULL DEFAULT '{}';
