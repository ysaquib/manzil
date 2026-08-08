"""Cleaned Source text must not be readable through `jobs.payload`.

DESIGN §16 control 2 claimed cleaned Source text was service-role-only "for
every member, not only for demo". DM-1 made that true of
`property_sources.cleaned_text` and nobody enumerated the second home: the
worker dumps the whole `RunState` into `jobs.payload`, `RunState.sources[]`
carries the cleaned body of every fetched page, and `jobs` is member-selectable.

These run against the database rather than the API wherever they can, for the
same reason `test_demo_guard.py` does: the threat model is a JWT driven straight
at PostgREST with FastAPI bypassed, so an API-level assertion proves nothing
about the claim. The API-level tests here exist to prove the *opposite*
direction -- that withholding the column did not break a working endpoint, and
in particular that answering a checkpoint no longer writes the redacted
projection back over the stored bodies.

`SENTINEL` is what every read assertion looks for. Bounding "characters of
`cleaned_text`" would pass against a transform that moved the body to another
key; searching every readable value for a marker string does not.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from httpx import AsyncClient
from local_supabase import LOCAL_ANON_KEY, LOCAL_SUPABASE_URL
from manzil_shared.models import CheckpointKind, CheckpointPrompt, JobState

pytestmark = pytest.mark.asyncio

# Long enough that a 2 KB truncation would still contain it, distinctive enough
# that it cannot occur by accident anywhere else in the row.
SENTINEL = "MANZIL-CLEANED-PAGE-BODY-SENTINEL"
BODY = f"{SENTINEL} " + ("rent two bedroom apartment " * 120)


def _run_state(job_id: str, *, checkpoint: dict | None = None) -> dict:
    """A RunState shaped like the worker's, carrying a page body."""
    state: dict = {
        "job_id": job_id,
        "job_type": "ingest",
        "url": "https://example.test/listing",
        "status": JobState.WAITING_USER.value if checkpoint else "done",
        "cursor": 4,
        "checkpoint": checkpoint,
        # A legitimate null inside run_state: it must survive the projection.
        # `jsonb_strip_nulls` would take it, which is why the transform does not
        # use it.
        "pending_dispute": None,
        "property_id": None,
        # A real `SourceClaim`, not an approximation: the resume assertion below
        # validates this whole payload back through `RunState`, which is the only
        # way to prove the worker gets its page text back rather than the `""`
        # that `SourceState.cleaned_text` silently defaults to.
        "source_claims": [
            {
                "criterion_key": "base_rent",
                "value": 2450,
                "confidence": "high",
                "evidence_quote": "$2,450 monthly rent",
                "source_id": "https://example.test/listing",
                "model": "google/gemini-3-flash-preview",
                "prompt_version": 1,
            }
        ],
        "sources": [
            {
                "url": "https://example.test/listing",
                "site_domain": "example.test",
                "cleaned_text": BODY,
                "cleaned_text_hash": "abc123",
            },
            {
                "url": "https://example.test/official",
                "site_domain": "example.test",
                "cleaned_text": BODY,
                "cleaned_text_hash": "def456",
            },
        ],
    }
    return state


async def _readable_columns(conn: asyncpg.Connection, table: str) -> list[str]:
    rows = await conn.fetch(
        """
        select column_name
          from information_schema.columns
         where table_schema = 'public' and table_name = $1
           and has_column_privilege('authenticated', 'public.' || $1,
                                    column_name, 'SELECT')
         order by ordinal_position
        """,
        table,
    )
    return [r["column_name"] for r in rows]


async def _read_everything_as(
    conn: asyncpg.Connection, subject: str, table: str, *, where: str = "true"
) -> str:
    """Every value of `table` the given subject can select, concatenated.

    Deliberately not "the characters of `cleaned_text`": a transform that renamed
    the key would satisfy that and leak just as much. The columns come from the
    catalog, so a column added next month is covered without anyone remembering
    this file.
    """
    columns = await _readable_columns(conn, table)
    projection = ", ".join(f"coalesce({c}::text, '')" for c in columns)
    inner = conn.transaction()
    await inner.start()
    try:
        await conn.execute("set local role authenticated")
        await conn.execute(
            "select set_config('request.jwt.claims', $1, true)",
            json.dumps({"sub": subject, "role": "authenticated"}),
        )
        rows = await conn.fetch(
            f"select concat_ws(' ', {projection}) as everything from {table} where {where}"
        )
        return " ".join(r["everything"] for r in rows)
    finally:
        await inner.rollback()


