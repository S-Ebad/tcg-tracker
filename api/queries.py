"""SQL behind each endpoint. Every function takes an open psycopg connection and returns plain dicts.

Offers are in-stock variants of in-stock listings with a card_key; prices in CAD. Conditions sort NM -> DMG with
401's PL ("played") between MP and HP; editions 1st -> Unlimited -> Limited -> unknown.
"""
from __future__ import annotations

import os
import re

from psycopg.rows import dict_row

CONDITION_ORDER = ["NM", "LP", "MP", "PL", "HP", "DMG"]
EDITION_ORDER = ["1st Edition", "Unlimited", "Limited"]

# A store is shown only while its data is fresh: a good (complete) crawl in the last API_MAX_DATA_AGE_HOURS. A store
# whose crawls keep failing (Fusion, 2026-10-26: partial runs saved 2,741 listings but never finished) or that was
# taken off the schedule drops off the site instead of showing stale or partial prices.
MAX_DATA_AGE_HOURS = int(os.environ.get("API_MAX_DATA_AGE_HOURS", "72"))
_LIVE_STORE = f"""EXISTS (SELECT 1 FROM scrape_runs r WHERE r.store_id = s.id AND r.status = 'ok'
                          AND r.finished_at > now() - interval '{MAX_DATA_AGE_HOURS} hours')"""

# in-stock offers per card from live stores, optionally from one store
_OFFERS = f"""
SELECT l.card_key, s.slug AS store, v.price
FROM variants v JOIN listings l ON l.id = v.listing_id JOIN stores s ON s.id = l.store_id
WHERE v.in_stock AND l.in_stock AND l.card_key IS NOT NULL AND {_LIVE_STORE}
  AND (%(store)s::text IS NULL OR s.slug = %(store)s)
"""

PRINTING_SORTS = {
    "best": "rank, min_price NULLS LAST, c.card_number",
    "price": "min_price NULLS LAST, c.card_number",
    "stores": "store_count DESC, min_price NULLS LAST",
    "name": "c.name, c.card_number",
    "number": "c.card_number",
}


def normalise(q: str) -> str:
    """Letters and digits only, lower case: "Maxx \"C\"" and "maxx c" both become "maxxc"."""
    return re.sub(r"[^a-z0-9]+", "", q.lower())


def printings(conn, *, q: str | None = None, set_code: str | None = None, rarity: str | None = None,
              store: str | None = None, in_stock: bool = True, sort: str = "best", limit: int = 24,
              offset: int = 0) -> dict:
    """Search results / set page: one row per card_key with its cheapest in-stock offer."""
    norm = normalise(q) if q else None
    if q is not None and not norm:
        return {"total": 0, "items": []}
    code = q.strip().upper() if q else None
    sql = f"""
    WITH agg AS (SELECT card_key, min(price) AS min_price, count(DISTINCT store) AS store_count
                 FROM ({_OFFERS}) o GROUP BY card_key)
    SELECT c.card_key, c.name, c.card_number, c.set_code, COALESCE(c.set_name, sn.set_name) AS set_name,
           c.rarity, c.art_label, a.min_price, COALESCE(a.store_count, 0) AS store_count,
           count(*) OVER () AS total,
           CASE WHEN %(norm)s::text IS NULL THEN 0
                WHEN regexp_replace(lower(c.name), '[^a-z0-9]+', '', 'g') = %(norm)s OR c.card_number = %(code)s THEN 0
                WHEN regexp_replace(lower(c.name), '[^a-z0-9]+', '', 'g') LIKE %(norm)s || '%%'
                     OR c.card_number LIKE %(code)s || '%%' THEN 1
                ELSE 2 END AS rank
    FROM cards c LEFT JOIN agg a USING (card_key) LEFT JOIN set_names sn USING (set_code)
    WHERE (%(norm)s::text IS NULL
           OR regexp_replace(lower(c.name), '[^a-z0-9]+', '', 'g') LIKE '%%' || %(norm)s || '%%'
           OR c.card_number LIKE %(code)s || '%%' OR c.set_code = %(code)s)
      AND (%(set_code)s::text IS NULL OR c.set_code = %(set_code)s)
      AND (%(rarity)s::text IS NULL OR lower(c.rarity) = lower(%(rarity)s))
      AND (NOT %(in_stock)s OR a.min_price IS NOT NULL)
    ORDER BY {PRINTING_SORTS.get(sort, PRINTING_SORTS['best'])}
    LIMIT %(limit)s OFFSET %(offset)s"""
    params = {"norm": norm, "code": code, "set_code": set_code, "rarity": rarity, "store": store,
              "in_stock": in_stock, "limit": limit, "offset": offset}
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(sql, params).fetchall()
    total = rows[0]["total"] if rows else 0
    for r in rows:
        r.pop("total"), r.pop("rank")
        r["min_price"] = float(r["min_price"]) if r["min_price"] is not None else None
    return {"total": total, "items": rows}


