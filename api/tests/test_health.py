"""Health route smoke test — proves the app factory, routing, and CORS wiring
boot without a DB (Phase 1 plan §8)."""

from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health_ok(client: AsyncClient) -> None:
    response = await client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


class _Connection:
    async def fetchval(self, query: str) -> int:
        assert query == "select 1"
        return 1


class _Acquire:
    async def __aenter__(self) -> _Connection:
        return _Connection()

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Pool:
    def acquire(self) -> _Acquire:
        return _Acquire()


class _Task:
    def __init__(self, *, done: bool = False) -> None:
        self._done = done

    def done(self) -> bool:
        return self._done


@pytest.mark.asyncio
async def test_ready_checks_database_worker_and_model(app) -> None:  # type: ignore[no-untyped-def]
    app.state.db_pool = _Pool()
    app.state.worker_task = _Task()
    app.state.worker_heartbeat_at = time.monotonic()
    app.state.model_artifact_ready = True

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "worker": "ok", "model": "ok"},
    }


@pytest.mark.asyncio
async def test_ready_fails_closed_without_exposing_internal_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Builds its own app rather than taking the shared fixture, because
    # `_worker_ready` short-circuits to True whenever the in-process worker is
    # disabled — and `conftest` defaults `MANZIL_WORKER_INPROCESS` to "false".
    # Inheriting that, this asserted the worker branch only on a machine whose
    # `.env` happened to enable it: it passed in the main checkout and failed in
    # a worktree, which is the definition of a test that is not testing.
    from manzil_api.config import get_settings
    from manzil_api.main import create_app

    monkeypatch.setenv("MANZIL_WORKER_INPROCESS", "true")
    get_settings.cache_clear()
    try:
        app = create_app()
        app.state.db_pool = None
        app.state.worker_task = _Task(done=True)
        app.state.worker_heartbeat_at = time.monotonic() - 999
        app.state.model_artifact_ready = False

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/v1/ready")
    finally:
        # The cache holds the pinned settings; drop it so the next caller reads
        # the environment monkeypatch has just restored.
        get_settings.cache_clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "failed", "worker": "failed", "model": "failed"},
    }
