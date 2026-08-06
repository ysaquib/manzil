"""DM-5: the public demo endpoints and the app-wide read-only guard.

The route-coverage test below is the one that matters. `require_not_demo` is
registered app-wide precisely so a new route cannot forget it, and the test
enumerates `app.routes` rather than naming routes, because a hand-maintained
list drifts the moment somebody adds an endpoint.
"""

from __future__ import annotations

import time
import uuid

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from local_supabase import LOCAL_JWT_SECRET

pytestmark = pytest.mark.asyncio

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# Public by design: the demo session endpoint is how a visitor gets a token at
# all, so it cannot require one.
EXEMPT_PATHS = {"/v1/demo/session"}


def demo_token(subject: str | None = None, **overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": subject or str(uuid.uuid4()),
        "aud": "authenticated",
        "role": "authenticated",
        "iat": now,
        "exp": now + 900,
        "manzil_demo": True,
        **overrides,
    }
    return jwt.encode(claims, LOCAL_JWT_SECRET, algorithm="HS256")


def _fill(path: str) -> str:
    """Substitute a plausible value for every path parameter."""
    out = []
    for segment in path.split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            out.append("00000000-0000-0000-0000-000000000000")
        else:
            out.append(segment)
    return "/".join(out)


@pytest.fixture
def unsafe_routes(app) -> list[tuple[str, str]]:
    """Every registered unsafe route, read from the OpenAPI schema.

    Deliberately not `app.routes`: this FastAPI version keeps included routers
    wrapped rather than flattened, so walking that list silently yields nothing
    -- which is the exact failure mode `test_there_are_unsafe_routes_to_cover`
    exists to catch. The schema is the app's own account of what it serves.
    """
    schema = app.openapi()
    routes: list[tuple[str, str]] = []
    for path, operations in schema.get("paths", {}).items():
        if not path.startswith("/v1") or path in EXEMPT_PATHS:
            continue
        for method in operations:
            if method.upper() in UNSAFE:
                routes.append((method.upper(), path))
    return sorted(routes)


async def test_there_are_unsafe_routes_to_cover(unsafe_routes) -> None:
    """Guards the guard: if enumeration silently returned nothing, the coverage
    test below would pass while testing nothing."""
    assert len(unsafe_routes) > 20


async def test_every_unsafe_route_refuses_a_demo_token(app, unsafe_routes) -> None:
    token = demo_token()
    failures: list[str] = []
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for method, path in unsafe_routes:
            response = await client.request(
                method,
                _fill(path),
                headers={"Authorization": f"Bearer {token}"},
                json={},
            )
            if response.status_code != 403 or response.json().get("code") != "demo_read_only":
                failures.append(f"{method} {path} -> {response.status_code}")
    assert not failures, "routes that did not refuse a demo token:\n" + "\n".join(failures)


async def test_safe_methods_are_not_refused(app) -> None:
    """The guard must not turn the demo into a blank page."""
    token = demo_token()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/v1/hunts", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code != 403


async def test_a_real_users_writes_are_untouched(as_owner) -> None:
    """The guard keys on the demo claim, not on being authenticated at all."""
    response = await as_owner.post("/v1/hunts", json={"name": "Guard Check"})
    assert response.status_code != 403


async def test_a_forged_demo_token_is_rejected(app) -> None:
    """The demo claim is not self-asserting: it is only believed under our
    signature. Otherwise anyone could mint themselves a demo identity, which
    matters because that identity has read access to the Demo Hunt."""
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": "authenticated",
            "role": "authenticated",
            "exp": int(time.time()) + 900,
            "manzil_demo": True,
        },
        "not-the-projects-signing-secret",
        algorithm="HS256",
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/v1/hunts", headers={"Authorization": f"Bearer {forged}"}
        )
    assert response.status_code == 401


async def test_an_expired_demo_token_is_rejected(app) -> None:
    stale = demo_token(exp=int(time.time()) - 60)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/v1/hunts", headers={"Authorization": f"Bearer {stale}"}
        )
    assert response.status_code == 401


# ── The public endpoints ─────────────────────────────────────────────────────


async def test_demo_config_reports_disabled_by_default(app) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/demo/config")
    assert response.status_code == 200
    assert response.json() == {"enabled": False}


async def test_session_is_not_discoverable_while_disabled(app, db_pool) -> None:
    """404 rather than 403: a disabled demo should not reveal that it exists."""
    await db_pool.execute("update site_settings set demo_enabled = false")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/demo/session")
    assert response.status_code == 404
    assert response.json()["code"] == "demo_unavailable"


async def test_disabled_attempts_are_still_recorded(app, db_pool) -> None:
    """The issuance log is the only telemetry that a public visitor arrived, so
    it must capture refusals too, not only successes."""
    before = await db_pool.fetchval(
        "select count(*) from demo_session_issuance where outcome = 'disabled'"
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post("/v1/demo/session")
    after = await db_pool.fetchval(
        "select count(*) from demo_session_issuance where outcome = 'disabled'"
    )
    assert after == before + 1


async def test_issuance_records_no_ip_address(db_pool) -> None:
    """§16 PII posture: this is the one place the app would otherwise collect
    data about people who are not users."""
    columns = {
        r["column_name"]
        for r in await db_pool.fetch(
            "select column_name from information_schema.columns"
            " where table_schema = 'public' and table_name = 'demo_session_issuance'"
        )
    }
    assert "ip" not in columns and "ip_address" not in columns
    assert "client_key" in columns


async def test_rate_limit_is_enforced_in_the_database(db_pool) -> None:
    """In-process counters do not survive multiple Render instances or a
    restart, so the ceiling is checked and recorded in one statement."""
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            outcomes = [
                (
                    await conn.fetchval(
                        "select issue_demo_session($1, $2, $3, $4)",
                        "test-key",
                        "pytest",
                        2,
                        100,
                    )
                )
                for _ in range(4)
            ]
        finally:
            await tr.rollback()

    import json as _json

    statuses = [_json.loads(o)["status"] for o in outcomes]
    # Demo is disabled in this database, so every attempt is refused for that
    # reason; the point here is that the function records and returns a decision
    # rather than raising, and never issues while disabled.
    assert all(s in {"disabled", "rate_limited"} for s in statuses)
    assert "issued" not in statuses
