"""Card images: downloaded once from the store's CDN on first request, then served from our own cache.

Only Shopify's CDN is fetched (the URLs come from store data, but never fetch arbitrary hosts), at a modest width,
with our User-Agent, a timeout and a size cap. Files are named by a hash of the card_key ("|" isn't valid on Windows).
"""
from __future__ import annotations

import hashlib
import os
import urllib.parse
import urllib.request
from pathlib import Path

ALLOWED_HOSTS = {"cdn.shopify.com"}
MAX_BYTES = 5_000_000
WIDTH = 480  # enough for a card page; Shopify resizes on its side


def cache_dir() -> Path:
    d = Path(os.environ.get("IMAGE_CACHE_DIR", Path(__file__).resolve().parent.parent / ".cache" / "images"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_path(card_key: str) -> Path:
    return cache_dir() / (hashlib.sha1(card_key.encode()).hexdigest() + ".img")


def sized(url: str) -> str:
    """Ask Shopify's CDN for a smaller copy (?width=480), keeping any existing query."""
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query) + [("width", str(WIDTH))]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def allowed(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS


def download(url: str, user_agent: str) -> tuple[bytes, str]:
    """(bytes, content type). Raises ValueError for anything that isn't a reasonable image."""
    if not allowed(url):
        raise ValueError(f"host not allowed: {url}")
    req = urllib.request.Request(sized(url), headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=15) as r:
        ctype = r.headers.get("Content-Type", "").split(";")[0]
        data = r.read(MAX_BYTES + 1)
    if not ctype.startswith("image/") or len(data) > MAX_BYTES or not data:
        raise ValueError(f"not an image or too large: {ctype}, {len(data)} bytes")
    return data, ctype


def get(card_key: str, url: str | None, user_agent: str, fetch=None) -> tuple[Path, str] | None:
    """Cached file and content type, downloading on first use; None if there's no usable image."""
    fetch = fetch or download
    path = cache_path(card_key)
    meta = path.with_suffix(".type")
    if path.exists() and meta.exists():
        return path, meta.read_text()
    if not url:
        return None
    try:
        data, ctype = fetch(url, user_agent)
    except Exception:
        return None
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    meta.write_text(ctype)
    return path, ctype
