"""FastAPI app factory (Phase 1 plan §4.2).

Owns: lifespan (asyncpg pool + in-process worker loop), CORS, the global
exception handlers, OpenAPI docs gating, the health route, and router wiring.
Every domain router is included under `/v1`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from manzil_worker.vision_onnx import ONNX_SHADOW_ARTIFACT_SHA256, artifact_digest

from manzil_api.admin.hunt_operations import router as admin_hunt_operations_router
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
READINESS_TIMEOUT_SECONDS = 2.0
# A Stage may legitimately run for minutes without returning to the queue loop.
# Keep this just beyond JOB_ORPHAN_AFTER (5 min), not at an HTTP-scale timeout.
WORKER_HEARTBEAT_MAX_AGE_SECONDS = 360.0


def _validate_supabase_keys(settings: Settings) -> None:
    missing = [
        name
        for name, value in (
            ("SUPABASE_ANON_KEY", settings.supabase_anon_key),
            ("SUPABASE_SECRET_KEY", settings.supabase_secret_key),
        )
        if not (value or "").strip()
    ]
    if missing:
        raise RuntimeError(
            "Missing required Supabase configuration: "
            + ", ".join(missing)
            + ". Configure the publishable and server-only Supabase keys in .env."
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _validate_supabase_keys(settings)
    pool = await create_db_pool(settings)
    app.state.db_pool = pool
    app.state.model_artifact_ready = await _model_artifact_ready(settings)

    stop = asyncio.Event()
    worker_task: asyncio.Task[None] | None = None
    app.state.worker_heartbeat_at = None
    if settings.worker_inprocess:
        def worker_tick() -> None:
            app.state.worker_heartbeat_at = time.monotonic()

        worker_task = asyncio.create_task(
            run_inprocess_worker(pool, settings, stop, on_tick=worker_tick)
        )
        logger.info("In-process worker loop started (MANZIL_WORKER_INPROCESS=true).")
    app.state.worker_task = worker_task

    try:
        yield
    finally:
        stop.set()  # stop claiming new jobs; let the in-flight one drain
        if worker_task is not None:
            await worker_task
        await pool.close()


async def _model_artifact_ready(settings: Settings) -> bool:
    raw_path = os.environ.get("MANZIL_IMAGE_CLASSIFY_ONNX_DIR", "").strip()
    if not raw_path:
        return settings.environment == "local"
    path = Path(raw_path)
    try:
        actual = await asyncio.to_thread(artifact_digest, path)
    except OSError:
        return False
    return actual == ONNX_SHADOW_ARTIFACT_SHA256


async def _database_ready(app: FastAPI) -> bool:
    pool = getattr(app.state, "db_pool", None)
    if pool is None:
        return False
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            async with pool.acquire() as connection:
                return await connection.fetchval("select 1") == 1
    except Exception:
        return False


def _worker_ready(app: FastAPI, settings: Settings) -> bool:
    if not settings.worker_inprocess:
        return True
    task = getattr(app.state, "worker_task", None)
    heartbeat_at = getattr(app.state, "worker_heartbeat_at", None)
    return bool(
        task is not None
        and not task.done()
        and heartbeat_at is not None
        and time.monotonic() - heartbeat_at <= WORKER_HEARTBEAT_MAX_AGE_SECONDS
    )


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
        admin_hunt_operations_router,
    ):
        app.include_router(router, prefix="/v1")

    @app.get("/v1/health", tags=["health"], summary="Liveness probe")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/ready", tags=["health"], summary="Readiness probe")
    async def ready() -> JSONResponse:
        checks = {
            "database": await _database_ready(app),
            "worker": _worker_ready(app, settings),
            "model": bool(getattr(app.state, "model_artifact_ready", False)),
        }
        is_ready = all(checks.values())
        return JSONResponse(
            status_code=200 if is_ready else 503,
            content={
                "status": "ready" if is_ready else "not_ready",
                "checks": {name: "ok" if value else "failed" for name, value in checks.items()},
            },
        )

    return app


app = create_app()
