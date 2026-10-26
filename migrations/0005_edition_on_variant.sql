-- Edition moves from the card to the variant.
--
-- Before: card_key = CODE|rarity|edition|art, one edition per listing. But a listing can hold both 1st Edition and
-- Unlimited copies (1,954 of 11,793 Trinity listings), so half their variants sat under the wrong edition, and stores
-- that list one product per edition (401 Games, Face to Face) could never line up.
-- After:  card_key = CODE|rarity|art. variants.edition (already stored per variant) is the edition.
--         current_best_prices = cheapest in-stock offer per card, edition and condition.

DROP VIEW IF EXISTS current_best_prices;

-- listings.card_key references cards; drop the FK while keys are rewritten (re-added below)
ALTER TABLE listings DROP CONSTRAINT IF EXISTS listings_card_key_fkey;

-- 'DIFO-EN070|super-rare|1st-edition|base' -> 'DIFO-EN070|super-rare|base'
CREATE FUNCTION pg_temp.drop_edition(k text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN array_length(string_to_array(k, '|'), 1) = 4
                THEN split_part(k, '|', 1) || '|' || split_part(k, '|', 2) || '|' || split_part(k, '|', 4)
                ELSE k END
$$;

INSERT INTO cards (card_key, set_code, card_number, name, set_name, rarity, edition, art_label, created_at)
SELECT DISTINCT ON (pg_temp.drop_edition(card_key))
       pg_temp.drop_edition(card_key), set_code, card_number, name, set_name, rarity, NULL, art_label, created_at
FROM cards
WHERE array_length(string_to_array(card_key, '|'), 1) = 4
  AND card_key IN (SELECT card_key FROM listings WHERE card_key IS NOT NULL)  -- orphans from older rules are dropped
ORDER BY pg_temp.drop_edition(card_key), created_at
ON CONFLICT (card_key) DO NOTHING;

UPDATE listings SET card_key = pg_temp.drop_edition(card_key)
WHERE card_key IS NOT NULL AND array_length(string_to_array(card_key, '|'), 1) = 4;

-- old-format rows, including ones no listing used any more
DELETE FROM cards WHERE array_length(string_to_array(card_key, '|'), 1) = 4;

ALTER TABLE cards DROP COLUMN edition;

ALTER TABLE listings ADD CONSTRAINT listings_card_key_fkey FOREIGN KEY (card_key) REFERENCES cards(card_key);

CREATE VIEW current_best_prices AS
SELECT c.card_key, c.name, c.set_name, c.rarity, v.edition, c.art_label,
       v.condition, s.slug AS store, v.price, v.quantity, l.url_name
FROM (
    SELECT DISTINCT ON (l.card_key, v.edition, v.condition)
           l.card_key, v.edition, v.condition, v.id AS variant_id
    FROM variants v JOIN listings l ON l.id = v.listing_id
    WHERE v.in_stock AND l.in_stock AND l.card_key IS NOT NULL
    ORDER BY l.card_key, v.edition, v.condition, v.price
) best
JOIN variants v ON v.id = best.variant_id
JOIN listings l ON l.id = v.listing_id
JOIN stores s ON s.id = l.store_id
JOIN cards c ON c.card_key = best.card_key;
