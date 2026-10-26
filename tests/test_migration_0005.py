"""Migration 0005 (edition moves from card_key to the variant) applied to data in the old format."""
import os

import pytest

URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL.rsplit("/", 1)[-1].endswith("_test"),
                                reason="TEST_DATABASE_URL (a *_test database) not set")


@pytest.fixture
def old_db():
    """Schema at version 4 with cards keyed the old way, incl. both editions of one card and an orphan card."""
    import psycopg

    from migrate import migrate

    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        migrate(conn, upto=4)
        conn.execute("""
            INSERT INTO stores (id, slug, name, base_url) VALUES (1, 'trinity', 'Trinity Hobby', 'https://x');
            INSERT INTO cards (card_key, set_code, card_number, name, set_name, rarity, edition, art_label) VALUES
              ('DIFO-EN070|super-rare|1st-edition|base', 'DIFO', 'DIFO-EN070', 'Therion Cross', 'DF', 'Super Rare',
               '1st Edition', NULL),
              ('DIFO-EN070|super-rare|unlimited|base', 'DIFO', 'DIFO-EN070', 'Therion Cross', 'DF', 'Super Rare',
               'Unlimited', NULL),
              ('TDGS-EN040|ghost-rare|unlimited|ghost', 'TDGS', 'TDGS-EN040', 'Stardust Dragon', 'TDG', 'Ghost Rare',
               'Unlimited', 'Ghost');
            INSERT INTO listings (id, store_id, source_product_id, card_key, url_name, title_raw, raw) VALUES
              (1, 1, 100, 'DIFO-EN070|super-rare|1st-edition|base', 'a', 'a', '{}'),
              (2, 1, 200, 'DIFO-EN070|super-rare|unlimited|base', 'b', 'b', '{}'),
              (3, 1, 300, NULL, 'q', 'quarantined', '{}');
            INSERT INTO variants (listing_id, source_variant_id, condition, edition, price, quantity, in_stock) VALUES
              (1, 10, 'NM', '1st Edition', 5.00, 1, true),
              (2, 20, 'NM', 'Unlimited', 3.00, 1, true);
        """)
        yield conn


def test_keys_rewritten_orphans_removed_and_view_per_edition(old_db):
    from migrate import migrate

    assert migrate(old_db) == [5]
    q = old_db.execute
    assert q("SELECT card_key FROM cards ORDER BY 1").fetchall() == [("DIFO-EN070|super-rare|base",)]
    assert q("SELECT id, card_key FROM listings ORDER BY id").fetchall() == [
        (1, "DIFO-EN070|super-rare|base"), (2, "DIFO-EN070|super-rare|base"), (3, None)]
    assert q("""SELECT column_name FROM information_schema.columns
                WHERE table_name='cards' AND column_name='edition'""").fetchall() == []
    assert q("SELECT edition, price::float FROM current_best_prices ORDER BY edition").fetchall() == [
        ("1st Edition", 5.0), ("Unlimited", 3.0)]
    # the foreign key is back
    with pytest.raises(Exception, match="foreign key"):
        q("UPDATE listings SET card_key='NOPE|x|base' WHERE id=1")
