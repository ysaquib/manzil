"""Durable Postgres job queue + in-process worker loop (P1-2, DESIGN §5, §10.1).

The queue is the `jobs` table. A worker claims the oldest queued row with
`FOR UPDATE SKIP LOCKED`, runs the stage machine against `PostgresPersistence`
(so state lands in Postgres before every cursor advance), and on success writes
the run's facts (property source, floor plans, extractions, scores) back to the
global/per-hunt tables — the writes DESIGN §5 assigns to the worker, since the
Phase 0 stages compute results but never persisted them.

Crash recovery (NFR3): the claiming worker heartbeats `locked_at` at every stage
boundary; a `running` job whose heartbeat is older than `JOB_ORPHAN_AFTER` is
reclaimed to `queued` by `reclaim_orphans` (run every tick) and resumed from its
`current_stage`. Clean shutdown drains the in-flight job before exiting.

Dispatch is keyed on `JobType`; only `ingest` is implemented here. A later task
adds `rescore` by registering one more entry in `build_dispatch`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from manzil_shared.config import JOB_ORPHAN_AFTER_SECONDS, WORKER_IDLE_BACKOFF_SECONDS
from manzil_shared.errors import StageFatal
from manzil_shared.models import (
    Confidence,
    JobType,
    NonNegotiable,
    RubricCriterion,
    RubricOption,
)

from manzil_worker.fetching.registry import InMemoryRegistry, PostgresRegistry
from manzil_worker.fetching.tiers import Fetcher, site_domain
from manzil_worker.postgres_persistence import PostgresPersistence
from manzil_worker.runner import PHASE0_STAGES, run_job
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import RunState

if TYPE_CHECKING:
    import asyncpg

log = structlog.get_logger()

JOB_ORPHAN_AFTER = timedelta(seconds=JOB_ORPHAN_AFTER_SECONDS)
_STAGE_NAMES = [name for name, _ in PHASE0_STAGES]

# A dispatcher runs one claimed job to a terminal state (raising only on
# unexpected failure — the runner maps stage errors to `failed` itself).
Dispatcher = Callable[["asyncpg.Pool", "asyncpg.Record"], Awaitable[None]]
FetchersFactory = Callable[[], dict[int, Fetcher]]


# ── queue primitives ─────────────────────────────────────────────────────────


async def claim_next_job(conn: asyncpg.Connection, worker_id: str) -> asyncpg.Record | None:
    """Claim the oldest queued job (`jobs_claim_idx` order), skipping rows other
    workers hold. Atomic: the `FOR UPDATE SKIP LOCKED` select and the state flip
    are one statement, so two workers never claim the same row."""
    return await conn.fetchrow(
        """
        with next_job as (
            select id from jobs
            where state = 'queued'
            order by created_at
            for update skip locked
            limit 1
        )
        update jobs set
            state = 'running',
            locked_by = $1,
            locked_at = now(),
            attempts = attempts + 1
        from next_job
        where jobs.id = next_job.id
        returning jobs.*
        """,
        worker_id,
    )


async def heartbeat(conn: asyncpg.Connection, job_id: UUID) -> None:
    """Refresh a running job's `locked_at` so it is not seen as orphaned."""
    await conn.execute(
        "update jobs set locked_at = now() where id = $1 and state = 'running'",
        job_id,
    )


async def reclaim_orphans(conn: asyncpg.Connection) -> int:
    """Return every `running` job whose heartbeat is older than
    `JOB_ORPHAN_AFTER` to `queued` with its lock cleared. Resumption is safe
    because stages persist before advancing (NFR3). Returns the count reclaimed."""
    result = await conn.execute(
        """
        update jobs set state = 'queued', locked_by = null, locked_at = null
        where state = 'running' and locked_at < now() - $1::interval
        """,
        JOB_ORPHAN_AFTER,
    )
    return int(result.split()[-1])  # "UPDATE <n>"


async def _mark_failed(pool: asyncpg.Pool, job_id: UUID, error: str) -> None:
    await pool.execute(
        """
        update jobs set state = 'failed', error = $2, finished_at = now(), locked_by = null
        where id = $1
        """,
        job_id,
        error,
    )


# ── rubric / state loading ───────────────────────────────────────────────────


def _rubric_criterion(row: asyncpg.Record) -> RubricCriterion:
    options = [RubricOption.model_validate(o) for o in json.loads(row["options"])]
    nn = json.loads(row["non_negotiable"]) if row["non_negotiable"] else None
    custom_def = json.loads(row["custom_def"]) if row["custom_def"] else None
    return RubricCriterion(
        hunt_id=row["hunt_id"],
        catalog_key=row["catalog_key"],
        custom_def=custom_def,
        options=options,
        unknown_delta=float(row["unknown_delta"]),
        non_negotiable=NonNegotiable(**nn) if nn else None,
        is_bonus=row["is_bonus"],
        position=row["position"],
    )


