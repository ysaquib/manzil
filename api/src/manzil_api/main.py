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

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from manzil_api.admin.operations import router as admin_operations_router
from manzil_api.admin.people import router as admin_people_router
from manzil_api.admin.router import router as admin_router
from manzil_api.collaboration.router import router as collaboration_router
from manzil_api.config import Settings, get_settings
from manzil_api.database import create_db_pool
from manzil_api.exceptions import CatchAllMiddleware, register_exception_handlers
from manzil_api.feedback.router import router as feedback_router
from manzil_api.fees.router import router as fees_router
from manzil_api.hunts.router import router as hunts_router
from manzil_api.invitation_links.router import router as invitation_links_router
from manzil_api.invites.router import router as invites_router
from manzil_api.jobs.router import router as jobs_router
from manzil_api.listings.router import router as listings_router
from manzil_api.overrides.router import router as overrides_router
from manzil_api.profiles.router import router as profiles_router
from manzil_api.rubric.router import router as rubric_router
from manzil_api.utilities.router import router as utilities_router
from manzil_api.visits.router import router as visits_router
from manzil_api.worker_loop import run_inprocess_worker

logger = logging.getLogger("manzil_api")


def _validate_supabase_keys(settings: Settings) -> None:
    missing = [
        name
        for name, value in (
            ("SUPABASE_ANON_KEY", settings.supabase_anon_key),
            ("SUPABASE_SERVICE_ROLE_KEY", settings.supabase_service_role_key),
        )
        if not (value or "").strip()
    ]
    if missing:
        raise RuntimeError(
            "Missing required Supabase configuration: "
            + ", ".join(missing)
            + ". Run `supabase status -o env` and copy ANON_KEY / SERVICE_ROLE_KEY into .env."
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _validate_supabase_keys(settings)
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
    # The in-process worker loop (§1.5) reads its keys straight from os.environ —
    # tier-3 provider, OpenRouter, Langfuse — like the worker CLI (which calls
    # load_dotenv itself). pydantic-settings parses .env WITHOUT populating
    # os.environ, so export it here; real environment wins (override=False) and a
    # missing .env is a no-op. Same cwd-relative path as Settings' env_file.
    load_dotenv(".env")
    settings = get_settings()

    app_configs: dict[str, Any] = {"title": "Manzil API", "version": "1.0"}
    if not settings.docs_enabled:
        app_configs["openapi_url"] = None  # hide docs outside local/staging

    app = FastAPI(lifespan=lifespan, **app_configs)

    # add_middleware prepends — register CatchAll first so CORSMiddleware stays outermost.
    app.add_middleware(CatchAllMiddleware)
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
        collaboration_router,
        invites_router,
        invitation_links_router,
        rubric_router,
        listings_router,
        jobs_router,
        overrides_router,
        fees_router,
        utilities_router,
        profiles_router,
        feedback_router,
        visits_router,
        admin_router,
        admin_people_router,
        admin_operations_router,
    ):
        app.include_router(router, prefix="/v1")

    @app.get("/v1/health", tags=["health"], summary="Liveness probe")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
