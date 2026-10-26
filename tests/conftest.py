import gzip
import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "trinity_yugioh_usf.json.gz"


@pytest.fixture(autouse=True)
def no_real_alert_channels(monkeypatch):
    """Tests must never post to the real Discord / email channels configured in .env."""
    import os

    for k in list(os.environ):
        if k.upper().startswith(("ALERT_", "SMTP_")):
            monkeypatch.delenv(k)


@pytest.fixture(scope="session")
def real_crawl() -> list[dict]:
    """Full real crawl of Trinity Hobby's Yu-Gi-Oh collection (11,793 raw USF items)."""
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
        return json.load(f)
