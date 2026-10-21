"""Persistence layer: upsert parsed items, track changes, close out a run."""
from __future__ import annotations

from psycopg.types.json import Jsonb

# A run that returns fewer items than this share of the previous good run is not trusted.
MIN_RATIO = 0.9


def ensure_store(conn, slug, name, base_url):
    return conn.execute(
        """INSERT INTO stores (slug, name, base_url) VALUES (%s,%s,%s)
           ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id""",
        (slug, name, base_url)).fetchone()[0]


def start_run(conn, store_id):
    return conn.execute("INSERT INTO scrape_runs (store_id) VALUES (%s) RETURNING id", (store_id,)).fetchone()[0]


def save_item(conn, store_id, run_id, rec, raw):
    """Upsert one parsed card (CardRec from parser.py) with its raw payload."""
    if rec.card_key:
        conn.execute(
            """INSERT INTO cards (card_key,set_code,card_number,name,set_name,rarity,edition,art_label)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (card_key) DO NOTHING""",
            (rec.card_key, rec.set_code, rec.card_number, rec.name, rec.set_name, rec.rarity,
             next((v.edition for v in rec.variants if v.edition), None), rec.art_label))
    listing_id = conn.execute(
        """INSERT INTO listings (store_id, source_product_id, card_key, url_name, title_raw, problems,
                                 in_stock, last_run_id, raw)
           VALUES (%s,%s,%s,%s,%s,%s,true,%s,%s)
           ON CONFLICT (store_id, source_product_id) DO UPDATE SET
              card_key = EXCLUDED.card_key, url_name = EXCLUDED.url_name, title_raw = EXCLUDED.title_raw,
              problems = EXCLUDED.problems, in_stock = true, last_seen = now(),
              last_run_id = EXCLUDED.last_run_id, raw = EXCLUDED.raw
           RETURNING id""",
        (store_id, rec.product_id, rec.card_key, rec.url_name, raw["title"], rec.problems,
         run_id, Jsonb(raw))).fetchone()[0]
    for v in rec.variants:
        old = conn.execute(
            "SELECT id, price, quantity, in_stock FROM variants WHERE listing_id=%s AND source_variant_id=%s",
            (listing_id, v.variant_id)).fetchone()
        vid = conn.execute(
            """INSERT INTO variants (listing_id, source_variant_id, sku, condition, edition, price,
                                     quantity, in_stock, last_run_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (listing_id, source_variant_id) DO UPDATE SET
                  sku = EXCLUDED.sku, condition = EXCLUDED.condition, edition = EXCLUDED.edition,
                  last_seen = now(), last_run_id = EXCLUDED.last_run_id,
                  price = EXCLUDED.price, quantity = EXCLUDED.quantity, in_stock = EXCLUDED.in_stock
               RETURNING id""",
            (listing_id, v.variant_id, v.sku, v.condition, v.edition, v.price, v.quantity,
             v.in_stock, run_id)).fetchone()[0]
        # history row only when something observable changed (or on first sight)
        if old is None or (float(old[1]), old[2], old[3]) != (v.price, v.quantity, v.in_stock):
            conn.execute(
                """INSERT INTO price_history (variant_id, price, quantity, in_stock) VALUES (%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""", (vid, v.price, v.quantity, v.in_stock))
    return listing_id


def finish_run(conn, store_id, run_id, items_seen, items_with_problems, error=None):
    """Close the run. Only a trustworthy run is allowed to mark missing cards out of stock.

    error: set by the caller when the crawl itself was incomplete (paging stopped, count mismatch, DB error).
    """
    prev = conn.execute(
        "SELECT items_seen FROM scrape_runs WHERE store_id=%s AND status='ok' AND id<>%s ORDER BY id DESC LIMIT 1",
        (store_id, run_id)).fetchone()
    status, notes = "ok", None
    if error:
        status, notes = "failed", error
    elif items_seen == 0:
        status, notes = "failed", "no items returned"
    elif prev and items_seen < MIN_RATIO * prev[0]:
        status, notes = "suspect", f"{items_seen} items vs {prev[0]} last good run"
    if status == "ok":
        conn.execute("""UPDATE listings SET in_stock=false
                        WHERE store_id=%s AND last_run_id IS DISTINCT FROM %s AND in_stock""", (store_id, run_id))
        conn.execute("""UPDATE variants SET in_stock=false FROM listings l
                        WHERE variants.listing_id=l.id AND l.store_id=%s AND variants.last_run_id IS DISTINCT FROM %s
                          AND variants.in_stock""", (store_id, run_id))
    conn.execute("""UPDATE scrape_runs SET finished_at=now(), status=%s, items_seen=%s,
                    items_with_problems=%s, notes=%s WHERE id=%s""",
                 (status, items_seen, items_with_problems, notes, run_id))
    return status, notes