async def _load_rubric(conn: asyncpg.Connection, hunt_id: UUID) -> list[RubricCriterion]:
    rows = await conn.fetch(
        """
        select hunt_id, catalog_key, custom_def, options, unknown_delta,
               non_negotiable, is_bonus, position
        from rubric_criteria
        where hunt_id = $1 and enabled
        order by position
        """,
        hunt_id,
    )
    return [_rubric_criterion(r) for r in rows]


def _build_run_state(job: asyncpg.Record) -> RunState:
    """Fresh from the enqueue payload, or reconstructed from a persisted snapshot
    (resume). The snapshot carries the resume cursor and all prior stage output."""
    payload = json.loads(job["payload"])
    snapshot = payload.get("run_state")
    if snapshot is not None:
        return RunState.model_validate(snapshot)
    return RunState(
        job_id=job["id"],
        job_type=JobType(job["type"]),
        url=payload["url"],
        hunt_listing_id=job["hunt_listing_id"],
        source_policy=payload.get("source_policy", "tiers_1_2_3"),
    )


# ── ingest dispatch ──────────────────────────────────────────────────────────


def _default_fetchers() -> dict[int, Fetcher]:
    """Real fetch ladder (mirrors the CLI): tier 1 always, tier 2 browser, tier 3
    unblocker only when a provider key is configured."""
    from manzil_worker.fetching.tier3 import Tier3Fetcher, tier3_configured
    from manzil_worker.fetching.tiers import Tier1Fetcher, Tier2Fetcher

    fetchers: dict[int, Fetcher] = {1: Tier1Fetcher(), 2: Tier2Fetcher()}
    if tier3_configured():
        fetchers[3] = Tier3Fetcher()
    return fetchers


async def _persist_ingest_results(
    conn: asyncpg.Connection,
    *,
    hunt_listing_id: UUID,
    property_id: UUID,
    rubric_version: int,
    state: RunState,
) -> None:
    """Write the completed run's facts to Postgres (DESIGN §5, §8.2): one
    `property_sources` row for the fetched page, append-only `extractions`, a
    `floor_plans` row per scorable plan, and the `scores` upsert per plan.

    Catalog-criterion extractions carry `hunt_id = NULL` (global facts, §8.2).
    SCORE emits one PlanScore per scorable plan (both beds+baths known) in that
    order — or, when NO plan is scorable, a single property-level PlanScore
    (`plan_name is None`). The `scores` table keys on a NOT-NULL `floor_plan_id`
    (§8.2), so a property-level score has nowhere to go; that case is raised
    rather than silently dropped (see below), pending a routing decision."""
    source = state.sources[0]
    source_id = await conn.fetchval(
        """
        insert into property_sources
            (property_id, url, site_domain, cleaned_text_hash, last_fetched_at, last_success_at)
        values ($1, $2, $3, $4, now(), now())
        on conflict (url) do update set
            cleaned_text_hash = excluded.cleaned_text_hash,
            last_fetched_at = now(),
            last_success_at = now()
        returning id
        """,
        property_id,
        source.url,
        site_domain(source.url),
        source.cleaned_hash,
    )

    for key, ext in state.reconciled.items():
        await conn.execute(
            """
            insert into extractions
                (property_id, hunt_id, criterion_key, value, confidence,
                 evidence_quote, source_id, model)
            values ($1, null, $2, $3::jsonb, $4::confidence, $5, $6, $7)
            """,
            property_id,
            key,
            json.dumps(ext.value),
            ext.confidence.value,
            ext.evidence_quote,
            source_id,
            ext.model,
        )

    scorable = [p for p in state.floor_plans if p.beds is not None and p.baths is not None]
    if not scorable:
        # Property-level score only: scores.floor_plan_id is NOT NULL (§8.2), so
        # there is no valid row to write. Fail loudly instead of ending done-empty
        # — routing property-level scores is a schema decision, not one to guess.
        raise StageFatal(
            "property-level score (no floor plan with both beds and baths) cannot be "
            "persisted: scores.floor_plan_id is NOT NULL (DESIGN §8.2) — needs a routing decision"
        )
    # strict=True: SCORE guarantees one PlanScore per scorable plan, so any length
    # mismatch is a real filter/order drift and must surface, not truncate.
    for plan_in, plan_score in zip(scorable, state.scores, strict=True):
        floor_plan_id = await conn.fetchval(
            """
            insert into floor_plans
                (property_id, source_id, plan_name, beds, baths, sqft_min, sqft_max,
                 rent_min, rent_max, deposit, availability_date)
            values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            returning id
            """,
            property_id,
            source_id,
            plan_in.plan_name or "unnamed",
            plan_in.beds,
            Decimal(str(plan_in.baths)),
            plan_in.sqft_min,
            plan_in.sqft_max,
            None if plan_in.rent_min is None else Decimal(str(plan_in.rent_min)),
            None if plan_in.rent_max is None else Decimal(str(plan_in.rent_max)),
            None if plan_in.deposit is None else Decimal(str(plan_in.deposit)),
            date.fromisoformat(plan_in.availability_date) if plan_in.availability_date else None,
        )
        await conn.execute(
            """
            insert into scores (hunt_listing_id, floor_plan_id, total, breakdown, rubric_version)
            values ($1, $2, $3, $4::jsonb, $5)
            on conflict (hunt_listing_id, floor_plan_id) do update set
                total = excluded.total,
                breakdown = excluded.breakdown,
                rubric_version = excluded.rubric_version,
                computed_at = now()
            """,
            hunt_listing_id,
            floor_plan_id,
            Decimal(str(plan_score.breakdown["total"])),
            json.dumps(plan_score.breakdown),
            rubric_version,
        )


