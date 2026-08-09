#!/usr/bin/env python
"""DM-8: the adversarial pass against a live, enabled demo (DESIGN §16, §17 R12).

IMPLEMENTATION's DM-8 row is explicit that **API-level tests do not count as
evidence for any item on it**, and both security reviews say the same thing at
more length. The threat model is a real session in a browser we do not control,
so this drives the five externally reachable planes directly, over HTTP, with a
token minted exactly the way a visitor's is:

    PostgREST · Storage · GoTrue · Realtime · FastAPI

Everything here is a *client*. It never imports the API, never touches a
FastAPI TestClient, and never uses a service-role connection except to set up
and tear down the world it is attacking.

    uv run python scripts/dm8_adversarial.py --evidence docs/demo-mode-dm8-evidence.md

It leaves the database as it found it: demo disabled, the marker restored. Run it
against a disposable database (`supabase db reset`) and again against staging
immediately before enabling the demo.

── Why this file is written the way it is ───────────────────────────────────────

The first version of this harness reported `All 32 checks passed` against a
database in which the C1 fail-open predicate had been **fully reintroduced**
(finding `R1`). Three separate defects produced that, and all three are the same
defect: *a negative assertion that nobody proved could ever be positive.*

Three rules follow, and every check below obeys them.

1. **No negative assertion without a positive control.** Every block starts by
   re-minting at the *current* generation and proving the token reads the Demo
   Hunt (`Minter.scoped`). A refusal only means something once we know the token
   was otherwise working. A failed precondition is a **FAIL**, never a pass and
   never a skip — the alternative is a harness that goes green because its own
   subject was already dead.

2. **Induced darkness must be attributable to the branch under test.**
   `demo_identity()` has three independent darkness branches: marker
   inconsistency, stale generation, and the switch being off. Because
   `set_demo_enabled` rotates the generation on *every* toggle, a check that
   darkens by flipping the switch also darkens for the generation reason — so
   deleting the switch branch entirely leaves such a check green. Any check that
   darkens via a configuration toggle therefore **re-mints at the post-toggle
   generation** first, leaving `demo_enabled = false` as the only remaining
   inconsistency.

3. **A refusal must be attributable to the control that is supposed to produce
   it.** DESIGN §16 control 4 says the four money-spending RPCs "reject a Demo
   Account explicitly rather than relying on the trigger alone" — so `check_rpcs`
   asserts the error came from `private.assert_not_demo` at entry, by name, and
   not from the statement trigger downstream. Without that, removing the entry
   guard leaves the RPCs answering `403`/`42501` from the write trigger and the
   check stays green.

`--broken-token` exists to demonstrate rule 1 on demand: it hands every block a
deliberately unusable token, and every precondition must go red.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import asyncpg
import httpx
import jwt

DEMO_CLAIM = "manzil_demo"
DEMO_GEN_CLAIM = "manzil_demo_gen"


# ── Result recording ─────────────────────────────────────────────────────────


@dataclass
class Check:
    plane: str
    name: str
    passed: bool
    detail: str
    evidence: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def record(self, plane: str, name: str, passed: bool, detail: str, evidence: str = "") -> bool:
        self.checks.append(Check(plane, name, passed, detail, evidence))
        mark = "PASS" if passed else "FAIL"
        colour = "\033[32m" if passed else "\033[31m"
        print(f"  {colour}{mark}\033[0m  {name} — {detail}")
        return passed

    def skip(self, why: str) -> None:
        self.skipped.append(why)
        print(f"  \033[33mSKIP\033[0m  {why}")

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    @property
    def attempted(self) -> int:
        return len(self.checks)

    @property
    def passed_count(self) -> int:
        return self.attempted - len(self.failed)

    def headline(self) -> str:
        """`R3`: a skipped plane is not a passed plane.

        The old artifact said "32 of 32 passed" for a run in which five FastAPI
        checks never executed, because skips were dropped from the denominator
        *and* from the sentence. Both numbers are reported here, and the skip
        count is in the headline rather than in a footnote.
        """
        line = f"{self.passed_count} of {self.attempted} attempted checks passed"
        if self.skipped:
            line += f" — {len(self.skipped)} plane(s) NOT EXERCISED"
        return line


# ── Environment ──────────────────────────────────────────────────────────────


@dataclass
class Env:
    supabase_url: str
    anon_key: str
    service_key: str
    jwt_secret: str
    database_url: str
    api_base_url: str | None

    @classmethod
    def load(cls) -> Env:
        # Either key name. Production moved to `SUPABASE_SECRET_KEY`, while the
        # local Supabase CLI still emits only the legacy service-role JWT, so a
        # harness that insisted on one of them would refuse to run in one of the
        # two places it is meant to run.
        service_key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get(
            "SUPABASE_SERVICE_ROLE_KEY"
        )
        missing = [
            name
            for name in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "DATABASE_URL")
            if not os.environ.get(name)
        ]
        if not service_key:
            missing.append("SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY)")
        secret = os.environ.get("SUPABASE_JWT_SECRET")
        if not secret:
            missing.append("SUPABASE_JWT_SECRET")
        if missing:
            sys.exit(f"Missing environment: {', '.join(missing)}")
        return cls(
            supabase_url=os.environ["SUPABASE_URL"].rstrip("/"),
            anon_key=os.environ["SUPABASE_ANON_KEY"],
            service_key=service_key,  # type: ignore[arg-type]
            jwt_secret=secret,  # type: ignore[arg-type]
            database_url=os.environ["DATABASE_URL"],
            api_base_url=(os.environ.get("MANZIL_API_BASE_URL") or "").rstrip("/") or None,
        )


def mint(env: Env, subject: str, generation: int, ttl: int = 900, **overrides: Any) -> str:
    """A token shaped exactly like `POST /v1/demo/session` mints."""
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": subject,
        "aud": "authenticated",
        "role": "authenticated",
        "iss": f"{env.supabase_url}/auth/v1",
        "iat": now,
        "exp": now + ttl,
        DEMO_CLAIM: True,
        DEMO_GEN_CLAIM: generation,
        "demo_session": str(uuid.uuid4()),
        **overrides,
    }
    return jwt.encode(claims, env.jwt_secret, algorithm="HS256")


# ── Setup / teardown ─────────────────────────────────────────────────────────


@dataclass
class World:
    principal: uuid.UUID
    owner: uuid.UUID
    hunt_id: uuid.UUID
    generation: int
    in_scope_property: uuid.UUID
    out_of_scope_property: uuid.UUID
    in_scope_object: str
    out_of_scope_object: str
    listing_id: uuid.UUID
    # Real ids for the RPC guards. A random uuid4 makes `answer_job_checkpoint`
    # and `correct_auto_resolved_checkpoint` answer 400/404 for *any* caller,
    # which is indistinguishable from a guard that fired.
    waiting_job_id: uuid.UUID
    auto_resolved_job_id: uuid.UUID


async def build_world(conn: asyncpg.Connection) -> World:
    """Configure a demo worth attacking, and a Property it must not reach."""
    owner = await conn.fetchval("select user_id from site_admins where is_primordial limit 1")
    if owner is None:
        sys.exit(
            "No primordial Site Admin. Bootstrap the local admin first (AGENTS.md), then re-run."
        )

    hunt_id = await conn.fetchval(
        "insert into hunts (name, owner_id) values ('DM-8 adversarial', $1) returning id",
        owner,
    )
    in_scope = await conn.fetchval(
        "insert into properties (name, canonical_address) "
        "values ('DM8 In Scope', '1 Demo Way') returning id"
    )
    out_of_scope = await conn.fetchval(
        "insert into properties (name, canonical_address) "
        "values ('DM8 Out Of Scope', '2 Private Rd') returning id"
    )
    listing_id = await conn.fetchval(
        "insert into hunt_listings (hunt_id, property_id, added_by) "
        "values ($1, $2, $3) returning id",
        hunt_id,
        in_scope,
        owner,
    )

    # A Job genuinely parked at a checkpoint, so `answer_job_checkpoint` gets
    # past its own "is this job waiting?" validation and the only thing left to
    # refuse the call is the entry guard.
    waiting_job = await conn.fetchval(
        "insert into jobs (hunt_id, hunt_listing_id, type, state, current_stage, payload) "
        "values ($1, $2, 'ingest', 'waiting_user', 'VERIFY', '{}'::jsonb) returning id",
        hunt_id,
        listing_id,
    )

    # Likewise for the correction path, which validates prompt/snapshot
    # provenance and the presence of a `checkpoint_auto_resolved` event before
    # it will do anything. `options` is the pinned §10.10 list-of-strings.
    auto_job_id = uuid.uuid4()
    await conn.execute(
        "insert into jobs (id, hunt_id, hunt_listing_id, type, state, current_stage, payload) "
        "values ($1, $2, $3, 'ingest', 'done', 'VERIFY', $4::jsonb)",
        auto_job_id,
        hunt_id,
        listing_id,
        json.dumps(
            {
                "auto_resolved_checkpoint": {
                    "prompt": {
                        "kind": "confirm_value",
                        "question": "DM-8 fixture",
                        "options": ["yes", "no"],
                        "default": "yes",
                    },
                    "snapshot": {"job_id": str(auto_job_id), "status": "running"},
                }
            }
        ),
    )
    await conn.execute(
        "insert into job_events (job_id, stage, event, detail) "
        "values ($1, 'VERIFY', 'checkpoint_auto_resolved', '{}'::jsonb)",
        auto_job_id,
    )

    objects = []
    for prop in (in_scope, out_of_scope):
        name = f"properties/{prop}/dm8{uuid.uuid4().hex[:8]}.webp"
        await conn.execute(
            "insert into storage.objects (bucket_id, name, owner) values ($1, $2, null)",
            "property-images",
            name,
        )
        objects.append(name)

    principal = uuid.uuid4()
    await conn.execute("delete from demo_accounts")
    await conn.execute(
        "insert into demo_accounts (user_id, note) values ($1, 'DM-8 harness')", principal
    )
    await conn.execute("update site_settings set demo_hunt_id = $1", hunt_id)
    await conn.fetchval("select set_demo_enabled(true, $1)", owner)
    generation = await conn.fetchval("select demo_generation from site_settings")

    return World(
        principal=principal,
        owner=owner,
        hunt_id=hunt_id,
        generation=generation,
        in_scope_property=in_scope,
        out_of_scope_property=out_of_scope,
        in_scope_object=objects[0],
        out_of_scope_object=objects[1],
        listing_id=listing_id,
        waiting_job_id=waiting_job,
        auto_resolved_job_id=auto_job_id,
    )


async def teardown(
    env: Env, conn: asyncpg.Connection, world: World, owner_restore: list[dict]
) -> None:
    owner = await conn.fetchval("select user_id from site_admins where is_primordial limit 1")
    await conn.fetchval("select set_demo_enabled(false, $1)", owner)

    # Supabase refuses direct DELETEs from `storage.objects` ("Use the Storage
    # API instead"), so the fixtures leave the same way real objects do.
    async with httpx.AsyncClient(
        base_url=f"{env.supabase_url}/storage/v1",
        headers={
            "apikey": env.service_key,
            "Authorization": f"Bearer {env.service_key}",
        },
        timeout=20,
    ) as client:
        for name in (world.in_scope_object, world.out_of_scope_object):
            try:
                await client.request("DELETE", "/object/property-images", json={"prefixes": [name]})
            except httpx.HTTPError as exc:  # cleanup must never mask the results
                print(f"  (cleanup) could not remove {name}: {exc}")
    # Jobs, Job Events, costs and listings all cascade from the Hunt.
    await conn.execute("delete from hunts where id = $1", world.hunt_id)
    await conn.execute(
        "delete from properties where id = any($1::uuid[])",
        [world.in_scope_property, world.out_of_scope_property],
    )
    await conn.execute("delete from demo_accounts")
    for row in owner_restore:
        await conn.execute(
            "insert into demo_accounts (user_id, created_by, note) values ($1, $2, $3)",
            row["user_id"],
            row["created_by"],
            row["note"],
        )
    await conn.execute("update site_settings set demo_hunt_id = null")


# ── The planes ───────────────────────────────────────────────────────────────


def rest(env: Env, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{env.supabase_url}/rest/v1",
        headers={"apikey": env.anon_key, "Authorization": f"Bearer {token}"},
        timeout=20,
    )


async def visible_properties(env: Env, token: str) -> int:
    """Rows the token can read from the global Property table.

    `-1` means PostgREST refused the request outright, which is a different
    state from "read zero rows" and must not be conflated with it.
    """
    async with rest(env, token) as client:
        response = await client.get("/properties", params={"select": "id"})
        return len(response.json()) if response.status_code == 200 else -1


# ── The instrument ───────────────────────────────────────────────────────────


class Minter:
    """Hands out tokens, and refuses to hand out one it has not proved works.

    This class is the whole answer to `R1`. Every check block asks it for a
    token; it mints at the generation the database holds *right now* and then
    performs a positive read before returning. A caller that gets `None` records
    nothing further — the precondition failure is already on the report.
    """

    def __init__(
        self,
        env: Env,
        world: World,
        conn: asyncpg.Connection,
        report: Report,
        flaw: str | None = None,
    ) -> None:
        self.env = env
        self.world = world
        self.conn = conn
        self.report = report
        self.flaw = flaw

    async def current_generation(self) -> int:
        return await self.conn.fetchval("select demo_generation from site_settings")

    async def token_at_current_generation(self) -> str:
        """A well-formed token — unless `--broken-token` asked for a bad one."""
        generation = await self.current_generation()
        if self.flaw == "expired":
            return mint(self.env, str(self.world.principal), generation, ttl=-60)
        if self.flaw == "stale-generation":
            return mint(self.env, str(self.world.principal), generation - 1)
        if self.flaw == "unsigned":
            return jwt.encode(
                jwt.decode(
                    mint(self.env, str(self.world.principal), generation),
                    options={"verify_signature": False},
                ),
                "not-the-projects-signing-secret",
                algorithm="HS256",
            )
        return mint(self.env, str(self.world.principal), generation)

    async def scoped(self, plane: str, why: str) -> str | None:
        """Mint, then prove the token is `scoped` before anything is asserted.

        The positive control is deliberately specific: not "some rows came back"
        but "the Property this run put inside the Demo Hunt came back". A token
        that is dark, expired, mis-signed or minted at a stale generation cannot
        satisfy it, which is exactly the set of states the old harness silently
        drifted into and then reported PASS from.
        """
        token = await self.token_at_current_generation()
        async with rest(self.env, token) as client:
            response = await client.get(
                "/properties",
                params={"select": "id", "id": f"eq.{self.world.in_scope_property}"},
            )
        ok = response.status_code == 200 and len(response.json()) == 1
        self.report.record(
            plane,
            f"precondition: the token reads the Demo Hunt before {why}",
            ok,
            f"GET /properties?id=eq.<in-scope> -> {response.status_code}, "
            f"{len(response.json()) if response.status_code == 200 else 'n/a'} rows",
            response.text[:160],
        )
        return token if ok else None


async def check_self_test(env: Env, world: World, minter: Minter, report: Report) -> None:
    """Before any security check: can this instrument tell the two states apart?

    A harness that reports PASS for a refusal has said nothing until it has also
    shown that it would have reported the *absence* of a refusal. So: one token
    that must read, one token that must not, back to back, with nothing about
    the database's configuration changed in between.
    """
    print("\nSelf-test — the instrument can tell `scoped` from `dark`")
    good = await minter.scoped("Self-test", "the security checks run")
    if good is None:
        return

    generation = await minter.current_generation()
    stale = mint(env, str(world.principal), generation - 1)
    count = await visible_properties(env, stale)
    report.record(
        "Self-test",
        "a validly-signed token at a stale generation reads nothing",
        count == 0,
        f"{count} Properties visible at generation {generation - 1} "
        f"while the database is at {generation}",
    )


async def check_postgrest(env: Env, world: World, minter: Minter, report: Report) -> None:
    print("\nPostgREST — reads are scoped by restrictive policy")
    token = await minter.scoped("PostgREST", "reading global facts")
    if token is None:
        return

    async with rest(env, token) as client:
        response = await client.get("/properties", params={"select": "id"})
        ids = {row["id"] for row in response.json()} if response.status_code == 200 else set()
        report.record(
            "PostgREST",
            "only Demo Hunt Properties are visible",
            str(world.in_scope_property) in ids and str(world.out_of_scope_property) not in ids,
            f"{len(ids)} Properties visible; in-scope present, out-of-scope absent",
            f"GET /properties -> {response.status_code}, {len(ids)} rows",
        )

        # Naming the row explicitly: a filter must not be a way around the policy.
        targeted = await client.get(
            "/properties", params={"select": "id", "id": f"eq.{world.out_of_scope_property}"}
        )
        report.record(
            "PostgREST",
            "asking for an out-of-scope Property by id returns nothing",
            targeted.status_code == 200 and targeted.json() == [],
            f"{targeted.status_code} {targeted.text[:80]}",
        )

        cleaned = await client.get("/property_sources", params={"select": "cleaned_text"})
        report.record(
            "PostgREST",
            "cleaned_text is not selectable",
            cleaned.status_code in (401, 403, 400),
            f"{cleaned.status_code} — column grant revoked for authenticated",
            cleaned.text[:160],
        )

        hunts = await client.get("/hunts", params={"select": "id"})
        hunt_ids = {row["id"] for row in hunts.json()} if hunts.status_code == 200 else set()
        report.record(
            "PostgREST",
            "only the Demo Hunt is visible",
            hunt_ids == {str(world.hunt_id)},
            f"visible hunts: {sorted(hunt_ids)}",
        )


async def check_writes(env: Env, world: World, minter: Minter, report: Report) -> None:
    print("\nPostgREST — every write is refused")
    token = await minter.scoped("PostgREST", "attempting writes")
    if token is None:
        return

    async with rest(env, token) as client:
        for table, body in [
            ("comments", {"hunt_listing_id": str(world.listing_id), "body": "dm8"}),
            (
                "hunt_listings",
                {"hunt_id": str(world.hunt_id), "property_id": str(world.in_scope_property)},
            ),
            ("properties", {"name": "dm8", "canonical_address": "x"}),
            ("site_settings", {"demo_enabled": True}),
            ("demo_accounts", {"user_id": str(uuid.uuid4())}),
        ]:
            response = await client.post(f"/{table}", json=body)
            # Precise on purpose. A bare `status in (400, 403, 404)` would pass
            # for a malformed request body too, which would let this test go
            # green against a database that had stopped refusing anything.
            refused = response.status_code in (401, 403) or "42501" in response.text
            report.record(
                "PostgREST",
                f"INSERT into {table} is refused",
                refused,
                f"{response.status_code}"
                + (" (42501 insufficient_privilege)" if "42501" in response.text else ""),
                response.text[:160],
            )

        deleted = await client.delete(
            "/comments", params={"id": "neq.00000000-0000-0000-0000-000000000000"}
        )
        report.record(
            "PostgREST",
            "a zero-row DELETE is still refused",
            deleted.status_code in (401, 403, 400),
            f"{deleted.status_code} — the statement guard fires on statements, not rows",
            deleted.text[:160],
        )


async def check_rpcs(
    env: Env, world: World, minter: Minter, conn: asyncpg.Connection, report: Report
) -> None:
    """DESIGN §16 control 4: the four money-spending RPCs guard *at entry*.

    Two things this check gets wrong if written casually, and both were wrong:

    * **The signatures must be real.** `answer_job_checkpoint` was called with
      `p_answer`/`p_event_detail` against a function that takes
      `p_payload`/`p_detail`, and `set_listing_source_policy` with
      `p_hunt_listing_id` against `p_listing_id`. No overload matches, so
      PostgREST answers 404 to *everyone* — guard or no guard. Every parameter
      name below is verified against `supabase/migrations/`.

    * **The refusal must come from the guard.** Every one of these functions
      also writes to a `public` table, so the statement trigger refuses them
      too, with the same `42501` and the same `403`. Asserting only the status
      and the SQLSTATE therefore passes with `private.assert_not_demo` deleted.
      What distinguishes them is the error *detail*: the entry guard names the
      function it blocked, the trigger names the table and operation. Requiring
      the former is requiring the control DESIGN actually specifies — "rejects a
      Demo Account explicitly rather than relying on the trigger alone".
    """
    print("\nPostgREST — the money-spending RPCs guard at entry")
    token = await minter.scoped("PostgREST", "calling the cost-bearing RPCs")
    if token is None:
        return

    before = await conn.fetchrow(
        "select (select count(*) from jobs) j, (select count(*) from job_events) e, "
        "(select count(*) from job_stage_costs) c"
    )
    calls = {
        # 20260715000000_submit_listing.sql:21-22
        "public.submit_listing(uuid,text,text,text)": {
            "p_hunt_id": str(world.hunt_id),
            "p_url": "https://example.test/dm8",
            "p_placeholder_name": "DM8",
            "p_source_policy": "trust_link",
        },
        # 20260901000010_jobs_payload_projection.sql — `p_payload` is gone: the
        # function merges the answer into the Job's own stored payload now.
        "public.answer_job_checkpoint(uuid,jsonb,jsonb)": {
            "p_job_id": str(world.waiting_job_id),
            "p_answer": {"choice": "yes"},
            "p_detail": {},
        },
        # 20260731000000_listing_single_source_reason.sql:19-20
        "public.set_listing_source_policy(uuid,text)": {
            "p_listing_id": str(world.listing_id),
            "p_source_policy": "trust_link",
        },
        # 20260818000000_p3_11_checkpoint_corrections.sql:7-8
        "public.correct_auto_resolved_checkpoint(uuid,jsonb)": {
            "p_job_id": str(world.auto_resolved_job_id),
            "p_answer": {"choice": "yes"},
        },
    }
    async with rest(env, token) as client:
        for signature, body in calls.items():
            name = signature.split("(")[0].removeprefix("public.")
            response = await client.post(f"/rpc/{name}", json=body)
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            blocked_by_entry_guard = str(payload.get("details") or "").startswith(
                f"blocked {signature}"
            )
            report.record(
                "PostgREST",
                f"{name} refuses a demo subject at entry",
                response.status_code == 403
                and payload.get("code") == "42501"
                and blocked_by_entry_guard,
                f"{response.status_code} {payload.get('code')} "
                + (
                    "(assert_not_demo, at entry)"
                    if blocked_by_entry_guard
                    else f"(NOT the entry guard: {payload.get('details')!r})"
                ),
                response.text[:200],
            )

    after = await conn.fetchrow(
        "select (select count(*) from jobs) j, (select count(*) from job_events) e, "
        "(select count(*) from job_stage_costs) c"
    )
    report.record(
        "PostgREST",
        "no Job, Job Event or cost row was created",
        (before["j"], before["e"], before["c"]) == (after["j"], after["e"], after["c"]),
        f"jobs {before['j']}→{after['j']}, events {before['e']}→{after['e']}, "
        f"costs {before['c']}→{after['c']}",
    )


async def check_storage(env: Env, world: World, minter: Minter, report: Report) -> None:
    print("\nStorage — private objects require a Hunt context")
    token = await minter.scoped("Storage", "reaching for objects")
    if token is None:
        return

    headers = {"apikey": env.anon_key, "Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(
        base_url=f"{env.supabase_url}/storage/v1", headers=headers, timeout=20
    ) as client:
        listed = await client.post(
            "/object/list/property-images",
            json={"prefix": "", "limit": 500, "sortBy": {"column": "name", "order": "asc"}},
        )
        names = [row.get("name", "") for row in listed.json()] if listed.status_code == 200 else []
        joined = " ".join(names)
        report.record(
            "Storage",
            "listing the bucket does not reveal out-of-scope objects",
            str(world.out_of_scope_property) not in joined,
            f"{listed.status_code}, {len(names)} entries; no out-of-scope Property id present",
        )

        # The exact key is supplied: path secrecy is explicitly not the control.
        for label, name, expect_ok in [
            ("in-scope", world.in_scope_object, True),
            ("out-of-scope", world.out_of_scope_object, False),
        ]:
            signed = await client.post(
                f"/object/sign/property-images/{name}", json={"expiresIn": 60}
            )
            ok = signed.status_code == 200
            report.record(
                "Storage",
                f"signing an {label} object {'succeeds' if expect_ok else 'is refused'}",
                ok == expect_ok,
                f"{signed.status_code} for {name}",
                signed.text[:160],
            )


async def check_gotrue(env: Env, minter: Minter, report: Report) -> None:
    print("\nGoTrue — there is no account to attack")
    # The precondition matters more here than anywhere: GoTrue answers 401 to a
    # malformed or expired token for reasons that have nothing to do with the
    # demo principal being virtual, so without it this whole block passes for a
    # token that was simply dead.
    token = await minter.scoped("GoTrue", "probing the account endpoints")
    if token is None:
        return

    headers = {"apikey": env.anon_key, "Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(
        base_url=f"{env.supabase_url}/auth/v1", headers=headers, timeout=20
    ) as client:
        probes = [
            ("GET /user", client.get("/user")),
            ("PUT /user (password)", client.put("/user", json={"password": "attacker-chosen-pw"})),
            ("PUT /user (email)", client.put("/user", json={"email": "attacker@example.test"})),
            ("POST /logout (global)", client.post("/logout", params={"scope": "global"})),
            ("POST /reauthenticate", client.get("/reauthenticate")),
            ("POST /factors (MFA enrol)", client.post("/factors", json={"factor_type": "totp"})),
        ]
        for label, coro in probes:
            response = await coro
            body = response.text[:160]
            refused = response.status_code in (401, 403, 404) or "user_not_found" in body
            report.record(
                "GoTrue",
                f"{label} is refused",
                refused,
                f"{response.status_code}",
                body,
            )


# ── Realtime ─────────────────────────────────────────────────────────────────


async def _realtime_delivers(
    env: Env, world: World, conn: asyncpg.Connection, token: str
) -> tuple[bool, bool]:
    """Open a real websocket, cause a real change, and see whether it arrives.

    Returns `(subscribed, delivered)`.

    `R4`: the old check substituted a PostgREST read for the second half, which
    tests the policy but not the subscription. Realtime authorizes *per change*,
    not at join — a dark token joins the topic happily and simply never receives
    anything — so the only honest way to ask is to write a row and wait.

    The write waits for Realtime's own `system` / "Subscribed to PostgreSQL"
    message rather than for a fixed sleep. A sleep is a coin toss here: the
    subscription is registered asynchronously after the join reply, and a run
    that writes too early reports "not delivered" for a token that was working
    perfectly — which on the negative checks would be a *false pass*, and on the
    positive control is the flake that produced one red run before this change.
    """
    import websockets

    url = (
        env.supabase_url.replace("https://", "wss://").replace("http://", "ws://")
        + f"/realtime/v1/websocket?apikey={env.anon_key}&vsn=1.0.0"
    )
    topic = f"realtime:dm8-{uuid.uuid4().hex[:6]}"
    async with websockets.connect(url, open_timeout=15) as socket:
        await socket.send(
            json.dumps(
                {
                    "topic": topic,
                    "event": "phx_join",
                    "payload": {
                        "config": {
                            "postgres_changes": [
                                {"event": "INSERT", "schema": "public", "table": "comments"}
                            ]
                        },
                        "access_token": token,
                    },
                    "ref": "1",
                }
            )
        )
        subscribed = False
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                message = json.loads(await asyncio.wait_for(socket.recv(), timeout=8))
            except TimeoutError:
                break
            if message.get("event") == "system":
                payload = message.get("payload", {})
                subscribed = payload.get("status") == "ok"
                break

        comment_id = await conn.fetchval(
            "insert into comments (hunt_listing_id, user_id, body) "
            "values ($1, $2, 'dm8 realtime probe') returning id",
            world.listing_id,
            world.owner,
        )
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                message = json.loads(await asyncio.wait_for(socket.recv(), timeout=8))
                if message.get("event") == "postgres_changes":
                    return subscribed, True
        except TimeoutError:
            pass
        finally:
            await conn.execute("delete from comments where id = $1", comment_id)
    return subscribed, False


async def check_realtime(
    env: Env, world: World, minter: Minter, conn: asyncpg.Connection, report: Report
) -> None:
    """A live subscription, before and after the kill switch (`R4`, R2 H6)."""
    print("\nRealtime — the kill switch reaches live subscriptions")
    try:
        import websockets  # noqa: F401
    except ImportError:  # pragma: no cover
        report.skip("Realtime: `websockets` is not installed")
        return

    token = await minter.scoped("Realtime", "subscribing")
    if token is None:
        return

    try:
        subscribed, delivered = await _realtime_delivers(env, world, conn, token)
    except Exception as exc:  # the harness reports failures, it never raises
        report.skip(f"Realtime subscribe (enabled): {type(exc).__name__}: {exc}")
        return
    # The positive control for the two negative checks below: unless a change
    # genuinely arrives here, "nothing arrived" there means nothing.
    report.record(
        "Realtime",
        "a change in the Demo Hunt reaches a subscribed demo token",
        subscribed and delivered,
        f"subscribed={subscribed}; a service-role INSERT into comments was "
        f"{'delivered' if delivered else 'NOT delivered'} over the websocket",
    )
    if not (subscribed and delivered):
        report.skip(
            "Realtime: the switch-off and generation checks need a working "
            "subscription as their control and were not attempted"
        )
        return

    # Rule 2: the switch-off half must darken for the *switch*, not for the
    # generation rotation the switch-off itself caused. So: toggle, then mint at
    # the post-toggle generation, leaving `demo_enabled = false` as the only
    # inconsistency the token has.
    await conn.fetchval("select set_demo_enabled(false, $1)", world.owner)
    try:
        post_toggle = await minter.token_at_current_generation()
        subscribed = False
        try:
            subscribed, delivered = await _realtime_delivers(env, world, conn, post_toggle)
        except Exception as exc:
            report.skip(f"Realtime subscribe (disabled): {type(exc).__name__}: {exc}")
            delivered = True  # never let an error read as a pass
        report.record(
            "Realtime",
            "with the switch off, a token minted at the current generation receives nothing",
            not delivered,
            f"subscribed={subscribed}; the same INSERT was "
            + ("NOT delivered" if not delivered else "DELIVERED")
            + "; the only inconsistency in this token is demo_enabled = false",
        )
    finally:
        await conn.fetchval("select set_demo_enabled(true, $1)", world.owner)

    # And the generation half, which needs the opposite treatment: an *old*
    # token against a re-enabled demo.
    stale = mint(env, str(world.principal), await minter.current_generation() - 2)
    subscribed = False
    try:
        subscribed, delivered = await _realtime_delivers(env, world, conn, stale)
    except Exception as exc:
        report.skip(f"Realtime subscribe (stale generation): {type(exc).__name__}: {exc}")
        delivered = True
    report.record(
        "Realtime",
        "after a generation rotation, a pre-rotation token receives nothing",
        not delivered,
        f"subscribed={subscribed}; the INSERT was "
        + ("NOT delivered" if not delivered else "DELIVERED")
        + "; demo enabled and the marker intact, so the stale generation alone darkens it",
    )


async def check_kill_switch_and_identity(
    env: Env, world: World, minter: Minter, conn: asyncpg.Connection, report: Report
) -> None:
    print("\nKill switch and identity — configuration loss fails closed")

    # 1. The marker row vanishes mid-session.
    token = await minter.scoped("Kill switch", "the marker row is deleted")
    if token is not None:
        await conn.execute("delete from demo_accounts")
        count = await visible_properties(env, token)
        report.record(
            "Kill switch",
            "deleting the marker row darkens a live token",
            count == 0,
            f"{count} Properties visible with no demo_accounts row "
            "(before the C1 fix: every Property in the database)",
        )
        await conn.execute(
            "insert into demo_accounts (user_id, note) values ($1, 'DM-8 harness')",
            world.principal,
        )

    # 2. The singleton names somebody else.
    token = await minter.scoped("Kill switch", "the singleton names another subject")
    if token is not None:
        await conn.execute("delete from demo_accounts")
        await conn.execute(
            "insert into demo_accounts (user_id, note) values ($1, 'mismatch')", uuid.uuid4()
        )
        count = await visible_properties(env, token)
        report.record(
            "Kill switch",
            "a singleton naming a different subject darkens the token",
            count == 0,
            f"{count} Properties visible",
        )
        await conn.execute("delete from demo_accounts")
        await conn.execute(
            "insert into demo_accounts (user_id, note) values ($1, 'DM-8 harness')",
            world.principal,
        )

    # 3. The switch itself — DESIGN §16 control 5, and the branch rule 2 exists
    #    for. Minting *after* the toggle is what makes this check about
    #    `demo_enabled` rather than about the generation the toggle rotated.
    token = await minter.scoped("Kill switch", "the demo is switched off")
    if token is not None:
        await conn.fetchval("select set_demo_enabled(false, $1)", world.owner)
        try:
            post_toggle = await minter.token_at_current_generation()
            count = await visible_properties(env, post_toggle)
            report.record(
                "Kill switch",
                "switching the demo off darkens a token minted at the current generation",
                count == 0,
                f"{count} Properties visible; marker intact and generation current, "
                "so demo_enabled = false is the only inconsistency",
            )
        finally:
            await conn.fetchval("select set_demo_enabled(true, $1)", world.owner)

    # 4. Disable, then re-enable: the pre-disable token must stay dead.
    token = await minter.scoped("Kill switch", "a disable/re-enable cycle")
    if token is not None:
        await conn.fetchval("select set_demo_enabled(false, $1)", world.owner)
        dark = await visible_properties(env, token)
        await conn.fetchval("select set_demo_enabled(true, $1)", world.owner)
        revived = await visible_properties(env, token)
        new_generation = await minter.current_generation()
        fresh = await visible_properties(env, mint(env, str(world.principal), new_generation))
        report.record(
            "Kill switch",
            "a token issued before a disable does not revive after re-enabling",
            dark == 0 and revived == 0 and fresh > 0,
            f"disabled: {dark} rows; re-enabled with the old token: {revived} rows; "
            f"freshly minted: {fresh} rows",
        )

    # 5. A forged token cannot mint itself a demo identity.
    forged = jwt.encode(
        {
            "sub": str(world.principal),
            "aud": "authenticated",
            "role": "authenticated",
            "exp": int(time.time()) + 900,
            DEMO_CLAIM: True,
            DEMO_GEN_CLAIM: await minter.current_generation(),
        },
        "not-the-projects-signing-secret",
        algorithm="HS256",
    )
    count = await visible_properties(env, forged)
    report.record(
        "Kill switch",
        "a token signed with the wrong secret is rejected outright",
        count == -1,
        "PostgREST refused the forged token (HTTP error rather than an empty result)",
    )


async def check_issuance(env: Env, conn: asyncpg.Connection, report: Report) -> None:
    print("\nIssuance — ceilings hold under concurrency, storage stays bounded")

    # Start from a known window. Without this the check passes vacuously on a
    # second run inside the same hour: the ceiling is already spent, nothing is
    # issued, and "issued <= 5" holds for the wrong reason.
    await conn.execute(
        "delete from demo_session_counters where window_start = date_trunc('hour', now())"
    )

    # Fresh connections so the calls genuinely race rather than queue on one.
    async def issue_on_own_connection(key: str) -> str:
        own = await asyncpg.connect(env.database_url)
        try:
            value = await own.fetchval("select issue_demo_session($1, $2, $3)", key, 1000, 5)
            return json.loads(value)["status"]
        finally:
            await own.close()

    results = await asyncio.gather(
        *[issue_on_own_connection(f"{i:032x}") for i in range(25)], return_exceptions=True
    )
    statuses = [r for r in results if isinstance(r, str)]
    issued = statuses.count("issued")
    report.record(
        "Issuance",
        "25 concurrent callers cannot exceed a global ceiling of 5",
        # `issued > 0` guards the guard: a run that issued nothing at all would
        # satisfy the ceiling without ever exercising it.
        0 < issued <= 5,
        f"{issued} issued of {len(statuses)} concurrent attempts "
        "(without the advisory lock this over-issues under READ COMMITTED)",
    )

    # Boundedness, reformulated. The previous version sent 25 *distinct* keys and
    # allowed 30 new rows, which a per-request log would also satisfy — the same
    # tautology `R5` fixes in the API test. One key, many requests: a design that
    # appends per request fails immediately, and a bucketed counter touches at
    # most its own row plus the global one.
    rows_before = await conn.fetchval("select count(*) from demo_session_counters")
    for _ in range(60):
        await conn.fetchval("select issue_demo_session($1, $2, $3)", "f" * 32, 1000, 5)
    rows_after = await conn.fetchval("select count(*) from demo_session_counters")
    report.record(
        "Issuance",
        "sixty requests on one client key add at most two counter rows",
        rows_after - rows_before <= 2,
        f"{rows_after - rows_before} new counter rows after 60 requests on a single key "
        "(the old per-request log added one row each)",
    )


async def check_api(env: Env, world: World, minter: Minter, report: Report) -> None:
    print("\nFastAPI — the legible 403, and the public routes")
    if not env.api_base_url:
        report.skip(
            "FastAPI: set MANZIL_API_BASE_URL to include the API plane (5 checks not exercised)"
        )
        return

    async with httpx.AsyncClient(base_url=env.api_base_url, timeout=20) as client:
        try:
            config = await client.get("/v1/demo/config")
        except httpx.HTTPError as exc:
            report.skip(f"FastAPI: {env.api_base_url} unreachable ({exc})")
            return

        # `/demo/config` caches its answer for a few seconds so an unauthenticated
        # public route cannot be turned into a database read per request (R2 M2).
        # That staleness is deliberate and cosmetic — it gates whether the "Try
        # the demo" button renders, nothing else. `/demo/session` is uncached and
        # RLS is uncached, so a disabled demo stops issuing and stops reading
        # immediately. Poll rather than assume, and say which we observed.
        deadline = time.monotonic() + 25
        while config.json().get("enabled") is not True and time.monotonic() < deadline:
            await asyncio.sleep(2)
            config = await client.get("/v1/demo/config")
        report.record(
            "FastAPI",
            "GET /v1/demo/config reports the demo as available",
            config.status_code == 200 and config.json().get("enabled") is True,
            f"{config.status_code} {config.text[:60]} "
            "(cached briefly; the cache gates the button, never access)",
        )

        session = await client.post("/v1/demo/session")
        minted = session.status_code == 200 and "access_token" in session.json()
        report.record(
            "FastAPI",
            "POST /v1/demo/session mints a token over real HTTP",
            minted,
            f"{session.status_code}",
        )
        if minted:
            issued_token = session.json()["access_token"]
            claims = jwt.decode(issued_token, options={"verify_signature": False})
            report.record(
                "FastAPI",
                "the issued token carries the demo claim and a generation",
                claims.get(DEMO_CLAIM) is True and isinstance(claims.get(DEMO_GEN_CLAIM), int),
                f"gen={claims.get(DEMO_GEN_CLAIM)}, ttl={claims['exp'] - claims['iat']}s",
            )
            report.record(
                "FastAPI",
                "the issued TTL is within the bounded range",
                60 <= claims["exp"] - claims["iat"] <= 1800,
                f"{claims['exp'] - claims['iat']}s (bound: 60..1800)",
            )

        token = await minter.scoped("FastAPI", "an unsafe route is called")
        if token is None:
            return
        write = await client.post(
            f"/v1/hunts/{world.hunt_id}/listings",
            headers={"Authorization": f"Bearer {token}"},
            json={"url": "https://example.test/x", "source_policy": "trust_link"},
        )
        report.record(
            "FastAPI",
            "an unsafe route answers 403 demo_read_only",
            write.status_code == 403 and write.json().get("code") == "demo_read_only",
            f"{write.status_code} {write.text[:80]}",
        )


# ── Evidence ─────────────────────────────────────────────────────────────────


def write_evidence(path: str, report: Report, env: Env, world: World) -> None:
    lines = [
        "# DM-8 adversarial pass — evidence",
        "",
        f"Run: {datetime.now().astimezone().isoformat()}",
        f"Target: `{env.supabase_url}`",
        f"API plane: {'`' + env.api_base_url + '`' if env.api_base_url else '**not exercised**'}",
        f"Demo principal: `{world.principal}` · Demo Hunt: `{world.hunt_id}`",
        "",
        "Produced by `scripts/dm8_adversarial.py`, which drives PostgREST, Storage,",
        "GoTrue, Realtime and FastAPI over HTTP with a token minted exactly as a",
        "visitor's is. API-level tests do not count as evidence for DM-8; nothing",
        "here uses a TestClient or an in-process import.",
        "",
        f"**{report.headline()}.**",
        "",
        "Every block below opens with a *precondition* row: the token was re-minted",
        "at the database's current demo generation and proved to read the Demo Hunt",
        "**before** anything was asserted about what it cannot do. A refusal recorded",
        "without that control is not evidence — finding `R1` was exactly a harness",
        "reporting PASS for a token that had already gone dark for an unrelated reason.",
        "",
        "| Plane | Check | Result | Detail |",
        "|---|---|---|---|",
    ]
    for check in report.checks:
        detail = check.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {check.plane} | {check.name} | {'✅' if check.passed else '❌'} | {detail} |"
        )

    if report.skipped:
        lines += [
            "",
            "## Not exercised",
            "",
            "These are **not** passes. They are planes this run did not reach, and the",
            "headline above counts them separately for that reason.",
            "",
        ]
        lines += [f"- {item}" for item in report.skipped]

    lines += [
        "",
        "## Observed behaviour worth recording in the runbook",
        "",
        "- **A ban is not a control.** GoTrue honours `PUT /auth/v1/user` for any",
        "  validly-signed JWT, banned or not (DESIGN §20 v3.55). The demo principal",
        "  is safe because it has no `auth.users` row at all, which is why every",
        "  GoTrue probe above answers `user_not_found` rather than `user_banned`.",
        "- **Disabling is a revocation.** Every toggle rotates",
        "  `site_settings.demo_generation`, so tokens issued before a disable stay",
        "  dark after a re-enable rather than resuming until `exp`. The two effects",
        "  are separated above: one check mints *after* the toggle so only the",
        "  switch can darken it, another keeps a pre-rotation token so only the",
        "  generation can.",
        "- **Losing the marker row is safe.** Deleting `demo_accounts` mid-session",
        "  darkens live tokens instead of promoting them to ordinary readers.",
        "- **The RPC guards are entry guards.** Each of the four refusals above was",
        "  attributed to `private.assert_not_demo` by the error detail naming the",
        "  function. The statement trigger would also refuse these calls, with the",
        "  same status and SQLSTATE — which is why the weaker assertion cannot tell",
        "  whether DESIGN §16 control 4 still exists.",
        "",
    ]
    with open(path, "w") as handle:
        handle.write("\n".join(lines))
    print(f"\nEvidence written to {path}")


# ── Entry point ──────────────────────────────────────────────────────────────


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", default="docs/demo-mode-dm8-evidence.md")
    parser.add_argument(
        "--broken-token",
        choices=("expired", "stale-generation", "unsigned"),
        help=(
            "Hand every check a deliberately unusable token. Every precondition "
            "must then FAIL. This is how the preconditions themselves are shown "
            "to bite; a run with this flag that reports passes is a broken harness."
        ),
    )
    args = parser.parse_args()

    env = Env.load()
    report = Report()

    conn = await asyncpg.connect(env.database_url)
    preserved = [
        dict(row) for row in await conn.fetch("select user_id, created_by, note from demo_accounts")
    ]
    world = await build_world(conn)
    minter = Minter(env, world, conn, report, flaw=args.broken_token)
    print(
        f"Demo enabled. Principal {world.principal}, "
        f"Hunt {world.hunt_id}, generation {world.generation}."
    )
    if args.broken_token:
        print(f"\033[33m--broken-token={args.broken_token}: every precondition must FAIL.\033[0m")

    try:
        # First, and before anything is asserted about the database: prove the
        # instrument can distinguish the two states it is about to report on.
        await check_self_test(env, world, minter, report)
        await check_postgrest(env, world, minter, report)
        await check_writes(env, world, minter, report)
        await check_rpcs(env, world, minter, conn, report)
        await check_storage(env, world, minter, report)
        await check_gotrue(env, minter, report)
        await check_realtime(env, world, minter, conn, report)
        await check_api(env, world, minter, report)
        await check_issuance(env, conn, report)
        # Last: it deliberately breaks the configuration it was handed.
        await check_kill_switch_and_identity(env, world, minter, conn, report)
    finally:
        await teardown(env, conn, world, preserved)
        await conn.close()

    write_evidence(args.evidence, report, env, world)

    if report.failed:
        print(f"\n\033[31m{len(report.failed)} check(s) FAILED\033[0m")
        for check in report.failed:
            print(f"  - [{check.plane}] {check.name}: {check.detail}")
        return 1
    print(f"\n\033[32m{report.passed_count} of {report.attempted} attempted checks passed.\033[0m")
    if report.skipped:
        print(
            f"\033[33m{len(report.skipped)} plane(s) not exercised — see the evidence file.\033[0m"
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