@pytest_asyncio.fixture
async def bodies_hunt(db_pool, seeded_users):  # type: ignore[no-untyped-def]
    """A Hunt whose Jobs carry page bodies in both of `payload`'s two homes.

    `owner` submitted the Listing; `member` is an ordinary member of the Hunt
    who did not, which is the weakest read position that still passes
    `jobs_member_select`.
    """
    owner = seeded_users["owner"]
    member = seeded_users["member"]
    hunt_id, listing_id, property_id = uuid4(), uuid4(), uuid4()
    waiting_job_id, done_job_id = uuid4(), uuid4()

    prompt = CheckpointPrompt(
        kind=CheckpointKind.CONFIRM_VALUE,
        question="Confirm the rent?",
        options=["yes", "no"],
        default="yes",
        context_ref="base_rent",
    ).model_dump(mode="json")

    await db_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Bodies', $2)", hunt_id, owner.user_id
    )
    await db_pool.execute(
        "insert into hunt_members (hunt_id, user_id, role) values ($1, $2, 'member')",
        hunt_id,
        member.user_id,
    )
    await db_pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'P', '1 Test St')",
        property_id,
    )
    await db_pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1,$2,$3,$4)",
        listing_id,
        hunt_id,
        property_id,
        owner.user_id,
    )
    # Home 1: run_state.sources[].cleaned_text, on a Job parked at a checkpoint.
    await db_pool.execute(
        """
        insert into jobs (id, hunt_id, hunt_listing_id, type, state, current_stage, payload)
        values ($1, $2, $3, 'ingest', 'waiting_user', 'VERIFY', $4::jsonb)
        """,
        waiting_job_id,
        hunt_id,
        listing_id,
        json.dumps(
            {
                "url": "https://example.test/listing",
                "run_state": _run_state(str(waiting_job_id), checkpoint=prompt),
            }
        ),
    )
    # Home 2: auto_resolved_checkpoint.snapshot -- a whole RunState, so also
    # page bodies -- on a terminal Job, which is what makes it correctable.
    snapshot = _run_state(str(done_job_id), checkpoint=prompt)
    await db_pool.execute(
        """
        insert into jobs
            (id, hunt_id, hunt_listing_id, type, state, current_stage, payload, finished_at)
        values ($1, $2, $3, 'ingest', 'done', 'VERIFY', $4::jsonb, now())
        """,
        done_job_id,
        hunt_id,
        listing_id,
        json.dumps(
            {
                "url": "https://example.test/listing",
                "run_state": {**snapshot, "status": "done", "checkpoint": None},
                "auto_resolved_checkpoint": {
                    "prompt": prompt,
                    "answer": {"choice": "yes", "context_ref": "base_rent"},
                    "resolved_at": datetime.now(UTC).isoformat(),
                    "snapshot": snapshot,
                },
            }
        ),
    )
    await db_pool.execute(
        "insert into job_events (job_id, stage, event) "
        "values ($1, 'VERIFY', 'checkpoint_auto_resolved')",
        done_job_id,
    )
    yield {
        "hunt_id": hunt_id,
        "listing_id": listing_id,
        "property_id": property_id,
        "waiting_job_id": waiting_job_id,
        "done_job_id": done_job_id,
        "owner": owner,
        "member": member,
    }
    await db_pool.execute("delete from hunts where id = $1", hunt_id)
    await db_pool.execute("delete from properties where id = $1", property_id)


# ── The finding itself ───────────────────────────────────────────────────────


async def test_member_jwt_cannot_read_page_text_through_jobs(db_pool, bodies_hunt) -> None:
    async with db_pool.acquire() as conn:
        everything = await _read_everything_as(
            conn,
            bodies_hunt["member"].user_id,
            "jobs",
            where=f"hunt_id = '{bodies_hunt['hunt_id']}'",
        )
    assert SENTINEL not in everything, (
        "An ordinary Hunt member can read cleaned Source text out of `jobs`. "
        "DESIGN §16 control 2 says it is service-role-only for every member."
    )
    # The positive control: the read worked at all, so a green result is the
    # projection doing its job rather than the rows being invisible.
    assert "https://example.test/listing" in everything


async def test_jobs_payload_is_not_selectable_by_authenticated(db_pool) -> None:
    readable = await db_pool.fetchval(
        "select has_column_privilege('authenticated', 'public.jobs', 'payload', 'SELECT')"
    )
    assert readable is False
    anon_readable = await db_pool.fetchval(
        "select has_column_privilege('anon', 'public.jobs', 'payload', 'SELECT')"
    )
    assert anon_readable is False