def card(conn, card_key: str) -> dict | None:
    """One card with every offer (in stock or not), other printings and per-store freshness."""
    with conn.cursor(row_factory=dict_row) as cur:
        info = cur.execute(
            """SELECT c.card_key, c.name, c.card_number, c.set_code, COALESCE(c.set_name, sn.set_name) AS set_name,
                      c.rarity, c.art_label
               FROM cards c LEFT JOIN set_names sn USING (set_code) WHERE c.card_key = %s""", (card_key,)).fetchone()
        if not info:
            return None
        offers = cur.execute(
            f"""SELECT s.slug AS store, s.name AS store_name, v.edition, v.condition, v.price::float AS price,
                      v.quantity, v.in_stock AND l.in_stock AS in_stock,
                      s.base_url || '/products/' || l.url_name AS url, v.last_seen
               FROM variants v JOIN listings l ON l.id = v.listing_id JOIN stores s ON s.id = l.store_id
               WHERE l.card_key = %(k)s AND {_LIVE_STORE}
               ORDER BY coalesce(array_position(%(eds)s, v.edition), 9),
                        coalesce(array_position(%(conds)s, v.condition), 9), v.price""",
            {"k": card_key, "eds": EDITION_ORDER, "conds": CONDITION_ORDER}).fetchall()
        others = cur.execute(
            f"""WITH agg AS (SELECT card_key, min(price) AS min_price FROM ({_OFFERS}) o GROUP BY card_key)
                SELECT c.card_key, c.card_number, c.rarity, c.art_label, a.min_price::float AS min_price
                FROM cards c LEFT JOIN agg a USING (card_key)
                WHERE regexp_replace(lower(c.name), '[^a-z0-9]+', '', 'g') = %(norm)s AND c.card_key <> %(k)s
                ORDER BY a.min_price NULLS LAST, c.card_number LIMIT 30""",
            {"norm": normalise(info["name"]), "k": card_key, "store": None}).fetchall()
    info["editions"] = [e for e in EDITION_ORDER + [None] if any(o["edition"] == e for o in offers)]
    in_stock = [o for o in offers if o["in_stock"]]
    nm = [o["price"] for o in in_stock if o["condition"] == "NM"]
    info["cheapest_nm"] = min(nm) if nm else None
    info["stores_in_stock"] = len({o["store"] for o in in_stock})
    info["offers"] = offers
    info["other_printings"] = others
    return info


