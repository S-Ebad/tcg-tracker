-- Data the front end needs (docs/frontend-plan.md, step 2).
--  * listings.image_url: the store's product image (every store's feed has one for ~99% of products).
--  * card_images: one image per card, preferring 401 Games (card-specific scans), then Trinity, then Fusion.
--    The API downloads it once on first request and serves its own copy (never hotlinks per page view).
--  * set_names: set code -> set name. Fusion's feed has no set names, so its cards borrow the name the other stores
--    use for the same set code (the most common one).

ALTER TABLE listings ADD COLUMN image_url text;

CREATE VIEW card_images AS
SELECT DISTINCT ON (l.card_key) l.card_key, l.image_url, s.slug AS store
FROM listings l JOIN stores s ON s.id = l.store_id
WHERE l.card_key IS NOT NULL AND l.image_url IS NOT NULL
ORDER BY l.card_key,
         CASE s.slug WHEN '401games' THEN 1 WHEN 'trinity' THEN 2 WHEN 'fusion' THEN 3 ELSE 9 END,
         l.in_stock DESC, l.last_seen DESC;

CREATE VIEW set_names AS
SELECT set_code, mode() WITHIN GROUP (ORDER BY set_name) AS set_name
FROM cards
WHERE set_name IS NOT NULL
GROUP BY set_code;
