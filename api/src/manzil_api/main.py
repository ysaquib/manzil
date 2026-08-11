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
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from manzil_worker.vision_onnx import ONNX_SHADOW_ARTIFACT_SHA256, artifact_digest

from manzil_api.admin.demo import router as admin_demo_router
from manzil_api.admin.hunt_operations import router as admin_hunt_operations_router
from manzil_api.admin.operations import router as admin_operations_router
from manzil_api.admin.people import router as admin_people_router
from manzil_api.admin.router import router as admin_router
from manzil_api.collaboration.router import router as collaboration_router
from manzil_api.config import Settings, get_settings
from manzil_api.database import create_db_pool
from manzil_api.demo.router import router as demo_router
from manzil_api.dependencies import require_not_demo
from manzil_api.email.dispatcher import run_email_dispatcher
from manzil_api.exceptions import CatchAllMiddleware, register_exception_handlers
from manzil_api.feedback.router import router as feedback_router
from manzil_api.fees.router import router as fees_router
from manzil_api.hunts.router import router as hunts_router
from manzil_api.invitation_links.router import router as invitation_links_router
from manzil_api.invites.router import router as invites_router
from manzil_api.jobs.router import router as jobs_router
from manzil_api.listings.router import router as listings_router
from manzil_api.notifications.router import router as notifications_router
from manzil_api.overrides.router import router as overrides_router
from manzil_api.probe_logging import quiet_probe_access_logs
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
    settings.validate_email_delivery()
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
    email_task = asyncio.create_task(run_email_dispatcher(pool, settings, stop))
    app.state.email_task = email_task

    try:
        yield
    finally:
        stop.set()  # stop claiming new jobs; let the in-flight one drain
        if worker_task is not None:
            await worker_task
        await email_task
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


def _email_ready(app: FastAPI) -> bool:
    task = getattr(app.state, "email_task", None)
    return bool(task is not None and not task.done())


def create_app() -> FastAPI:
    # The in-process worker loop (§1.5) reads its keys straight from os.environ —
    # tier-3 provider, OpenRouter, Langfuse — like the worker CLI (which calls
    # load_dotenv itself). pydantic-settings parses .env WITHOUT populating
    # os.environ, so export it here; real environment wins (override=False) and a
    # missing .env is a no-op. Same cwd-relative path as Settings' env_file.
    load_dotenv(".env")
    # Uvicorn configures logging before it imports the app, so a filter attached
    # here survives; the probe cadence is Render's to set, the log volume is ours.
    quiet_probe_access_logs()
    settings = get_settings()

    app_configs: dict[str, Any] = {"title": "Manzil API", "version": "1.0"}
    if not settings.docs_enabled:
        app_configs["openapi_url"] = None  # hide docs outside local/staging

    # `require_not_demo` is registered app-wide rather than per-router so a new
    # route cannot forget it. It is deliberately not the security boundary --
    # the database refuses these writes regardless (DESIGN §16) -- but it turns
    # a raw SQLSTATE into a catchable `403 demo_read_only` and stops demo
    # traffic before any expensive validation or fan-out. It reads the bearer
    # token itself, so it does not force authentication onto the public demo
    # and health routes.
    app = FastAPI(lifespan=lifespan, dependencies=[Depends(require_not_demo)], **app_configs)

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
        demo_router,
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
        notifications_router,
        admin_router,
        admin_demo_router,
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
            "email": _email_ready(app),
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
