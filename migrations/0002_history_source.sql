-- Record why a price_history row exists, and how much each run marked out of stock.
--  * source = 'seen':    the variant was in the crawl and its price, quantity or stock flag changed (or first sight).
--  * source = 'missing': the variant, or its whole listing, was absent from a trustworthy ('ok') crawl and was
--                        marked out of stock. quantity on these rows is the last value seen, not an observation.

ALTER TABLE price_history
    ADD COLUMN source text NOT NULL DEFAULT 'seen' CHECK (source IN ('seen', 'missing'));

ALTER TABLE scrape_runs
    ADD COLUMN listings_marked_out integer NOT NULL DEFAULT 0,
    ADD COLUMN variants_marked_out integer NOT NULL DEFAULT 0;