async def test_every_other_jobs_column_stays_readable(db_pool) -> None:
    """The inverse of the revoke. Dropping the table-level grant and forgetting
    a column would break the Tasks UI rather than leak anything, which is the
    right direction of failure but still a bug."""
    hidden = await db_pool.fetch(
        """
        select column_name from information_schema.columns
         where table_schema = 'public' and table_name = 'jobs'
           and column_name <> 'payload'
           and not has_column_privilege('authenticated', 'public.jobs',
                                        column_name, 'SELECT')
        """
    )
    assert [r["column_name"] for r in hidden] == []


async def test_demo_principal_cannot_read_page_text_through_jobs(db_pool, bodies_hunt) -> None:
    """The same read with the demo turned on and the Hunt made the Demo Hunt.

    Everything happens inside a transaction that is rolled back, so the local
    database keeps its real (disabled) demo configuration.
    """
    demo_subject = str(uuid4())
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute("set local statement_timeout = '15s'")
            await conn.execute("delete from demo_accounts")
            await conn.execute(
                "insert into demo_accounts (user_id, note) values ($1, 'projection test')",
                UUID(demo_subject),
            )
            await conn.execute(
                "update site_settings set demo_enabled = true, demo_hunt_id = $1",
                bodies_hunt["hunt_id"],
            )
            everything = await _read_everything_as(
                conn, demo_subject, "jobs", where=f"hunt_id = '{bodies_hunt['hunt_id']}'"
            )
        finally:
            await tr.rollback()
    assert SENTINEL not in everything
    assert "https://example.test/listing" in everything  # positive control


async def test_total_member_readable_page_text_across_every_store(db_pool, bodies_hunt) -> None:
    """One bound over both of the exposed homes at once.

    `job_events.detail` is included because `_summarize` used to store a 2 KB
    raw page prefix there for every `fetch_page` tool call -- the same class of
    data, in a table this fix does not touch.
    """
    job_ids = (bodies_hunt["waiting_job_id"], bodies_hunt["done_job_id"])
    await db_pool.execute(
        "insert into job_events (job_id, stage, event, detail) "
        "values ($1, 'DISCOVER', 'tool_called', $2::jsonb)",
        job_ids[0],
        json.dumps({"tool": "fetch_page", "input": {"url": "https://example.test/listing"}}),
    )
    async with db_pool.acquire() as conn:
        jobs_text = await _read_everything_as(
            conn, bodies_hunt["member"].user_id, "jobs",
            where=f"hunt_id = '{bodies_hunt['hunt_id']}'",
        )
        events_text = await _read_everything_as(
            conn, bodies_hunt["member"].user_id, "job_events",
            where=f"job_id in ('{job_ids[0]}', '{job_ids[1]}')",
        )
    assert SENTINEL not in jobs_text + events_text


# ── The projection is lossless ───────────────────────────────────────────────


async def test_projection_preserves_every_field_the_api_reads(db_pool, bodies_hunt) -> None:
    row = await db_pool.fetchrow(
        "select payload, payload_public from jobs where id = $1", bodies_hunt["waiting_job_id"]
    )
    original = json.loads(row["payload"])
    public = json.loads(row["payload_public"])

    # Every key `jobs/service.py` reads, at the path it reads it from.
    assert public["url"] == original["url"]
    for key in ("cursor", "checkpoint", "source_claims", "pending_dispute", "url", "status"):
        assert public["run_state"][key] == original["run_state"][key], key
    # Array length and element order are preserved; only the body key is gone.
    assert len(public["run_state"]["sources"]) == len(original["run_state"]["sources"]) == 2
    assert [s["url"] for s in public["run_state"]["sources"]] == [
        s["url"] for s in original["run_state"]["sources"]
    ]
    assert [s["cleaned_text_hash"] for s in public["run_state"]["sources"]] == [
        "abc123",
        "def456",
    ]
    assert all("cleaned_text" not in s for s in public["run_state"]["sources"])


async def test_projection_covers_the_auto_resolved_snapshot(db_pool, bodies_hunt) -> None:
    public = json.loads(
        await db_pool.fetchval(
            "select payload_public from jobs where id = $1", bodies_hunt["done_job_id"]
        )
    )
    auto = public["auto_resolved_checkpoint"]
    assert SENTINEL not in json.dumps(public)
    # The prompt, the answer and the claim evidence the drawer renders survive.
    assert auto["prompt"]["question"] == "Confirm the rent?"
    assert auto["answer"] == {"choice": "yes", "context_ref": "base_rent"}
    assert auto["snapshot"]["source_claims"][0]["evidence_quote"] == "$2,450 monthly rent"
    assert len(auto["snapshot"]["sources"]) == 2


