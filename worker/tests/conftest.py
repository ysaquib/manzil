"""Shared helpers for worker tests: fake fetcher/LLM, state builders, and the
full-catalog extraction payload used by P0-8/9/10 stage tests. No live LLM
calls in tests, ever (AGENTS.md) — the FakeLLM validates payloads through the
same schema the seam would."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

# Local Supabase Postgres; mirrors test_migration_0002_schema.py's default so the
# P1-2 queue tests skip cleanly wherever CI has no database.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)


@pytest_asyncio.fixture
async def pg_pool() -> AsyncIterator[asyncpg.Pool]:
    """asyncpg pool against the local stack; skips the test when unreachable."""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, timeout=5, min_size=1, max_size=4)
    except (OSError, asyncpg.PostgresError) as exc:  # pragma: no cover - env guard
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")
    try:
        yield pool
    finally:
        await pool.close()