def history(conn, card_key: str, edition: str | None, condition: str | None) -> list[dict]:
    """Price history points per store (every recorded change), oldest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            """SELECT s.slug AS store, v.edition, v.condition, h.observed_at, h.price::float AS price, h.in_stock,
                      h.source
               FROM price_history h JOIN variants v ON v.id = h.variant_id
               JOIN listings l ON l.id = v.listing_id JOIN stores s ON s.id = l.store_id
               WHERE l.card_key = %(k)s AND (%(ed)s::text IS NULL OR v.edition = %(ed)s)
                 AND (%(cond)s::text IS NULL OR v.condition = %(cond)s)
               ORDER BY s.slug, h.observed_at""", {"k": card_key, "ed": edition, "cond": condition}).fetchall()
    series: dict[str, list] = {}
    for r in rows:
        series.setdefault(r.pop("store"), []).append(r)
    return [{"store": s, "points": pts} for s, pts in series.items()]


def sets(conn) -> list[dict]:
    """Every set with at least one card in stock, A-Z by name (code when no name is known)."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"""WITH agg AS (SELECT card_key, min(price) AS min_price FROM ({_OFFERS}) o GROUP BY card_key)
                SELECT c.set_code, max(COALESCE(c.set_name, sn.set_name)) AS set_name,
                       count(*) AS cards_in_stock, min(a.min_price)::float AS cheapest
                FROM cards c JOIN agg a USING (card_key) LEFT JOIN set_names sn USING (set_code)
                GROUP BY c.set_code
                ORDER BY lower(coalesce(max(COALESCE(c.set_name, sn.set_name)), c.set_code)), c.set_code""",
            {"store": None}).fetchall()


DEAL_SORTS = {"amount": "saving DESC", "percent": "saving_pct DESC, saving DESC"}


def deals(conn, *, condition: str = "NM", min_price: float = 5.0, store: str | None = None, sort: str = "amount",
          limit: int = 20, offset: int = 0) -> list[dict]:
    """Same card, edition and condition at 2+ stores: cheapest store vs priciest store."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            f"""WITH store_best AS (
                    SELECT l.card_key, v.edition, v.condition, s.slug, min(v.price) AS price
                    FROM variants v JOIN listings l ON l.id = v.listing_id JOIN stores s ON s.id = l.store_id
                    WHERE v.in_stock AND l.in_stock AND l.card_key IS NOT NULL AND v.edition IS NOT NULL
                      AND v.condition = %(cond)s AND {_LIVE_STORE}
                    GROUP BY 1, 2, 3, 4),
                spread AS (
                    SELECT card_key, edition, condition, min(price) AS low, max(price) AS high,
                           count(*) AS stores,
                           (array_agg(slug ORDER BY price, slug))[1] AS cheapest_store,
                           (array_agg(slug ORDER BY price DESC, slug))[1] AS priciest_store
                    FROM store_best GROUP BY 1, 2, 3 HAVING count(*) >= 2)
                SELECT c.card_key, c.name, c.card_number, c.rarity, c.art_label, sp.edition, sp.condition,
                       sp.cheapest_store, sp.low::float AS low, sp.priciest_store, sp.high::float AS high,
                       sp.stores, (sp.high - sp.low)::float AS saving,
                       round(1 - sp.low / sp.high, 4)::float AS saving_pct
                FROM spread sp JOIN cards c USING (card_key)
                WHERE sp.high >= %(min_price)s AND sp.high > sp.low
                  AND (%(store)s::text IS NULL OR sp.cheapest_store = %(store)s)
                ORDER BY {DEAL_SORTS.get(sort, DEAL_SORTS['amount'])}, c.card_key
                LIMIT %(limit)s OFFSET %(offset)s""",
            {"cond": condition, "min_price": min_price, "store": store, "limit": limit, "offset": offset}).fetchall()
    return rows


def stores(conn) -> list[dict]:
    """Each live store with its newest good crawl and how many listings are in stock."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"""SELECT s.slug, s.name, s.base_url,
                      (SELECT max(finished_at) FROM scrape_runs r WHERE r.store_id = s.id AND r.status = 'ok')
                          AS last_updated,
                      (SELECT count(*) FROM listings l WHERE l.store_id = s.id AND l.in_stock) AS listings_in_stock
               FROM stores s WHERE {_LIVE_STORE} ORDER BY s.name""").fetchall()


def image_url(conn, card_key: str) -> str | None:
    row = conn.execute("SELECT image_url FROM card_images WHERE card_key = %s", (card_key,)).fetchone()
    return row[0] if row else None