async def test_projection_keeps_legitimate_nulls(db_pool, bodies_hunt) -> None:
    """`jsonb_strip_nulls` would have been the obvious implementation and would
    have silently changed what the API reads."""
    public = json.loads(
        await db_pool.fetchval(
            "select payload_public from jobs where id = $1", bodies_hunt["waiting_job_id"]
        )
    )
    assert "pending_dispute" in public["run_state"]
    assert public["run_state"]["pending_dispute"] is None
    assert "property_id" in public["run_state"]
    assert public["run_state"]["property_id"] is None


TOTALITY_SHAPES = [
    pytest.param(None, id="sql-null"),
    pytest.param('"a string"', id="jsonb-string"),
    pytest.param("null", id="jsonb-null"),
    pytest.param("42", id="number"),
    pytest.param("true", id="boolean"),
    pytest.param("[]", id="empty-array"),
    pytest.param("{}", id="empty-object"),
    pytest.param('{"run_state": "x"}', id="run-state-scalar"),
    pytest.param('{"run_state": [1, 2, 3]}', id="run-state-array"),
    pytest.param(
        '{"run_state": {"sources": {"a": {"cleaned_text": "MANZIL-CLEANED-PAGE-BODY-SENTINEL"}}}}',
        id="sources-object-not-array",
    ),
    pytest.param(
        '{"auto_resolved_checkpoint": {"snapshot": {"auto_resolved_checkpoint":'
        ' {"snapshot": {"sources": [{"cleaned_text":'
        ' "MANZIL-CLEANED-PAGE-BODY-SENTINEL"}]}}}}}',
        id="snapshot-in-snapshot",
    ),
    pytest.param(
        '{"cleaned_text": "MANZIL-CLEANED-PAGE-BODY-SENTINEL", "keep": null, "n": [null, 1]}',
        id="top-level-body-and-legit-nulls",
    ),
]


@pytest.mark.parametrize("shape", TOTALITY_SHAPES)
async def test_transform_is_total(db_pool, shape) -> None:
    """The transform must never raise, on any jsonb whatsoever.

    A generated column's expression runs against every existing row when the
    column is added, so an expression that raises on one odd legacy payload
    aborts the migration and makes that row unwritable -- an availability
    incident, not a caller's problem. Table-driven over the shapes the worker
    never writes but another writer could.
    """
    out = await db_pool.fetchval(
        "select private.strip_cleaned_text($1::jsonb, 0)", shape
    )
    if shape is None:
        assert out is None
        return
    assert SENTINEL not in out
    # Shape is otherwise preserved, including the legitimate nulls.
    if shape.startswith("{") and '"keep"' in shape:
        parsed = json.loads(out)
        assert "keep" in parsed and parsed["keep"] is None
        assert parsed["n"] == [None, 1]


async def test_transform_is_total_on_the_generated_column(db_pool, bodies_hunt) -> None:
    """Same shapes, but written through the column, which is where a raise would
    actually hurt."""
    hunt_id = bodies_hunt["hunt_id"]
    for param in TOTALITY_SHAPES:
        shape = param.values[0]
        if shape is None:
            continue  # `payload` is NOT NULL
        job_id = uuid4()
        await db_pool.execute(
            "insert into jobs (id, hunt_id, type, state, payload) "
            "values ($1, $2, 'rescore', 'queued', $3::jsonb)",
            job_id,
            hunt_id,
            shape,
        )
        public = await db_pool.fetchval("select payload_public from jobs where id = $1", job_id)
        assert SENTINEL not in (public or ""), param.id
        await db_pool.execute("delete from jobs where id = $1", job_id)


# ── The RPCs ─────────────────────────────────────────────────────────────────


async def _as_member(conn: asyncpg.Connection, subject: str) -> None:
    await conn.execute("set local role authenticated")
    await conn.execute(
        "select set_config('request.jwt.claims', $1, true)",
        json.dumps({"sub": subject, "role": "authenticated"}),
    )


async def test_correct_auto_resolved_checkpoint_returns_no_page_text(
    db_pool, bodies_hunt
) -> None:
    """`returns setof jobs` is a disclosure channel the column revoke does not
    close: column ACLs apply to table references, not to composite rows returned
    by a function, and PostgREST serialises every column of an RPC result."""
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _as_member(conn, bodies_hunt["owner"].user_id)
            rows = await conn.fetch(
                "select * from public.correct_auto_resolved_checkpoint($1, $2::jsonb)",
                bodies_hunt["done_job_id"],
                json.dumps({"choice": "no"}),
            )
            returned = " ".join(
                str(value) for row in rows for value in row.values() if value is not None
            )
        finally:
            await tr.rollback()
    assert rows, "the correction returned no Job"
    assert SENTINEL not in returned
    # Positive control: this really is the correction Job.
    assert str(bodies_hunt["done_job_id"]) not in [str(r["id"]) for r in rows]


