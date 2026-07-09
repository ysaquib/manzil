"""In-process worker loop glue (Phase 1 plan §1.5, IMPLEMENTATION P1-3).

DESIGN §5's budget option: the API runs the durable-queue worker loop as a
`lifespan` asyncio task instead of a separate service. Gated by
`MANZIL_WORKER_INPROCESS` (default `true`); P3-1 flips it to `false` in the
deployment env, no code change.

Scaffolding note: `manzil_worker.queue.run_worker_loop` is P1-2 and does not
exist yet. Until it lands this glue is import-defensive — it logs that the loop
is unavailable and yields control, so the API boots and serves today. Wire the
real call in the marked spot when P1-2 merges.
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg

from manzil_api.config import Settings

logger = logging.getLogger("manzil_api.worker_loop")


async def run_inprocess_worker(pool: asyncpg.Pool, settings: Settings, stop: asyncio.Event) -> None:
    """Drive the durable queue until `stop` is set (clean-shutdown drain)."""
    try:
        from manzil_worker.queue import (
            run_worker_loop,
        )
    except ImportError:
        logger.warning(
            "manzil_worker.queue.run_worker_loop not available yet (P1-2); "
            "in-process worker loop is a no-op until it lands."
        )
        await stop.wait()
        return

    # P1-2 landed: the loop builds its own per-job StageCtx (rubric + settings
    # loaded from each job's hunt) and dispatches by job_type. Hand off until the
    # lifespan sets `stop`, then it drains the in-flight job and returns.
    await run_worker_loop(pool, stop=stop)
