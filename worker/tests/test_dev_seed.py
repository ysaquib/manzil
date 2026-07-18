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
from worker_helpers import _SEED_EXTRACT_RECORDINGS, RECORDED, seed_recorded_llm

# Inline (not imported from conftest) to avoid a same-named sibling conftest
# shadowing it during full-suite collection — see test_migration_0002_schema.py.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def _load_dev_seed():  # type: ignore[no-untyped-def]
    os.environ["MANZIL_LLM_MODE"] = "replay"  # seed must never call a live model in tests
    spec = importlib.util.spec_from_file_location("dev_seed", SCRIPTS_DIR / "dev_seed.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_extract_recordings_are_committed() -> None:
    """Recording filenames are content-hash-keyed, so a prompt or model change
    re-keys them under the blanket `fixtures/recorded/*` ignore. When that
    happens the suite keeps passing locally (file on disk) while CI's checkout
    is missing it — this asserts each referenced seed recording is git-tracked
    so the drift fails at the desk, not on master."""
    import subprocess

    repo_root = Path(__file__).resolve().parents[2]
    for filename in _SEED_EXTRACT_RECORDINGS.values():
        path = RECORDED / filename
        assert path.exists(), f"missing seed recording {filename} — re-record it"
        try:
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", str(path)],
                cwd=repo_root,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):  # pragma: no cover - env guard
            pytest.skip("git unavailable")
        assert tracked.returncode == 0, (
            f"{filename} exists locally but is not git-tracked — add a "
            f"!worker/tests/fixtures/recorded/{filename} exception to .gitignore "
            "and `git add` it, or CI's checkout will fail the seed pipeline"
        )


async def test_dev_seed_leaves_one_hunt_three_listings_nonzero_scores() -> None:
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, timeout=5, min_size=1, max_size=4)
    except (OSError, asyncpg.PostgresError) as exc:  # pragma: no cover - env guard
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")
    try:
        dev_seed = _load_dev_seed()
        hunts, listings, scores = await dev_seed.seed(pool, call_structured=seed_recorded_llm)
        assert hunts == 1
        assert listings == 3
        assert scores >= 1
    finally:
        await pool.close()