async def test_answer_job_checkpoint_returns_no_page_text(db_pool, bodies_hunt) -> None:
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _as_member(conn, bodies_hunt["owner"].user_id)
            rows = await conn.fetch(
                "select * from public.answer_job_checkpoint($1, $2::jsonb, $3::jsonb)",
                bodies_hunt["waiting_job_id"],
                json.dumps({"choice": "yes"}),
                json.dumps({"answer": {"choice": "yes"}}),
            )
            returned = " ".join(
                str(value) for row in rows for value in row.values() if value is not None
            )
        finally:
            await tr.rollback()
    assert rows
    assert SENTINEL not in returned
    assert rows[0]["state"] == "queued"  # positive control


async def test_answer_job_checkpoint_merges_and_keeps_the_source_bodies(
    db_pool, bodies_hunt
) -> None:
    """The read-modify-write hazard the revoke creates, at the database level.

    With `payload` withheld the API can only read `payload_public`; an RPC that
    *replaces* the column with what the caller read would empty every Source
    body -- silently, because `extract.py:336` skips an emptied Source rather
    than erroring.
    """
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _as_member(conn, bodies_hunt["owner"].user_id)
            await conn.fetch(
                "select * from public.answer_job_checkpoint($1, $2::jsonb, $3::jsonb)",
                bodies_hunt["waiting_job_id"],
                json.dumps({"choice": "yes"}),
                json.dumps({}),
            )
            await conn.execute("reset role")
            stored = json.loads(
                await conn.fetchval(
                    "select payload from jobs where id = $1", bodies_hunt["waiting_job_id"]
                )
            )
        finally:
            await tr.rollback()
    assert stored["run_state"]["sources"][0]["cleaned_text"].startswith(SENTINEL)
    assert stored["run_state"]["status"] == "running"
    assert stored["run_state"]["checkpoint"] is None
    assert stored["checkpoint_answer"] == {"choice": "yes", "context_ref": "base_rent"}


async def test_answer_job_checkpoint_takes_no_caller_payload(db_pool, bodies_hunt) -> None:
    """The injection primitive from `.claude/plans/checkpoint-payload-injection.md`.

    A member could call this RPC directly with a RunState of their choosing and
    steer the run at another Property -- through `property_id`, and separately
    through `sources[0].url`, which `canonical_id` prefers. Both are gone
    because there is no longer a parameter to carry them.
    """
    victim_property = uuid4()
    hostile = {
        "url": "https://example.test/listing",
        "run_state": {
            "job_id": str(bodies_hunt["waiting_job_id"]),
            "job_type": "ingest",
            "status": "running",
            "cursor": 99,
            "checkpoint": None,
            "property_id": str(victim_property),
            "sources": [{"url": "https://victim.test/listing", "cleaned_text": ""}],
        },
    }
    async with db_pool.acquire() as conn:
        for attempt in (
            hostile,
            {**hostile, "run_state": {**hostile["run_state"], "property_id": None}},
        ):
            tr = conn.transaction()
            await tr.start()
            try:
                await _as_member(conn, bodies_hunt["owner"].user_id)
                with pytest.raises(asyncpg.PostgresError) as excinfo:
                    await conn.fetch(
                        "select * from public.answer_job_checkpoint("
                        "p_job_id => $1, p_payload => $2::jsonb, p_detail => $3::jsonb)",
                        bodies_hunt["waiting_job_id"],
                        json.dumps(attempt),
                        json.dumps({}),
                    )
                # 42883: no function matches. The parameter does not exist.
                assert excinfo.value.sqlstate == "42883"
            finally:
                await tr.rollback()

        stored = json.loads(
            await conn.fetchval(
                "select payload from jobs where id = $1", bodies_hunt["waiting_job_id"]
            )
        )
    assert stored["run_state"]["property_id"] is None
    assert stored["run_state"]["sources"][0]["url"] == "https://example.test/listing"
    assert stored["run_state"]["cursor"] == 4


async def test_answer_validation_is_server_side(db_pool, bodies_hunt) -> None:
    """The API's check at `jobs/service.py:288` is not a control -- the RPC is
    directly callable through PostgREST."""
    async with db_pool.acquire() as conn:
        for answer in ('{"choice": "maybe"}', '{"choice": 7}', '"not an object"', "{}"):
            tr = conn.transaction()
            await tr.start()
            try:
                await _as_member(conn, bodies_hunt["owner"].user_id)
                with pytest.raises(asyncpg.PostgresError) as excinfo:
                    await conn.fetch(
                        "select * from public.answer_job_checkpoint($1, $2::jsonb, $3::jsonb)",
                        bodies_hunt["waiting_job_id"],
                        answer,
                        "{}",
                    )
                assert excinfo.value.sqlstate == "22023", answer
            finally:
                await tr.rollback()


