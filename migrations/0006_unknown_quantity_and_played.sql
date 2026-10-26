-- Second store (401 Games, Fast Simon API) differs from Trinity in two ways:
--  * no quantities, only "sellable" yes/no -> variants.quantity / price_history.quantity may be NULL (unknown);
--    in_stock still says whether it can be bought.
--  * conditions NM / PLD / HP. "PLD" (played) has no published definition that maps onto LP or MP, so it is stored
--    as its own grade 'PL' and never compared with LP/MP in current_best_prices (which groups by condition).

ALTER TABLE variants ALTER COLUMN quantity DROP NOT NULL;
ALTER TABLE price_history ALTER COLUMN quantity DROP NOT NULL;

ALTER TABLE variants DROP CONSTRAINT IF EXISTS variants_condition_check;
ALTER TABLE variants ADD CONSTRAINT variants_condition_check
    CHECK (condition IN ('NM', 'LP', 'MP', 'PL', 'HP', 'DMG'));
