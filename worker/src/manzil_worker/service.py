"""Standalone process entry point for the durable Manzil worker.

The API lifespan loop and this command deliberately call the same queue
dispatch/runner seam.  Postgres remains the queue, state store, lease holder,
and source of worker liveness; this module only owns process startup and
shutdown.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal

import asyncpg
import structlog
from dotenv import load_dotenv

from manzil_worker.ops.demo_publication import process_next_demo_publication
from manzil_worker.queue import build_dispatch, run_worker_loop, scheduler_tick

log = structlog.get_logger()


def _request_shutdown(stop: asyncio.Event, signal_name: str) -> None:
    """Stop claiming Jobs while allowing the current Job to drain."""
    log.info("worker_shutdown_requested", signal=signal_name)
    stop.set()


def install_shutdown_signal_handlers(
    stop: asyncio.Event,
    *,
    event_loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Translate Render/container termination signals into a queue drain."""
    event_loop = event_loop or asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGTERM, signal.SIGINT):
        try:
            event_loop.add_signal_handler(
                shutdown_signal,
                _request_shutdown,
                stop,
                shutdown_signal.name,
            )
        except NotImplementedError:  # pragma: no cover - Windows only
            # Render runs Linux, but retain a usable local fallback for Python
            # event loops that do not implement add_signal_handler().
            signal.signal(
                shutdown_signal,
                lambda _signum, _frame, name=shutdown_signal.name: _request_shutdown(stop, name),
            )


async def run_worker_service(
    database_url: str,
    *,
    stop: asyncio.Event | None = None,
) -> None:
    """Run one durable worker loop until ``stop`` requests a clean drain."""
    stop = stop or asyncio.Event()
    pool = await asyncpg.create_pool(database_url)
    try:
        # Supplying the DSN is required: build_dispatch otherwise intentionally
        # falls back to InMemoryRegistry for the Phase-0 CLI without a database.
        dispatch = build_dispatch(pool, dsn=database_url)
        await run_worker_loop(
            pool,
            stop=stop,
            dispatch=dispatch,
            priority_tick=process_next_demo_publication,
            scheduler_tick=scheduler_tick,
            mode=os.environ.get("MANZIL_MODE", "workflow"),
        )
    finally:
        await pool.close()


async def run_worker_process(database_url: str) -> None:
    """Install process signal handling, then run the service loop."""
    stop = asyncio.Event()
    install_shutdown_signal_handlers(stop)
    await run_worker_service(database_url, stop=stop)


def main() -> None:
    """Console-script entry point used by the Render Background Worker."""
    parser = argparse.ArgumentParser(
        description="Run Manzil's durable Postgres-backed pipeline worker."
    )
    parser.parse_args()
    load_dotenv(".env")
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required for the standalone worker")
    asyncio.run(run_worker_process(database_url))