async def test_options_missing_from_the_prompt_refuses_the_answer(db_pool, bodies_hunt) -> None:
    """`'{"a":1}'::jsonb ? 'x'` is NULL when the left side is NULL, and
    `if not null` is not a raise -- which would accept any choice at all."""
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute(
                "update jobs set payload = payload #- '{run_state,checkpoint,options}' "
                "where id = $1",
                bodies_hunt["waiting_job_id"],
            )
            await _as_member(conn, bodies_hunt["owner"].user_id)
            with pytest.raises(asyncpg.PostgresError) as excinfo:
                await conn.fetch(
                    "select * from public.answer_job_checkpoint($1, $2::jsonb, $3::jsonb)",
                    bodies_hunt["waiting_job_id"],
                    '{"choice": "anything"}',
                    "{}",
                )
            assert excinfo.value.sqlstate == "22023"
        finally:
            await tr.rollback()


# ── The revoke cannot be silently undone ─────────────────────────────────────


async def test_payload_revoke_cannot_be_silently_undone(db_pool) -> None:
    """Supabase's bootstrap issues a blanket `grant select on all tables`, so a
    future migration can put the column back without anyone noticing. That is
    the DM-1 pattern and this is its third recurrence."""
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            clean = await conn.fetchval("select private.demo_preflight()")
            assert "jobs.payload is readable" not in clean
            await conn.execute("grant select (payload) on jobs to authenticated")
            problems = await conn.fetchval("select private.demo_preflight()")
            assert "jobs.payload is readable" in problems
        finally:
            await tr.rollback()
    # And the grant really is gone again.
    assert (
        await db_pool.fetchval(
            "select has_column_privilege('authenticated','public.jobs','payload','SELECT')"
        )
        is False
    )


# ── Realtime ─────────────────────────────────────────────────────────────────


async def _realtime_record(token: str, hunt_id: UUID, db_pool, job_id: UUID) -> dict | None:
    """Subscribe to `jobs` as a member, cause an UPDATE, return the record.

    Walrus filters an subscriber's columns by `has_column_privilege`, so this
    should close with the revoke -- but it is the one path where the control
    depends on an upstream component's behaviour rather than on this repo, which
    is why it gets a real socket rather than an assumption.
    """
    import websockets

    url = (
        LOCAL_SUPABASE_URL.replace("https://", "wss://").replace("http://", "ws://")
        + f"/realtime/v1/websocket?apikey={LOCAL_ANON_KEY}&vsn=1.0.0"
    )
    topic = f"realtime:payload-projection-{uuid4().hex[:6]}"
    async with websockets.connect(url, open_timeout=15) as socket:
        await socket.send(
            json.dumps(
                {
                    "topic": topic,
                    "event": "phx_join",
                    "payload": {
                        "config": {
                            "postgres_changes": [
                                {
                                    "event": "UPDATE",
                                    "schema": "public",
                                    "table": "jobs",
                                    "filter": f"hunt_id=eq.{hunt_id}",
                                }
                            ]
                        },
                        "access_token": token,
                    },
                    "ref": "1",
                }
            )
        )
        # Wait for Realtime's own readiness signal, never a fixed sleep: the
        # subscription is registered asynchronously after the join reply, and a
        # write that lands too early reports "nothing delivered" for a token
        # that was working perfectly -- a false pass on a negative assertion.
        deadline = time.monotonic() + 20
        subscribed = False
        while time.monotonic() < deadline:
            try:
                message = json.loads(await asyncio.wait_for(socket.recv(), timeout=8))
            except TimeoutError:
                break
            if message.get("event") == "system":
                subscribed = message.get("payload", {}).get("status") == "ok"
                break
        if not subscribed:
            return None

        await db_pool.execute(
            "update jobs set current_stage = 'REALTIME-PROBE' where id = $1", job_id
        )
        deadline = time.monotonic() + 10
        try:
            while time.monotonic() < deadline:
                message = json.loads(await asyncio.wait_for(socket.recv(), timeout=8))
                if message.get("event") == "postgres_changes":
                    return message["payload"]["data"]["record"]
        except TimeoutError:
            pass
    return None