def make_ingest_dispatcher(
    *,
    dsn: str | None,
    fetchers_factory: FetchersFactory,
) -> Dispatcher:
    """Build the `ingest` handler. `fetchers_factory` is the injection seam the
    dev-seed uses to serve committed fixture pages instead of the live web."""

    async def dispatch(pool: asyncpg.Pool, job: asyncpg.Record) -> None:
        job_id: UUID = job["id"]
        if job["hunt_listing_id"] is None:
            await _mark_failed(pool, job_id, "ingest: job has no hunt_listing_id")
            return
        async with pool.acquire() as conn:
            listing = await conn.fetchrow(
                """
                select hl.property_id, hl.hunt_id, h.settings, h.rubric_version
                from hunt_listings hl join hunts h on h.id = hl.hunt_id
                where hl.id = $1
                """,
                job["hunt_listing_id"],
            )
            if listing is None:
                await _mark_failed(pool, job_id, "ingest: hunt_listing not found")
                return
            rubric = await _load_rubric(conn, listing["hunt_id"])

        settings = json.loads(listing["settings"]) if listing["settings"] else {}
        min_confidence = Confidence(settings.get("min_confidence", "medium"))
        state = _build_run_state(job)

        async def project(conn: asyncpg.Connection, done_state: RunState) -> None:
            await _persist_ingest_results(
                conn,
                hunt_listing_id=job["hunt_listing_id"],
                property_id=listing["property_id"],
                rubric_version=listing["rubric_version"],
                state=done_state,
            )

        # The projection runs in the same transaction as the DONE flip (see
        # PostgresPersistence.on_done), so results and terminal state commit
        # atomically — no window where the job is `done` with no result rows.
        persistence = PostgresPersistence(
            pool, job_id, _STAGE_NAMES, start_cursor=state.cursor, on_done=project
        )
        registry = PostgresRegistry(dsn) if dsn else InMemoryRegistry()
        ctx = StageCtx(
            fetchers=fetchers_factory(),
            registry=registry,
            rubric=rubric,
            rubric_version=listing["rubric_version"],
            min_confidence=min_confidence,
            persistence=persistence,
        )

        await run_job(state, ctx)

    return dispatch


def build_dispatch(
    pool: asyncpg.Pool,
    *,
    dsn: str | None = None,
    fetchers_factory: FetchersFactory | None = None,
) -> dict[JobType, Dispatcher]:
    """The `job_type -> dispatcher` table. Only `ingest` today; `rescore` is one
    more entry (P1-6). `dsn` (when given) backs the per-domain adapter registry."""
    dsn = dsn or os.environ.get("DATABASE_URL")
    return {
        JobType.INGEST: make_ingest_dispatcher(
            dsn=dsn, fetchers_factory=fetchers_factory or _default_fetchers
        ),
    }


# ── the loop ─────────────────────────────────────────────────────────────────


async def run_worker_loop(
    pool: asyncpg.Pool,
    stop: asyncio.Event,
    *,
    dispatch: dict[JobType, Dispatcher] | None = None,
    worker_id: str | None = None,
    idle_backoff: float = WORKER_IDLE_BACKOFF_SECONDS,
    until_empty: bool = False,
) -> None:
    """Tick: reclaim orphans → claim → dispatch by `job_type` → repeat.

    Clean-shutdown drain: once `stop` is set the loop claims nothing new but the
    in-flight job (already claimed this tick) runs to completion before exit.
    `until_empty` returns when the queue drains instead of idling — the bounded
    drain the dev-seed and tests use.
    """
    dispatch = dispatch if dispatch is not None else build_dispatch(pool)
    worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"

    while not stop.is_set():
        async with pool.acquire() as conn:
            await reclaim_orphans(conn)
            job = await claim_next_job(conn, worker_id)

        if job is None:
            if until_empty:
                return
            # Wake early on shutdown rather than sleeping the full backoff.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=idle_backoff)
            continue

        job_type_raw = job["type"]
        handler = dispatch.get(JobType(job_type_raw))
        if handler is None:
            await _mark_failed(pool, job["id"], f"no dispatcher for job_type {job_type_raw!r}")
            continue

        log.info("job_claimed", job_id=str(job["id"]), job_type=job_type_raw, worker=worker_id)
        try:
            async with pool.acquire() as conn:
                await heartbeat(conn, job["id"])
            await handler(pool, job)
        except asyncio.CancelledError:
            raise  # shutdown/cancellation: leave the row locked for orphan reclaim
        except Exception as error:
            log.error("job_dispatch_failed", job_id=str(job["id"]), error=str(error))
            await _mark_failed(pool, job["id"], f"dispatch error: {error}")
