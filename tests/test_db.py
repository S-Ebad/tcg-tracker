"""db.py against a real Postgres. Needs TEST_DATABASE_URL pointing at a database whose name ends in _test
(its public schema is dropped and rebuilt for every test). Skipped when it isn't set."""
import os

import pytest

import db
from parser import parse_item

URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL.rsplit("/", 1)[-1].endswith("_test"),
                                reason="TEST_DATABASE_URL (a *_test database) not set")


@pytest.fixture
def conn():
    import psycopg

    from migrate import migrate

    with psycopg.connect(URL, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE")
        c.execute("CREATE SCHEMA public")
        migrate(c)
        yield c


@pytest.fixture
def store(conn):
    return db.ensure_store(conn, "trinity", "Trinity Hobby", "https://trinityhobby.com")


def raw(pid, variants, title="Therion Cross [DIFO-EN070] Super Rare"):
    """variants: list of (variant_id, available, price); option index i -> values[i]."""
    values = ["Near Mint 1st Edition", "Lightly Played 1st Edition", "Moderately Played 1st Edition"]
    return {"id": pid, "urlName": f"p{pid}", "title": title,
            "tags": ["Super Rare", "YGO_Dimension Force", "1st Edition"],
            "options": [{"name": "Title", "values": values}],
            "variants": [{"id": vid, "sku": None, "available": a, "price": p, "options": [i]}
                         for i, (vid, a, p) in enumerate(variants)]}


def crawl(conn, store, raws, items_seen=None):
    """One complete run: save everything in one batch, then finish it."""
    run = db.start_run(conn, store)
    with conn.transaction():
        db.save_items(conn, store, run, [(parse_item(r), r) for r in raws])
    with conn.transaction():
        status, _ = db.finish_run(conn, store, run, len(raws) if items_seen is None else items_seen, 0)
    return run, status


def history(conn, variant):
    return conn.execute(
        """SELECT h.price::float, h.quantity, h.in_stock, h.source FROM price_history h
           JOIN variants v ON v.id = h.variant_id WHERE v.source_variant_id = %s ORDER BY h.observed_at""",
        (variant,)).fetchall()


def test_first_sight_writes_one_history_row_per_variant(conn, store):
    crawl(conn, store, [raw(1, [(10, 3, 0.6), (11, 0, 0.5)])])
    assert history(conn, 10) == [(0.6, 3, True, "seen")]
    assert history(conn, 11) == [(0.5, 0, False, "seen")]


def test_unchanged_recrawl_writes_no_history(conn, store):
    crawl(conn, store, [raw(1, [(10, 3, 0.6)])])
    crawl(conn, store, [raw(1, [(10, 3, 0.6)])])
    assert len(history(conn, 10)) == 1


def test_price_change_and_going_to_zero_are_recorded(conn, store):
    crawl(conn, store, [raw(1, [(10, 3, 0.6)])])
    crawl(conn, store, [raw(1, [(10, 3, 0.75)])])
    crawl(conn, store, [raw(1, [(10, 0, 0.75)])])
    assert history(conn, 10) == [(0.6, 3, True, "seen"), (0.75, 3, True, "seen"), (0.75, 0, False, "seen")]


def test_variant_removed_from_listing_gets_missing_row(conn, store):
    crawl(conn, store, [raw(1, [(10, 3, 0.6), (11, 2, 0.5)])])
    _, status = crawl(conn, store, [raw(1, [(10, 3, 0.6)])])
    assert status == "ok"
    assert history(conn, 11) == [(0.5, 2, True, "seen"), (0.5, 2, False, "missing")]
    assert conn.execute("SELECT in_stock FROM variants WHERE source_variant_id=11").fetchone() == (False,)
    assert conn.execute("SELECT variants_marked_out FROM scrape_runs ORDER BY id DESC LIMIT 1").fetchone() == (1,)


def test_whole_listing_disappearing_marks_listing_and_variants_out(conn, store):
    keep = [raw(n, [(n * 10, 1, 1.0)], title=f"Card [AAAA-EN{n:03d}] Rare") for n in range(2, 12)]
    crawl(conn, store, [raw(1, [(10, 3, 0.6)])] + keep)
    crawl(conn, store, keep)
    assert conn.execute("SELECT in_stock FROM listings WHERE source_product_id=1").fetchone() == (False,)
    assert history(conn, 10)[-1] == (0.6, 3, False, "missing")
    assert conn.execute("SELECT listings_marked_out, variants_marked_out FROM scrape_runs ORDER BY id DESC LIMIT 1"
                        ).fetchone() == (1, 1)


def test_missing_rows_are_not_repeated_on_later_runs(conn, store):
    keep = [raw(n, [(n * 10, 1, 1.0)], title=f"Card [AAAA-EN{n:03d}] Rare") for n in range(2, 12)]
    crawl(conn, store, [raw(1, [(10, 3, 0.6)])] + keep)
    crawl(conn, store, keep)
    crawl(conn, store, keep)
    assert [h[3] for h in history(conn, 10)] == ["seen", "missing"]


def test_restock_after_missing_is_recorded(conn, store):
    keep = [raw(n, [(n * 10, 1, 1.0)], title=f"Card [AAAA-EN{n:03d}] Rare") for n in range(2, 12)]
    crawl(conn, store, [raw(1, [(10, 3, 0.6)])] + keep)
    crawl(conn, store, keep)
    crawl(conn, store, [raw(1, [(10, 1, 0.6)])] + keep)
    assert history(conn, 10)[-1] == (0.6, 1, True, "seen")
    assert conn.execute("SELECT in_stock FROM listings WHERE source_product_id=1").fetchone() == (True,)


def test_suspect_run_marks_nothing_out_and_writes_no_missing_rows(conn, store):
    many = [raw(n, [(n * 10, 1, 1.0)], title=f"Card [AAAA-EN{n:03d}] Rare") for n in range(1, 21)]
    crawl(conn, store, many)
    _, status = crawl(conn, store, many[:5])
    assert status == "suspect"
    assert conn.execute("SELECT count(*) FROM variants WHERE NOT in_stock").fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM price_history WHERE source='missing'").fetchone() == (0,)


def test_failed_run_marks_nothing_out(conn, store):
    crawl(conn, store, [raw(1, [(10, 3, 0.6)]), raw(2, [(20, 1, 1.0)], title="X [AAAA-EN002] Rare")])
    run = db.start_run(conn, store)
    with conn.transaction():
        status, notes = db.finish_run(conn, store, run, 1, 0, error="paging stopped early")
    assert (status, notes) == ("failed", "paging stopped early")
    assert conn.execute("SELECT count(*) FROM variants WHERE NOT in_stock").fetchone() == (0,)


def test_unconfirmed_quantity_minus_one_is_kept_raw_and_in_stock(conn, store):
    crawl(conn, store, [raw(1, [(10, -1, 2.0)])])
    assert conn.execute("SELECT quantity, in_stock FROM variants WHERE source_variant_id=10").fetchone() == (-1, True)
    row = conn.execute("SELECT quantity FROM current_best_prices").fetchone()
    assert row == (-1,)


def test_duplicate_product_in_one_batch_keeps_last_copy(conn, store):
    run = db.start_run(conn, store)
    a, b = raw(1, [(10, 3, 0.6)]), raw(1, [(10, 3, 0.9)])
    with conn.transaction():
        db.save_items(conn, store, run, [(parse_item(a), a), (parse_item(b), b)])
    assert conn.execute("SELECT price::float FROM variants").fetchall() == [(0.9,)]


def test_quarantined_listing_is_stored_without_card(conn, store):
    crawl(conn, store, [raw(1, [(10, 1, 1.0)], title="Mystery card with no code")])
    assert conn.execute("SELECT card_key, problems FROM listings").fetchone() == (None, ["no_set_code"])
    assert conn.execute("SELECT count(*) FROM cards").fetchone() == (0,)


def test_best_prices_are_per_card_edition_and_condition(conn, store):
    mixed = raw(1, [(10, 1, 9.0), (11, 1, 2.0)])
    mixed["options"][0]["values"] = ["Near Mint 1st Edition", "Near Mint Unlimited"]
    other = raw(2, [(20, 1, 7.0)])  # same card from a second listing, 1st Edition, cheaper
    other["urlName"] = "second-listing"
    crawl(conn, store, [mixed, other])
    rows = conn.execute("""SELECT card_key, edition, condition, price::float, url_name FROM current_best_prices
                           ORDER BY edition""").fetchall()
    assert rows == [("DIFO-EN070|super-rare|base", "1st Edition", "NM", 7.0, "second-listing"),
                    ("DIFO-EN070|super-rare|base", "Unlimited", "NM", 2.0, "p1")]
    assert conn.execute("SELECT count(*) FROM cards").fetchone() == (1,)


def test_set_name_is_filled_by_a_later_store_and_card_image_prefers_401(conn, store):
    from parser import CardRec, VariantRec

    def rec(pid, set_name, image):
        return CardRec(pid, f"p{pid}", "Therion Cross", "DIFO", "EN", "DIFO-EN070", set_name, "Super Rare", None,
                       "DIFO-EN070|super-rare|base", [VariantRec(pid * 10, None, "NM", "1st Edition", 1.0, None, True)],
                       [], title="Therion Cross", image_url=image)

    fusion = db.ensure_store(conn, "fusion", "Fusion Gaming", "https://fusiongamingonline.com")
    g401 = db.ensure_store(conn, "401games", "401 Games", "https://store.401games.ca")
    for st, r in ((fusion, rec(1, None, "https://cdn/fusion.jpg")), (store, rec(2, "Dimension Force", "https://cdn/t.jpg")),
                  (g401, rec(3, "Dimension Force", "https://cdn/401.jpg"))):
        run = db.start_run(conn, st)
        with conn.transaction():
            db.save_items(conn, st, run, [(r, {"id": r.product_id})])
    assert conn.execute("SELECT set_name FROM cards").fetchone() == ("Dimension Force",)
    assert conn.execute("SELECT set_name FROM set_names WHERE set_code='DIFO'").fetchone() == ("Dimension Force",)
    assert conn.execute("SELECT image_url, store FROM card_images").fetchall() == [("https://cdn/401.jpg", "401games")]


def test_store_config_round_trip_and_age(conn, store):
    assert db.get_store_config(conn, store, "usf") is None
    db.set_store_config(conn, store, "usf", {"api_key": "a"})
    db.set_store_config(conn, store, "usf", {"api_key": "b"})
    value, age = db.get_store_config(conn, store, "usf")
    assert value == {"api_key": "b"} and 0 <= age < 60


def test_real_crawl_loads_with_expected_counts(conn, store, real_crawl):
    run = db.start_run(conn, store)
    pairs = [(parse_item(r), r) for r in real_crawl]
    for i in range(0, len(pairs), 500):
        with conn.transaction():
            db.save_items(conn, store, run, pairs[i:i + 500])
    counts = [conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("listings", "cards", "variants", "price_history")]
    assert counts == [11793, 11778, 62710, 62710]
    assert conn.execute("SELECT count(*) FROM listings WHERE card_key IS NULL").fetchone()[0] < 0.01 * 11793
