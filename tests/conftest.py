import gzip
import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "trinity_yugioh_usf.json.gz"


@pytest.fixture(scope="session")
def real_crawl() -> list[dict]:
    """Full real crawl of Trinity Hobby's Yu-Gi-Oh collection (11,793 raw USF items)."""
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
        return json.load(f)
