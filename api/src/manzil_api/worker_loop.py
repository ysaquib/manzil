"""In-process worker loop glue (Phase 1 plan §1.5, IMPLEMENTATION P1-3).

DESIGN §5's budget option: the API runs the durable-queue worker loop as a
`lifespan` asyncio task instead of a separate service. Gated by
`MANZIL_WORKER_INPROCESS` (default `true`); P3-1 flips it to `false` in the
deployment env, no code change.
"""

from __future__ import annotations

import asyncio

import asyncpg
from manzil_worker.queue import build_dispatch, run_worker_loop

from manzil_api.config import Settings


async def run_inprocess_worker(pool: asyncpg.Pool, settings: Settings, stop: asyncio.Event) -> None:
    """Drive the durable queue until `stop` is set (clean-shutdown drain)."""
    # Pass settings.database_url explicitly: pydantic-settings reads DATABASE_URL
    # from the .env file without populating os.environ, so build_dispatch's env
    # fallback would silently degrade to InMemoryRegistry.
    dispatch = build_dispatch(pool, dsn=settings.database_url)
    await run_worker_loop(pool, stop=stop, dispatch=dispatch)
