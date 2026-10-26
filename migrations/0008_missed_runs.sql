-- How many complete ('ok') runs in a row have not seen a listing. A store can require more than one miss before a
-- listing counts as out of stock: 401 Games' search index drifts (two copies out of sync, ~0.7% of cards skipped
-- per crawl), so a single miss there doesn't mean sold out. Reset to 0 whenever the listing is seen.
ALTER TABLE listings ADD COLUMN missed_runs integer NOT NULL DEFAULT 0;