async def test_realtime_update_carries_no_page_text(db_pool, bodies_hunt, seeded_users) -> None:
    record = await _realtime_record(
        seeded_users["member"].token,
        bodies_hunt["hunt_id"],
        db_pool,
        bodies_hunt["waiting_job_id"],
    )
    if record is None:
        pytest.skip("Realtime did not confirm the subscription; no honest assertion is possible")
    assert record["current_stage"] == "REALTIME-PROBE"  # positive control
    assert "payload" not in record
    assert SENTINEL not in json.dumps(record)


# ── The API paths, under a real member JWT ───────────────────────────────────


async def test_checkpoint_answer_through_the_api_preserves_source_bodies(
    as_owner: AsyncClient, db_pool, bodies_hunt
) -> None:
    """The end-to-end version of the read-modify-write hazard.

    Red with the revoke and the column list applied but the RPC unchanged: the
    API reads `payload_public`, sends it back as `p_payload`, and the RPC
    replaces the column with it.
    """
    job_id = bodies_hunt["waiting_job_id"]
    response = await as_owner.post(
        f"/v1/jobs/{job_id}/checkpoint", json={"answer": {"choice": "yes"}}
    )
    assert response.status_code == 200, response.text
    stored = json.loads(await db_pool.fetchval("select payload from jobs where id = $1", job_id))
    assert stored["run_state"]["sources"][0]["cleaned_text"].startswith(SENTINEL)
    assert stored["run_state"]["sources"][1]["cleaned_text"].startswith(SENTINEL)
    assert stored["run_state"]["status"] == "running"
    assert stored["run_state"]["checkpoint"] is None


async def test_job_detail_and_list_still_resolve_for_a_member(
    app, seeded_users, bodies_hunt
) -> None:
    """Every field the Tasks UI needs, read with the weakest member JWT."""
    from httpx import ASGITransport

    member = seeded_users["member"]
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {member.token}"},
    ) as ac:
        listed = await ac.get(f"/v1/hunts/{bodies_hunt['hunt_id']}/jobs")
        assert listed.status_code == 200, listed.text
        jobs = {job["id"]: job for job in listed.json()}

    waiting = jobs[str(bodies_hunt["waiting_job_id"])]
    assert waiting["stage_index"] == 4
    assert waiting["checkpoint"]["question"] == "Confirm the rent?"
    assert waiting["checkpoint_context"]["evidence"][0]["evidence_quote"] == "$2,450 monthly rent"

    done = jobs[str(bodies_hunt["done_job_id"])]
    assert done["auto_resolved_checkpoint"]["answer"]["choice"] == "yes"
    assert done["auto_resolved_checkpoint"]["context"]["source_url"] == (
        "https://example.test/listing"
    )
    assert SENTINEL not in json.dumps(jobs)


async def test_refresh_coalescing_still_finds_a_matching_job(
    as_owner: AsyncClient, db_pool, bodies_hunt
) -> None:
    """`listings/service.py:_refresh_matches` reads `payload.scope` and
    `payload.fields` -- a third payload consumer, under a user JWT."""
    await db_pool.execute(
        "insert into property_sources (property_id, url, site_domain, last_success_at) "
        "values ($1, 'https://example.test/listing', 'example.test', now())",
        bodies_hunt["property_id"],
    )
    listing_id = bodies_hunt["listing_id"]
    first = await as_owner.post(
        f"/v1/listings/{listing_id}/refresh", json={"fields": ["pricing"]}
    )
    assert first.status_code == 202, first.text
    second = await as_owner.post(
        f"/v1/listings/{listing_id}/refresh", json={"fields": ["pricing"]}
    )
    assert second.status_code == 202, second.text
    assert second.json()["id"] == first.json()["id"], "the second refresh did not coalesce"


async def test_the_resumed_run_state_still_carries_the_page_text(
    as_owner: AsyncClient, db_pool, bodies_hunt
) -> None:
    """What the worker actually gets back after a checkpoint answer.

    `SourceState.cleaned_text` defaults to `""`, so an emptied Source validates
    cleanly and `extract.py:336` *skips* it — the failure would be a silently
    unverified listing, not an error. Asserting through the real model rather
    than the dict is the point.
    """
    from manzil_worker.state import RunState

    job_id = bodies_hunt["waiting_job_id"]
    answer = await as_owner.post(
        f"/v1/jobs/{job_id}/checkpoint", json={"answer": {"choice": "yes"}}
    )
    assert answer.status_code == 200, answer.text

    stored = json.loads(await db_pool.fetchval("select payload from jobs where id = $1", job_id))
    resumed = RunState.model_validate(stored["run_state"])
    assert len(resumed.sources) == 2
    for source in resumed.sources:
        # The exact predicate EXTRACT skips on, and the text VERIFY audits against.
        assert source.cleaned_text, f"{source.url} resumed with no page text"
        assert source.cleaned_text.startswith(SENTINEL)


