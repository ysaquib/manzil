"""DM-5: the public demo endpoints and the app-wide read-only guard.

The route-coverage test below is the one that matters. `require_not_demo` is
registered app-wide precisely so a new route cannot forget it, and the test
enumerates `app.routes` rather than naming routes, because a hand-maintained
list drifts the moment somebody adds an endpoint.
"""

from __future__ import annotations

import json
import logging
import pathlib
import time
import uuid

import asyncpg
import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from local_supabase import LOCAL_JWT_SECRET, LOCAL_SUPABASE_URL
from manzil_api.admin.dependencies import AdminAudit
from manzil_api.main import create_app

pytestmark = pytest.mark.asyncio

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# Public by design: the demo session endpoint is how a visitor gets a token at
# all, so it cannot require one.
EXEMPT_PATHS = {"/v1/demo/session"}


def demo_token(subject: str | None = None, **overrides) -> str:
    """A token matching the profile `POST /v1/demo/session` actually mints.

    The verifier pins that profile (R2 M7), so a test token that omits `iss`,
    `role` or the generation claim is rejected as malformed rather than
    recognised as a demo token -- which would make the coverage test below pass
    for the wrong reason. `overrides` is how the negative tests break it on
    purpose.
    """
    now = int(time.time())
    claims = {
        "sub": subject or str(uuid.uuid4()),
        "aud": "authenticated",
        "role": "authenticated",
        "iss": f"{LOCAL_SUPABASE_URL}/auth/v1",
        "iat": now,
        "exp": now + 900,
        "manzil_demo": True,
        "manzil_demo_gen": 1,
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


async def test_disabled_attempts_are_still_counted(app, db_pool) -> None:
    """Refusals are telemetry too -- they are how an operator sees an attack.

    Counted, not logged: the old table appended a row per request, so a disabled
    demo turned every unauthenticated request into a guaranteed durable write
    (R2 C2).
    """
    window = "date_trunc('hour', now())"
    before = await db_pool.fetchval(
        f"select coalesce(sum(disabled), 0) from demo_session_counters"
        f" where window_start = {window}"
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post("/v1/demo/session")
    after = await db_pool.fetchval(
        f"select coalesce(sum(disabled), 0) from demo_session_counters"
        f" where window_start = {window}"
    )
    assert after > before


async def test_refused_requests_cannot_grow_the_database(db_pool) -> None:
    """The C2 storage attack, directly: many refusals, bounded rows.

    Storage must be a function of the bucket domain, never of how many requests
    an unauthenticated caller chooses to send.

    **One key, two hundred times.** The previous version sent 200 *distinct*
    keys and allowed 201 new rows, which the design it exists to refuse -- a row
    per request -- satisfies exactly (R2 `R5`). Distinct keys can only ever prove
    that the bucket domain is finite, and 200 is under 4096, so the assertion was
    a tautology. A single key has exactly one bucket, so anything beyond its row
    and the global row is per-request storage.
    """
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            before = await conn.fetchval("select count(*) from demo_session_counters")
            for _ in range(200):
                await conn.fetchval(
                    "select issue_demo_session($1, $2, $3)", "a" * 32, 20, 600
                )
            after = await conn.fetchval("select count(*) from demo_session_counters")
        finally:
            await tr.rollback()

    # The caller's own bucket, plus the global bucket. Nothing else may appear,
    # however many times the endpoint is hit.
    assert after - before <= 2


async def test_issuance_stores_nothing_about_the_visitor(db_pool) -> None:
    """§16 PII posture: this is the one place the app would otherwise collect
    data about people who are not users. Counters hold a bucket number derived
    from a truncated HMAC -- not the IP, and no longer even the HMAC."""
    columns = {
        r["column_name"]
        for r in await db_pool.fetch(
            "select column_name from information_schema.columns"
            " where table_schema = 'public' and table_name = 'demo_session_counters'"
        )
    }
    assert columns == {
        "window_start",
        "client_bucket",
        "issued",
        "rate_limited",
        "disabled",
    }
    assert not await db_pool.fetchval(
        "select exists (select 1 from information_schema.tables"
        " where table_schema = 'public' and table_name = 'demo_session_issuance')"
    ), "the per-request log must be gone, not merely unused"


async def _enable_demo_in_transaction(conn, seeded_users) -> None:
    """Make the demo genuinely issuable, and preflight-clean, inside a
    rolled-back transaction.

    Preflight-clean matters for the audit-atomicity test below, which has to
    reach `set_demo_enabled(true, ...)` rather than bounce off a blocker: the
    Demo Hunt must be owned by the primordial Site Admin, and the principal must
    be virtual and hold no stored membership.
    """
    # Start from an empty window. The counters are committed state shared with
    # anything else that has issued this hour -- `scripts/dm8_adversarial.py`
    # deliberately exhausts a ceiling -- so without this the ceiling tests below
    # depend on what else has run recently. Rolled back with the transaction.
    await conn.execute(
        "delete from demo_session_counters where window_start = date_trunc('hour', now())"
    )

    owner = seeded_users["owner"].user_id
    primordial = await conn.fetchval(
        "select user_id from site_admins where is_primordial limit 1"
    )
    if primordial is None:
        await conn.execute(
            "insert into site_admins (user_id, is_primordial, note)"
            " values ($1, true, 'test bootstrap')",
            owner,
        )
        primordial = owner

    hunt = await conn.fetchval(
        "insert into hunts (name, owner_id) values ('Issuance test', $1) returning id",
        primordial,
    )
    await conn.execute("delete from demo_accounts")
    # A UUID with no auth.users row: the virtual principal the preflight insists
    # on (DESIGN §20 v3.55).
    await conn.execute(
        "insert into demo_accounts (user_id, note) values ($1, 'issuance test')",
        uuid.uuid4(),
    )
    await conn.execute(
        "update site_settings set demo_enabled = true, demo_hunt_id = $1", hunt
    )


async def test_issuance_stops_at_the_per_key_ceiling(db_pool, seeded_users) -> None:
    """The previous version of this test ran while the demo was disabled and
    accepted `disabled`/`rate_limited` -- so it never issued a token, never
    reached a ceiling, and would have passed against a limiter that did nothing
    (R2 C2). This one enables the demo and counts.
    """
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _enable_demo_in_transaction(conn, seeded_users)
            statuses = [
                json.loads(
                    await conn.fetchval(
                        "select issue_demo_session($1, $2, $3)", "a" * 32, 2, 600
                    )
                )["status"]
                for _ in range(4)
            ]
        finally:
            await tr.rollback()

    assert statuses == ["issued", "issued", "rate_limited", "rate_limited"]


async def test_issuance_stops_at_the_global_ceiling(db_pool, seeded_users) -> None:
    """The global ceiling is the one that matters: every visitor shares a single
    identity, so an attacker rotating client keys is the expected shape."""
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _enable_demo_in_transaction(conn, seeded_users)
            statuses = [
                json.loads(
                    await conn.fetchval(
                        "select issue_demo_session($1, $2, $3)", f"{i:032x}", 20, 3
                    )
                )["status"]
                for i in range(5)
            ]
        finally:
            await tr.rollback()

    assert statuses.count("issued") == 3
    assert statuses[3:] == ["rate_limited", "rate_limited"]


async def test_issuance_is_serialized_against_a_concurrent_caller(db_pool) -> None:
    """The heart of C2: the ceiling is only real if the decision is serialized.

    The old function counted, decided, then inserted with no lock, so under READ
    COMMITTED every concurrent caller read the same below-limit count and every
    one of them issued. Rather than race hundreds of requests and hope to catch
    the overshoot, this proves the mechanism directly.

    The lock is asserted by identity, not merely by observing that a second
    caller blocks: both callers also touch the same global counter row, so
    *something* would block either way and a blocking-only test would pass
    against a function with no advisory lock at all.
    """
    async with db_pool.acquire() as first, db_pool.acquire() as second:
        outer = first.transaction()
        await outer.start()
        try:
            await first.fetchval(
                "select issue_demo_session($1, $2, $3)", "b" * 32, 20, 600
            )

            # 8274531 is the constant in 20260901000007. A bigint advisory key
            # of that size lands in (classid 0, objid <key>).
            held = await second.fetchval(
                "select count(*) from pg_locks"
                " where locktype = 'advisory' and classid = 0 and objid = 8274531"
                "   and granted"
            )
            assert held == 1, "issuance must hold its advisory lock for the transaction"

            # And it is held to the end of the transaction, not released early.
            inner = second.transaction()
            await inner.start()
            try:
                await second.execute("set local lock_timeout = '750ms'")
                with pytest.raises(asyncpg.PostgresError) as caught:
                    await second.fetchval(
                        "select issue_demo_session($1, $2, $3)", "c" * 32, 20, 600
                    )
                assert caught.value.sqlstate == "55P03", "expected a lock timeout"
            finally:
                await inner.rollback()
        finally:
            await outer.rollback()

    # Released with the transaction.
    async with db_pool.acquire() as check:
        assert (
            await check.fetchval(
                "select count(*) from pg_locks"
                " where locktype = 'advisory' and classid = 0 and objid = 8274531"
            )
            == 0
        )


async def test_issuance_refuses_a_malformed_client_key(db_pool) -> None:
    """Defence in depth (R2 M6): only the API calls this today, but a SECURITY
    DEFINER function should not take its caller's word for its own inputs."""
    async with db_pool.acquire() as conn:
        for bad_key, per_key, global_hour in [
            ("not-a-digest", 20, 600),
            ("a" * 32, 0, 600),
            ("a" * 32, 20, 0),
        ]:
            with pytest.raises(asyncpg.PostgresError):
                await conn.fetchval(
                    "select issue_demo_session($1, $2, $3)",
                    bad_key,
                    per_key,
                    global_hour,
                )


# ── R2 H1: an existing installation upgrades to the virtual principal ────────


def _seed_module():
    """Load the seed script by path; `scripts/` is not an installed package."""
    import importlib.util

    path = (
        pathlib.Path(__file__).resolve().parents[2] / "scripts" / "seed_demo_hunt.py"
    )
    spec = importlib.util.spec_from_file_location("seed_demo_hunt", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


async def test_an_existing_real_account_principal_upgrades(db_pool, seeded_users) -> None:
    """The H1 case: every installation seeded before v3.55 has one of these.

    The old order inserted the new principal before deleting the old one, so the
    singleton index rejected the insert and the delete never ran -- leaving the
    operator with a principal that `demo_preflight()` refuses (it has an
    `auth.users` row) and no way to replace it short of manual SQL.
    """
    seed = _seed_module()
    owner = seeded_users["owner"].user_id
    legacy = seeded_users["outsider"].user_id

    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute("delete from demo_accounts")
            await conn.execute(
                "insert into demo_accounts (user_id, note) values ($1, 'legacy')",
                legacy,
            )
            # Precondition: the legacy principal is a real Auth account.
            assert await conn.fetchval(
                "select exists (select 1 from auth.users where id = $1)", legacy
            )

            warnings = await seed.reconcile_demo_principal(conn, owner)

            rows = await conn.fetch("select user_id from demo_accounts")
            assert [r["user_id"] for r in rows] == [seed.DEMO_PRINCIPAL_ID]
            assert any("still has an auth.users row" in w for w in warnings), (
                "the stranded Auth account must be reported, not silently left"
            )
        finally:
            await tr.rollback()


async def test_reconciling_is_idempotent(db_pool, seeded_users) -> None:
    seed = _seed_module()
    owner = seeded_users["owner"].user_id
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute("delete from demo_accounts")
            first = await seed.reconcile_demo_principal(conn, owner)
            second = await seed.reconcile_demo_principal(conn, owner)
            assert first == [] and second == []
            assert await conn.fetchval("select count(*) from demo_accounts") == 1
        finally:
            await tr.rollback()


async def test_seeding_refuses_a_principal_that_has_an_account(
    db_pool, seeded_users
) -> None:
    """The virtual principal is the whole C3 defence; a collision must stop the
    seed rather than quietly reintroduce a takeable GoTrue identity."""
    seed = _seed_module()
    owner = seeded_users["owner"].user_id
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute("delete from demo_accounts")
            # Give the deterministic principal id a real Auth row.
            await conn.execute(
                "insert into auth.users (id, instance_id, aud, role, email)"
                " values ($1, '00000000-0000-0000-0000-000000000000',"
                " 'authenticated', 'authenticated', 'collision@test.manzil')",
                seed.DEMO_PRINCIPAL_ID,
            )
            with pytest.raises(seed.DemoPrincipalConflict):
                await seed.reconcile_demo_principal(conn, owner)
        finally:
            await tr.rollback()


# ── R2 H4: the toggle and its audit entry ────────────────────────────────────


async def test_enabling_the_demo_without_an_audit_entry_is_impossible(
    db_pool, seeded_users
) -> None:
    """Enable is atomic with its audit row: a public exposure with no record of
    who caused it is not an acceptable outcome, so if the ledger cannot be
    written the setting must not change either."""
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _enable_demo_in_transaction(conn, seeded_users)
            await conn.execute("update site_settings set demo_enabled = false")

            inner = conn.transaction()
            await inner.start()
            try:
                await conn.fetchval(
                    "select set_demo_enabled($1, $2)",
                    True,
                    seeded_users["owner"].user_id,
                )
                assert await conn.fetchval("select demo_enabled from site_settings")
                # Simulate the audit insert failing inside the same transaction.
                with pytest.raises(asyncpg.PostgresError):
                    await conn.execute("insert into admin_audit_log (action) values (null)")
            finally:
                await inner.rollback()

            assert not await conn.fetchval("select demo_enabled from site_settings"), (
                "a failed audit write must take the setting change with it"
            )
        finally:
            await tr.rollback()


# ── R2 `R2`: the toggle *route*, not just the SQL underneath it ──────────────
#
# `grep -rn "admin/demo" api/tests/` returned nothing before this. The test
# above asserts Postgres savepoint semantics, which the pre-fix implementation
# -- two separate pool calls, no shared transaction -- also satisfies, because
# what it demonstrates is that a rolled-back subtransaction takes its writes
# with it. That is true of Postgres, not of the route. The route's deliberate
# asymmetry (DESIGN §16 control 5) needs both halves driven over HTTP.


@pytest_asyncio.fixture
async def demo_toggle_admin(db_pool, seeded_users):
    """A Site Admin client, and a demo configuration that preflight accepts.

    Committed rather than transactional: the route uses the pool, so a
    rolled-back fixture would be invisible to it. Everything is restored in the
    teardown, including the caller's own `site_settings` row and `demo_accounts`.
    """
    app = create_app()
    app.state.db_pool = db_pool
    identity = seeded_users["outsider"]

    before = await db_pool.fetchrow(
        "select demo_enabled, demo_hunt_id from site_settings"
    )
    markers = [
        dict(row)
        for row in await db_pool.fetch("select user_id, created_by, note from demo_accounts")
    ]
    primordial = await db_pool.fetchval(
        "select user_id from site_admins where is_primordial limit 1"
    )
    if primordial is None:
        pytest.skip("no primordial Site Admin; bootstrap the local admin first (AGENTS.md)")

    hunt = await db_pool.fetchval(
        "insert into hunts (name, owner_id) values ('Demo toggle test', $1) returning id",
        primordial,
    )
    await db_pool.execute(
        "insert into site_admins (user_id) values ($1) on conflict do nothing",
        identity.user_id,
    )
    await db_pool.execute("delete from demo_accounts")
    await db_pool.execute(
        "insert into demo_accounts (user_id, note) values ($1, 'toggle route test')",
        uuid.uuid4(),
    )
    await db_pool.execute(
        "update site_settings set demo_enabled = false, demo_hunt_id = $1", hunt
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {identity.token}"},
        ) as client:
            yield client
    finally:
        await db_pool.execute(
            "update site_settings set demo_enabled = $1, demo_hunt_id = $2",
            before["demo_enabled"],
            before["demo_hunt_id"],
        )
        await db_pool.execute("delete from demo_accounts")
        for row in markers:
            await db_pool.execute(
                "insert into demo_accounts (user_id, created_by, note) values ($1, $2, $3)",
                row["user_id"],
                row["created_by"],
                row["note"],
            )
        await db_pool.execute("delete from hunts where id = $1", hunt)
        await db_pool.execute(
            "delete from site_admins where user_id = $1", identity.user_id
        )
        # `admin_audit_log` is deliberately append-only, so nothing is removed
        # from it here. Neither test below writes to it: the enable test's audit
        # write is the thing that fails, and the disable test reaches the
        # enabled state through the same SQL the route calls rather than through
        # the route, precisely so this ledger is left alone.


def _audit_always_fails(monkeypatch) -> None:
    """Make the Admin Audit Log unavailable, the way a real outage would."""

    async def boom(*args, **kwargs) -> None:
        raise asyncpg.PostgresError("audit log unavailable")

    monkeypatch.setattr(AdminAudit, "record", boom)


async def test_enabling_the_demo_is_refused_when_the_audit_cannot_be_written(
    demo_toggle_admin, db_pool, monkeypatch
) -> None:
    """Turning the demo *on* makes the app publicly reachable. If that cannot be
    recorded, it must not happen -- so the route holds one transaction across
    both writes and the failure takes the setting with it."""
    _audit_always_fails(monkeypatch)

    response = await demo_toggle_admin.patch("/v1/admin/demo", json={"enabled": True})

    assert response.status_code >= 500, f"expected the call to fail, got {response.status_code}"
    assert not await db_pool.fetchval("select demo_enabled from site_settings"), (
        "the demo was enabled with no Admin Audit Log entry"
    )


async def test_disabling_the_demo_survives_a_failing_audit(
    demo_toggle_admin, db_pool, monkeypatch, caplog
) -> None:
    """And the other half, which is deliberately *not* symmetric: an emergency
    shutoff must not be refusable by the conditions that made it an emergency.
    Disabling commits first and audits afterwards; a failure there is logged
    loudly and the shutoff stands."""
    admin_id = await db_pool.fetchval(
        "select user_id from site_admins where is_primordial limit 1"
    )
    await db_pool.fetchval("select set_demo_enabled(true, $1)", admin_id)
    assert await db_pool.fetchval("select demo_enabled from site_settings")

    _audit_always_fails(monkeypatch)
    with caplog.at_level(logging.ERROR):
        response = await demo_toggle_admin.patch("/v1/admin/demo", json={"enabled": False})

    assert response.status_code == 200 and response.json() == {"enabled": False}
    assert not await db_pool.fetchval("select demo_enabled from site_settings"), (
        "a failing audit table must not be able to keep the demo switched on"
    )
    assert any("audit entry failed" in record.getMessage() for record in caplog.records), (
        "an unaudited shutoff must be loud, not silent"
    )


async def test_toggling_rotates_the_demo_generation(db_pool, seeded_users) -> None:
    """The revocation lever. Every toggle invalidates every issued token."""
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            actor = seeded_users["owner"].user_id
            before = await conn.fetchval("select demo_generation from site_settings")
            await conn.fetchval("select set_demo_enabled($1, $2)", False, actor)
            after = await conn.fetchval("select demo_generation from site_settings")
            assert after == before + 1
        finally:
            await tr.rollback()


# ── R2 `R6`-`R8`: the hardening tail (20260901000009) ────────────────────────


async def test_the_kill_switch_is_read_under_the_issuance_lock(db_pool) -> None:
    """`R6`. Reading `demo_enabled` before taking the advisory lock and not again
    under it widens the window in which a disable races an in-flight issuance.
    Today that window is survivable only because the rotated generation renders
    the minted token `dark` -- one control compensating for another's gap, which
    is exactly the arrangement that should not be able to drift silently.

    Asserted structurally because the alternative is racing a lock and hoping to
    observe the interleaving that is being ruled out.
    """
    body = await db_pool.fetchval(
        "select pg_get_functiondef("
        "'public.issue_demo_session(text,integer,integer)'::regprocedure)"
    )
    lock_at = body.index("pg_advisory_xact_lock")
    read_at = body.index("from site_settings")
    assert lock_at < read_at, (
        "issue_demo_session reads site_settings before taking its advisory lock"
    )


async def test_the_bucket_expression_cannot_raise_or_reach_the_sentinel(db_pool) -> None:
    """`R8`, both halves.

    `abs(hashtextextended(...))` raises `22003` on `bigint` min, which turns one
    unlucky client key into a permanent 500 on the public endpoint. And the
    obvious repair is worse: Postgres `%` keeps the dividend's sign, so a plain
    `hashtextextended(...) % 4096` returns -4095..4095 -- and `-1` is the
    reserved *global* bucket. A key landing there would take the sentinel branch,
    escape the per-key ceiling entirely, and double-count the global row. Over
    200k sampled keys a signed remainder puts 22 of them on it.
    """
    body = await db_pool.fetchval(
        "select pg_get_functiondef("
        "'public.issue_demo_session(text,integer,integer)'::regprocedure)"
    )
    assert "abs(hashtextextended" not in body, "abs() raises on bigint min"
    assert (
        "((hashtextextended(p_client_key, 0) % c_buckets) + c_buckets)\n"
        "              % c_buckets" in body
    ), "the double modulo is the fix; a single one can reach the -1 sentinel"

    # The failure mode itself, so the test says what it is protecting against
    # rather than only pinning a string.
    with pytest.raises(asyncpg.NumericValueOutOfRangeError):
        await db_pool.fetchval("select abs((-9223372036854775808)::bigint) % 4096")
    assert (
        await db_pool.fetchval(
            "select (((-9223372036854775808)::bigint % 4096) + 4096) % 4096"
        )
        == 0
    )

    # And the behaviour, measured rather than recomputed: the buckets the
    # function actually writes for a spread of real keys.
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute("delete from demo_session_counters")
            for i in range(500):
                await conn.fetchval(
                    "select issue_demo_session($1, $2, $3)",
                    f"{uuid.uuid4().hex}{i:032x}"[:64],
                    20,
                    600,
                )
            buckets = [
                row["client_bucket"]
                for row in await conn.fetch(
                    "select client_bucket from demo_session_counters where client_bucket <> -1"
                )
            ]
        finally:
            await tr.rollback()

    assert buckets, "no keyed buckets were recorded; the sample proved nothing"
    assert min(buckets) >= 0 and max(buckets) < 4096, f"bucket out of domain: {buckets}"


async def test_the_counter_table_refuses_a_bucket_below_the_global_sentinel(db_pool) -> None:
    """`R8`'s belt to the function's braces: if the expression ever starts
    producing signed remainders again, the row is refused rather than quietly
    merged into the global counter."""
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    "insert into demo_session_counters (window_start, client_bucket)"
                    " values (now(), -2)"
                )
        finally:
            await tr.rollback()


async def test_an_image_key_must_carry_the_properties_prefix(db_pool, seeded_users) -> None:
    """`R7`. `can_read_property_image` read `(storage.foldername(name))[2]` as the
    Property id without pinning `[1]`, so `zzz/<property-uuid>/x.webp` authorised
    exactly as the real key does.

    Not exploitable today -- the only `authenticated` policies on
    `storage.objects` are SELECT, so nothing can place an object under a prefix
    of its choosing. That is a property of the *other* policies though, and this
    is the function that answers "may you read this object".
    """
    owner = seeded_users["owner"].user_id
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            hunt = await conn.fetchval(
                "insert into hunts (name, owner_id) values ('R7 prefix', $1) returning id",
                owner,
            )
            prop = await conn.fetchval(
                "insert into properties (name, canonical_address)"
                " values ('R7 prefix', '1 Prefix Way') returning id"
            )
            await conn.execute(
                "insert into hunt_listings (hunt_id, property_id, added_by)"
                " values ($1, $2, $3)",
                hunt,
                prop,
                owner,
            )
            await conn.fetchval(
                "select set_config('request.jwt.claims', $1, true)",
                json.dumps({"sub": str(owner), "role": "authenticated"}),
            )

            async def readable(name: str) -> bool:
                return await conn.fetchval(
                    "select private.can_read_property_image($1)", name
                )

            # The positive control: without it a function that refused
            # everything would satisfy every assertion below.
            assert await readable(f"properties/{prop}/abc123.webp"), (
                "the real key must still authorise, or this test proves nothing"
            )
            for forged in (
                f"zzz/{prop}/abc123.webp",
                f"public/{prop}/abc123.webp",
                f"a/b/{prop}/abc123.webp",
                f"{prop}/abc123.webp",
                f"properties/{prop}/nested/abc123.webp",
            ):
                assert not await readable(forged), f"{forged} authorised"
        finally:
            await tr.rollback()
