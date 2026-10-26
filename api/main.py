"""FastAPI app: read-only JSON for the website, plus card images. Interactive docs at /docs.

Config (environment / .env): DATABASE_URL, API_CORS_ORIGINS (comma-separated, default http://localhost:3000),
IMAGE_CACHE_DIR, TCG_CONTACT_EMAIL (User-Agent for image downloads).
"""
from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from psycopg_pool import ConnectionPool

from api import images, queries

pool: ConnectionPool | None = None


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = ENV_FILE) -> None:
    """Read the project's .env (KEY=value lines) so `uvicorn api.main:app` works from any shell.
    Values already in the environment win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2).strip()


load_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    pool = ConnectionPool(url, min_size=1, max_size=10, kwargs={"autocommit": True}, open=True)
    try:
        yield
    finally:
        pool.close()


app = FastAPI(title="tcg-tracker API", version="0.1",
              description="Canadian Yu-Gi-Oh! single prices across Trinity Hobby, 401 Games and Fusion Gaming (CAD).",
              lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_methods=["GET"],
                   allow_origins=[o.strip() for o in os.environ.get("API_CORS_ORIGINS",
                                                                    "http://localhost:3000").split(",") if o.strip()])

Limit = Query(24, ge=1, le=100)
Offset = Query(0, ge=0, le=100_000)


def _conn():
    return pool.connection()


@app.get("/api/search", summary="Search printings by card name or card number")
def search(q: str = Query(..., min_length=1, max_length=100), rarity: str | None = None, store: str | None = None,
           in_stock: bool = True, sort: Literal["best", "price", "stores", "name"] = "best",
           limit: int = Limit, offset: int = Offset):
    with _conn() as conn:
        return queries.printings(conn, q=q, rarity=rarity, store=store, in_stock=in_stock, sort=sort,
                                 limit=limit, offset=offset)


@app.get("/api/cards/{card_key}", summary="A card with every store's offers")
def card(card_key: str):
    with _conn() as conn:
        found = queries.card(conn, card_key)
    if not found:
        raise HTTPException(404, "No card with that key")
    return found


@app.get("/api/cards/{card_key}/history", summary="Price history per store")
def history(card_key: str, edition: str | None = None, condition: str | None = None):
    with _conn() as conn:
        return queries.history(conn, card_key, edition, condition)


@app.get("/api/sets", summary="Sets with cards in stock, A-Z")
def sets():
    with _conn() as conn:
        return queries.sets(conn)


@app.get("/api/sets/{set_code}", summary="A set's printings")
def set_page(set_code: str, rarity: str | None = None, store: str | None = None, in_stock: bool = True,
             sort: Literal["number", "price", "name", "stores"] = "number", limit: int = Query(100, ge=1, le=500),
             offset: int = Offset):
    with _conn() as conn:
        return queries.printings(conn, set_code=set_code.upper(), rarity=rarity, store=store, in_stock=in_stock,
                                 sort=sort, limit=limit, offset=offset)


@app.get("/api/deals", summary="Biggest savings between stores for the same card, edition and condition")
def deals(condition: Literal["NM", "LP", "MP", "PL", "HP", "DMG"] = "NM", min_price: float = Query(5.0, ge=0),
          store: str | None = None, sort: Literal["amount", "percent"] = "amount",
          limit: int = Query(20, ge=1, le=100), offset: int = Offset):
    with _conn() as conn:
        return queries.deals(conn, condition=condition, min_price=min_price, store=store, sort=sort,
                             limit=limit, offset=offset)


@app.get("/api/stores", summary="Stores and when each was last updated")
def stores():
    with _conn() as conn:
        return queries.stores(conn)


@app.get("/images/{card_key}", summary="The card's image (downloaded once, then served from our cache)")
def image(card_key: str):
    with _conn() as conn:
        url = queries.image_url(conn, card_key)
    ua = f"tcg-tracker/0.1 (Canadian Yu-Gi-Oh price tracker; contact: {os.environ.get('TCG_CONTACT_EMAIL', 'unset')})"
    got = images.get(card_key, url, ua)
    if not got:
        raise HTTPException(404, "No image for this card")
    path, ctype = got
    return FileResponse(path, media_type=ctype, headers={"Cache-Control": "public, max-age=604800"})