async def test_the_admin_ghost_checkpoint_answer_also_preserves_the_bodies(
    db_pool, bodies_hunt, seeded_users
) -> None:
    """The Site Admin ghost path answers checkpoints through the raw pool rather
    than the RPC, so it needs its own evidence that the revoke did not turn its
    read-modify-write into the same data loss."""
    from httpx import ASGITransport
    from manzil_api.main import create_app
    from manzil_worker.state import RunState

    identity = seeded_users["outsider"]
    job_id = bodies_hunt["waiting_job_id"]
    await db_pool.execute(
        "insert into site_admins(user_id) values($1) on conflict do nothing", identity.user_id
    )
    app = create_app()
    app.state.db_pool = db_pool
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {identity.token}"},
        ) as ghost:
            response = await ghost.post(
                f"/v1/admin/ghost/jobs/{job_id}/checkpoint", json={"answer": {"choice": "yes"}}
            )
            assert response.status_code == 200, response.text
            assert response.json()["state"] == "queued"
    finally:
        await db_pool.execute("delete from site_admins where user_id=$1", identity.user_id)

    stored = json.loads(await db_pool.fetchval("select payload from jobs where id = $1", job_id))
    resumed = RunState.model_validate(stored["run_state"])
    assert all(source.cleaned_text.startswith(SENTINEL) for source in resumed.sources)


async def test_the_demo_entry_guard_still_fires_on_the_new_signature(
    db_pool, bodies_hunt
) -> None:
    """DESIGN §16 control 4, against the *rewritten* function.

    Worth its own test because this exact regression has already happened once:
    the DM-8 harness called `answer_job_checkpoint` with parameter names no
    overload matched, PostgREST answered 404 to everyone, and the check passed
    for the wrong reason. Asserting the SQLSTATE alone would repeat that -- the
    write guard produces the same `42501` -- so this requires the entry guard's
    own `detail`, exactly as `scripts/dm8_adversarial.py` does.
    """
    demo_subject = str(uuid4())
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute("set local statement_timeout = '15s'")
            await conn.execute("delete from demo_accounts")
            await conn.execute(
                "insert into demo_accounts (user_id, note) values ($1, 'projection test')",
                UUID(demo_subject),
            )
            await conn.execute(
                "update site_settings set demo_enabled = true, demo_hunt_id = $1",
                bodies_hunt["hunt_id"],
            )
            await _as_member(conn, demo_subject)
            with pytest.raises(asyncpg.PostgresError) as excinfo:
                # Named notation, not positional: PostgREST resolves an RPC by
                # its parameter *names*, so a positional call would prove
                # nothing about the signature a browser actually reaches.
                await conn.fetch(
                    "select * from public.answer_job_checkpoint("
                    "p_job_id => $1, p_answer => $2::jsonb, p_detail => $3::jsonb)",
                    bodies_hunt["waiting_job_id"],
                    '{"choice": "yes"}',
                    "{}",
                )
        finally:
            await tr.rollback()
    assert excinfo.value.sqlstate == "42501"
    assert excinfo.value.detail == (
        "blocked public.answer_job_checkpoint(uuid,jsonb,jsonb)"
    ), "the refusal did not come from the entry guard"


async def test_a_service_role_write_computes_the_projection(bodies_hunt) -> None:
    """The generated column must be computable by *every* writer, not only the
    ones that happen to hold USAGE on `private`.

    The outer call reaches `strip_cleaned_text` by OID, so it needs no schema
    privilege — but the recursive call inside the body is resolved by name at
    execution time under the writing role, and `service_role` holds no USAGE on
    `private`. An invoker-rights transform therefore fails
    `permission denied for schema private` on every service-role insert into
    `jobs` — *intermittently*, because plpgsql caches the compiled body per
    backend and a pooled connection that already ran it as `authenticated`
    succeeds for everyone afterwards. That is why this opens its own connection:
    a fresh backend has an empty plan cache, which is the only deterministic way
    to ask the question.
    """
    import os

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute("set local role service_role")
            job_id = await conn.fetchval(
                "insert into jobs (hunt_id, type, state, payload) "
                "values ($1, 'rescore', 'queued', $2::jsonb) returning id",
                bodies_hunt["hunt_id"],
                json.dumps({"run_state": {"sources": [{"cleaned_text": BODY}]}}),
            )
            await conn.execute("reset role")
            public = await conn.fetchval(
                "select payload_public from jobs where id = $1", job_id
            )
        finally:
            await tr.rollback()
    finally:
        await conn.close()
    assert SENTINEL not in public
    assert json.loads(public) == {"run_state": {"sources": [{}]}}
