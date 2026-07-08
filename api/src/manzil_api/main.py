"""FastAPI app factory (Phase 1 plan §4.2).

Owns: lifespan (asyncpg pool + in-process worker loop), CORS, the global
exception handlers, OpenAPI docs gating, the health route, and router wiring.
Every domain router is included under `/v1`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from manzil_api.config import get_settings
from manzil_api.database import create_db_pool
from manzil_api.exceptions import register_exception_handlers
from manzil_api.fees.router import router as fees_router
from manzil_api.hunts.router import router as hunts_router
from manzil_api.jobs.router import router as jobs_router
from manzil_api.listings.router import router as listings_router
from manzil_api.overrides.router import router as overrides_router
from manzil_api.rubric.router import router as rubric_router
from manzil_api.worker_loop import run_inprocess_worker

logger = logging.getLogger("manzil_api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    pool = await create_db_pool(settings)
    app.state.db_pool = pool

    stop = asyncio.Event()
    worker_task: asyncio.Task[None] | None = None
    if settings.worker_inprocess:
        worker_task = asyncio.create_task(run_inprocess_worker(pool, settings, stop))
        logger.info("In-process worker loop started (MANZIL_WORKER_INPROCESS=true).")

    try:
        yield
    finally:
        stop.set()  # stop claiming new jobs; let the in-flight one drain
        if worker_task is not None:
            await worker_task
        await pool.close()


def create_app() -> FastAPI:
    settings = get_settings()

    app_configs: dict[str, Any] = {"title": "Manzil API", "version": "1.0"}
    if not settings.docs_enabled:
        app_configs["openapi_url"] = None  # hide docs outside local/staging

    app = FastAPI(lifespan=lifespan, **app_configs)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    for router in (
        hunts_router,
        rubric_router,
        listings_router,
        jobs_router,
        overrides_router,
        fees_router,
    ):
        app.include_router(router, prefix="/v1")

    @app.get("/v1/health", tags=["health"], summary="Liveness probe")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
