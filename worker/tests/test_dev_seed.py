"""P1-1 done-when: after the dev-seed runs, the DB holds 1 hunt, 3 listings, and
non-zero scores. Skips cleanly without a database.

The test drives `scripts/dev_seed.py` itself (idempotent — it replaces its own
data), in `MANZIL_LLM_MODE=replay` against the committed seed recordings, so it
is a self-contained assertion rather than a check on external prior state.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import asyncpg
import pytest
from conftest import DATABASE_URL

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def _load_dev_seed():  # type: ignore[no-untyped-def]
    os.environ["MANZIL_LLM_MODE"] = "replay"  # seed must never call a live model in tests
    spec = importlib.util.spec_from_file_location("dev_seed", SCRIPTS_DIR / "dev_seed.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_dev_seed_leaves_one_hunt_three_listings_nonzero_scores() -> None:
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, timeout=5, min_size=1, max_size=4)
    except (OSError, asyncpg.PostgresError) as exc:  # pragma: no cover - env guard
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")
    try:
        dev_seed = _load_dev_seed()
        hunts, listings, scores = await dev_seed.seed(pool)
        assert hunts == 1
        assert listings == 3
        assert scores >= 1
    finally:
        await pool.close()
