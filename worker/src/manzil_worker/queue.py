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

Dispatch is keyed on `JobType`; `ingest` and `rescore` are registered in
`build_dispatch`.
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
from manzil_shared.config import (
    JOB_ORPHAN_AFTER_SECONDS,
    MANZIL_JOB_MAX_ATTEMPTS,
    WORKER_IDLE_BACKOFF_SECONDS,
)
from manzil_shared.models import (
    Confidence,
    JobType,
    NonNegotiable,
    RubricCriterion,
    RubricOption,
)

from manzil_worker.fetching.registry import InMemoryRegistry, PostgresRegistry
from manzil_worker.fetching.tiers import Fetcher, site_domain
from manzil_worker.llm.config import model_for_stage
from manzil_worker.postgres_persistence import PostgresPersistence
from manzil_worker.runner import (
    INGEST_STAGE_NAMES,
    INGEST_STAGES,
    PHASE0_STAGE_NAMES,
    PHASE0_STAGES,
    run_job,
)
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.rescore import rescore_hunt
from manzil_worker.state import DedupeCandidate, RunState, SourceFreshness

if TYPE_CHECKING:
    import asyncpg

    from manzil_worker.stages.base import (
        CallStructured,
        DedupeCandidates,
        FreshSourceLookup,
        GeocodeAddress,
    )

log = structlog.get_logger()

JOB_ORPHAN_AFTER = timedelta(seconds=JOB_ORPHAN_AFTER_SECONDS)

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
            started_at = coalesce(started_at, now()),
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
    """Sweep `running` jobs whose heartbeat is older than `JOB_ORPHAN_AFTER`.
    Below the dead-letter cap they return to `queued` with the lock cleared and
    resume safely (stages persist before advancing, NFR3). At or above the cap
    (`attempts >= MANZIL_JOB_MAX_ATTEMPTS`) they are dead-lettered to `failed` so
    a crash loop cannot churn the queue forever — a manual retry (which resets
    `attempts`) is the only way back. Both branches happen in one atomic UPDATE
    per tick. Returns the count of rows swept (re-queued + dead-lettered)."""
    result = await conn.execute(
        """
        update jobs set
            state = case when attempts >= $2 then 'failed' else 'queued' end::job_state,
            error = case when attempts >= $2
                then 'dead-lettered: orphaned after ' || attempts::text || ' attempts'
                else error end,
            finished_at = case when attempts >= $2 then now() else finished_at end,
            locked_by = null,
            locked_at = null
        where state = 'running' and locked_at < now() - $1::interval
        """,
        JOB_ORPHAN_AFTER,
        MANZIL_JOB_MAX_ATTEMPTS,
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
        state = RunState.model_validate(snapshot)
    else:
        state = RunState(
            job_id=job["id"],
            job_type=JobType(job["type"]),
            url=payload["url"],
            hunt_listing_id=job["hunt_listing_id"],
            source_policy=payload.get("source_policy", "tiers_1_2_3"),
        )
    if payload.get("checkpoint_answer"):
        state.checkpoint_answer = payload["checkpoint_answer"]
    return state


# ── ingest dispatch ──────────────────────────────────────────────────────────


def _default_fetchers() -> dict[int, Fetcher]:
    """Real fetch ladder (mirrors the CLI): tier 1 always, tier 2 browser, tier 3
    unblocker only when a provider key is configured."""
    from manzil_worker.fetching.tier3 import Tier3Fetcher, tier3_configured
    from manzil_worker.fetching.tiers import Tier1Fetcher, Tier2Fetcher

    fetchers: dict[int, Fetcher] = {1: Tier1Fetcher(), 2: Tier2Fetcher()}
    if tier3_configured():
        fetchers[3] = Tier3Fetcher()
    else:
        log.info("tier3_off_ladder", reason="no unblocker provider key in os.environ")
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
    `property_sources` row for the fetched page (including `cleaned_text`, the
    Phase-1 debugging artifact — the exact text the extraction model saw), the
    `properties` identity update
    (name/address/official_url from EXTRACT's non-catalog block, §20 2026-07-10),
    append-only `extractions`, a `floor_plans` upsert per scorable plan, and the
    `scores` upsert per plan.

    Catalog-criterion extractions carry `hunt_id = NULL` (global facts, §8.2).
    SCORE emits one PlanScore per scorable plan (both beds+baths known). When NO
    plan is scorable — extraction (and any cross-validation) found no available
    floor plans — that is a legitimate "no availability" result, not an error
    (§8.2, §20): the source/extractions still persist, the listing is marked
    `unavailable_at = now()`, and it renders as a dimmed, null-score row. When
    plans are found the marker is cleared, so the state reverses on refresh."""

    source = state.sources[0]
    source_id = await conn.fetchval(
        """
        insert into property_sources
            (property_id, url, site_domain, cleaned_text_hash, cleaned_text,
             last_fetched_at, last_success_at)
        values ($1, $2, $3, $4, $5, now(), now())
        on conflict (url) do update set
            cleaned_text_hash = excluded.cleaned_text_hash,
            cleaned_text = excluded.cleaned_text,
            last_fetched_at = now(),
            last_success_at = now()
        returning id
        """,
        property_id,
        source.url,
        site_domain(source.url),
        source.cleaned_hash,
        source.cleaned_text,
    )

    # Project EXTRACT's identity block onto the global properties row, replacing the
    # URL-slug placeholders written at submit. Non-null-wins: an extracted value
    # overwrites, a null leaves the existing value. Phase 1 single-source
    # last-write-wins; DEDUPE/RECONCILE own identity when multi-source arrives (P3).
    identity = state.property_identity
    if identity is not None and any(
        v is not None for v in (identity.name, identity.address, identity.official_url)
    ):
        await conn.execute(
            """
            update properties set
                name = coalesce($2, name),
                canonical_address = coalesce($3, canonical_address),
                official_url = coalesce($4, official_url)
            where id = $1
            """,
            property_id,
            identity.name,
            identity.address,
            identity.official_url,
        )

    # DEDUPE's geocode → the properties forever-cache columns (§2.3, P3-4). Never
    # overwrite an existing place_id: a geocode is paid once per property, ever, so
    # a merge onto a property already geocoded keeps the cached coordinates.
    geocode = state.geocode
    if geocode is not None:
        await conn.execute(
            """
            update properties set
                place_id = coalesce(place_id, $2),
                lat = coalesce(lat, $3),
                lng = coalesce(lng, $4)
            where id = $1
            """,
            property_id,
            geocode.place_id,
            geocode.lat,
            geocode.lng,
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

    # §9.5 v1 species-specific pet rent → fee_checklist slots. Extracted amounts
    # never clobber a human 'manual' entry (the DO UPDATE's WHERE guards that);
    # only non-null amounts are written, so an unstated species stays an empty
    # slot rather than a fabricated $0.
    pet_costs = state.pet_costs
    if pet_costs is not None:
        pet_slots = {
            "pet_rent_cat": pet_costs.cat_rent_monthly,
            "pet_rent_dog": pet_costs.dog_rent_monthly,
            "pet_rent": pet_costs.pet_rent_monthly,
        }
        for slot, amount in pet_slots.items():
            if amount is None:
                continue
            await conn.execute(
                """
                insert into fee_checklist
                    (hunt_listing_id, fee_slot, amount, value_state, evidence_ref, updated_at)
                values ($1, $2, $3, 'extracted', $4, now())
                on conflict (hunt_listing_id, fee_slot) do update set
                    amount = excluded.amount,
                    value_state = excluded.value_state,
                    evidence_ref = excluded.evidence_ref,
                    updated_at = now()
                where fee_checklist.value_state <> 'manual'
                """,
                hunt_listing_id,
                slot,
                Decimal(str(amount)),
                pet_costs.evidence_quote,
            )

    # §9.5 v1 utilities-included → one append-only `utilities_included` extraction
    # (property-level, hunt_id NULL; latest row wins by design). Only when the
    # block is present and `included` was resolved (empty list = "none included").
    utilities = state.utilities
    if utilities is not None and utilities.included is not None:
        model = next((e.model for e in state.reconciled.values()), None) or model_for_stage(
            "extract"
        )
        await conn.execute(
            """
            insert into extractions
                (property_id, hunt_id, criterion_key, value, confidence,
                 evidence_quote, source_id, model)
            values ($1, null, 'utilities_included', $2::jsonb, 'high'::confidence, $3, $4, $5)
            """,
            property_id,
            json.dumps(utilities.included),
            utilities.evidence_quote,
            source_id,
            model,
        )

    scorable = [p for p in state.floor_plans if p.beds is not None and p.baths is not None]
    if not scorable:
        # No available floor plans, even after extraction/cross-validation — a
        # legitimate "no availability" result (§8.2), not an error. The source and
        # extractions above still persist; mark the listing unavailable so the
        # Overview shows a dimmed, null-score row distinct from a failed job.
        await conn.execute(
            "update hunt_listings set unavailable_at = now() where id = $1",
            hunt_listing_id,
        )
        return
    # Plans found — clear any prior no-availability marker (reversible on refresh).
    await conn.execute(
        "update hunt_listings set unavailable_at = null where id = $1",
        hunt_listing_id,
    )
    # strict=True: SCORE guarantees one PlanScore per scorable plan, so any length
    # mismatch is a real filter/order drift and must surface, not truncate.
    for plan_in, plan_score in zip(scorable, state.scores, strict=True):
        # Upsert on the natural plan key so a plan keeps a stable id across
        # refreshes — scores and pins that reference floor_plan_id stay attached.
        floor_plan_id = await conn.fetchval(
            """
            insert into floor_plans
                (property_id, source_id, plan_name, beds, baths, sqft_min, sqft_max,
                 rent_min, rent_max, deposit, availability_date, raw)
            values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb)
            on conflict (source_id, plan_name, beds, baths) do update set
                sqft_min = excluded.sqft_min,
                sqft_max = excluded.sqft_max,
                rent_min = excluded.rent_min,
                rent_max = excluded.rent_max,
                deposit = excluded.deposit,
                availability_date = excluded.availability_date,
                raw = excluded.raw
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
            # The per-plan raw extracted object (§8.2 floor_plans.raw): the full
            # FloorPlanIn as EXTRACT emitted it, including fields with no column of
            # their own (e.g. evidence_quote) — provenance for re-derivation.
            json.dumps(plan_in.model_dump(mode="json")),
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


async def _merge_into_canonical(
    conn: asyncpg.Connection,
    *,
    hunt_listing_id: UUID,
    placeholder_id: UUID,
    canonical_id: UUID,
) -> None:
    """Apply a DEDUPE merge (P3-4): re-point this listing and every row that
    references the placeholder property to the canonical one, then delete the
    placeholder. Runs in the projection's terminal transaction BEFORE
    `_persist_ingest_results`, so the run's own facts then land on the canonical
    property.

    Covers every FK to `properties` (migrations 0001/0002): `hunt_listings`,
    `property_sources`, `extractions`, `floor_plans`, `property_images`. A fresh
    placeholder has no child rows yet (its source/extractions are written by the
    projection AFTER this), so the child re-points are defensive — they matter only
    when a prior run had already persisted rows under the placeholder."""
    await conn.execute(
        "update hunt_listings set property_id = $2 where id = $1",
        hunt_listing_id,
        canonical_id,
    )
    for table in ("property_sources", "extractions", "floor_plans", "property_images"):
        await conn.execute(
            f"update {table} set property_id = $2 where property_id = $1",
            placeholder_id,
            canonical_id,
        )
    await conn.execute("delete from properties where id = $1", placeholder_id)
    log.info(
        "dedupe_merged",
        hunt_listing_id=str(hunt_listing_id),
        placeholder_id=str(placeholder_id),
        canonical_id=str(canonical_id),
    )


def _make_dedupe_candidates(pool: asyncpg.Pool, exclude_property_id: UUID) -> DedupeCandidates:
    """DEDUPE's DB seam (P3-4): every existing `properties` row except this run's
    own placeholder, as the identity inputs the stage matches against. A dumb read
    — distance + name-similarity live in the stage."""

    async def candidates() -> list[DedupeCandidate]:
        rows = await pool.fetch(
            "select id, name, canonical_address, place_id, lat, lng "
            "from properties where id <> $1",
            exclude_property_id,
        )
        return [DedupeCandidate(**dict(row)) for row in rows]

    return candidates


def make_ingest_dispatcher(
    *,
    dsn: str | None,
    fetchers_factory: FetchersFactory,
    call_structured: CallStructured | None = None,
    geocode_address: GeocodeAddress | None = None,
) -> Dispatcher:
    """Build the `ingest` handler. `fetchers_factory` is the injection seam the
    dev-seed uses to serve committed fixture pages instead of the live web;
    `call_structured` is the parallel LLM seam tests use to drive a full run
    without touching a provider; `geocode_address` is DEDUPE's geocode seam (P3-4)
    tests inject so CI never touches Google (defaults to the live Maps call via
    StageCtx)."""

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
        cats = int(settings.get("cats", 0))
        dogs = int(settings.get("dogs", 0))

        payload = json.loads(job["payload"])
        # A resumed/retried job arrives with a prior RunState snapshot; a fresh
        # submission does not — that distinction is the §10.4 manifest `trigger`.
        resumed = payload.get("run_state") is not None
        state = _build_run_state(job)
        # Seed property_id on a FRESH run only (PLAN reads it to look up persisted
        # source freshness). CRITICAL resume-correctness fix (P3-4): a resumed
        # snapshot already carries its property_id — and after a DEDUPE merge that
        # is the CANONICAL property, not the placeholder. Unconditionally assigning
        # listing["property_id"] here would clobber that merge back to the dead
        # placeholder whenever a job parks AFTER DEDUPE (e.g. at VERIFY's
        # confirm_value) and later resumes. So the snapshot's value always wins.
        if state.property_id is None:
            state.property_id = listing["property_id"]

        async def project(conn: asyncpg.Connection, done_state: RunState) -> None:
            # The canonical property is where DEDUPE landed the run (the merge
            # target, or the placeholder when nothing merged). On a merge, re-point
            # everything onto it and drop the placeholder before the run's facts are
            # written — so the projection persists against the surviving property.
            placeholder_id: UUID = listing["property_id"]
            canonical_id: UUID = done_state.property_id or placeholder_id
            if canonical_id != placeholder_id:
                await _merge_into_canonical(
                    conn,
                    hunt_listing_id=job["hunt_listing_id"],
                    placeholder_id=placeholder_id,
                    canonical_id=canonical_id,
                )
            await _persist_ingest_results(
                conn,
                hunt_listing_id=job["hunt_listing_id"],
                property_id=canonical_id,
                rubric_version=listing["rubric_version"],
                state=done_state,
            )

        # Walk + labels, selected by resume state (§2.1):
        #  * plan set → a P3 job resumes by name from its own manifest (run_job
        #    walks state.plan.stages; the passed list is unused);
        #  * plan is None AND resumed → a PRE-P3 snapshot: its integer cursor
        #    indexes the legacy 6-stage list, so it must walk PHASE0_STAGES with
        #    the lowercase labels — prepending PLAN (INGEST_STAGES) would offset
        #    the cursor by one and re-run an already-passed stage;
        #  * plan is None AND fresh → the PLAN-first manifest walk.
        if state.plan is not None:
            walk_stages, stage_names = INGEST_STAGES, list(state.plan.stages)
        elif resumed:
            walk_stages, stage_names = PHASE0_STAGES, PHASE0_STAGE_NAMES
        else:
            walk_stages, stage_names = INGEST_STAGES, INGEST_STAGE_NAMES
        # The projection runs in the same transaction as the DONE flip (see
        # PostgresPersistence.on_done), so results and terminal state commit
        # atomically — no window where the job is `done` with no result rows.
        persistence = PostgresPersistence(
            pool, job_id, stage_names, start_cursor=state.cursor, on_done=project
        )
        registry = PostgresRegistry(dsn) if dsn else InMemoryRegistry()
        ctx = StageCtx(
            fetchers=fetchers_factory(),
            registry=registry,
            rubric=rubric,
            rubric_version=listing["rubric_version"],
            min_confidence=min_confidence,
            cats=cats,
            dogs=dogs,
            persistence=persistence,
            fresh_source_lookup=_make_fresh_source_lookup(pool),
            dedupe_candidates=_make_dedupe_candidates(pool, listing["property_id"]),
            plan_trigger="user:retry" if resumed else "user:submit",
            **({} if call_structured is None else {"call_structured": call_structured}),
            **({} if geocode_address is None else {"geocode_address": geocode_address}),
        )

        await run_job(state, ctx, walk_stages)

    return dispatch


def _make_fresh_source_lookup(pool: asyncpg.Pool) -> FreshSourceLookup:
    """DB-backed PLAN seam: the persisted-source freshness inputs for
    (property, url), or None when no row exists. The TTL decision itself stays in
    PLAN (deterministic, tunable-driven) — this is a dumb read."""

    async def lookup(property_id: UUID | None, url: str) -> SourceFreshness | None:
        if property_id is None:
            return None
        row = await pool.fetchrow(
            """
            select cleaned_text_hash, cleaned_text, last_success_at
            from property_sources
            where property_id = $1 and url = $2
            """,
            property_id,
            url,
        )
        if row is None:
            return None
        return SourceFreshness(
            cleaned_text_hash=row["cleaned_text_hash"],
            cleaned_text=row["cleaned_text"] or "",
            last_success_at=row["last_success_at"],
        )

    return lookup


def make_rescore_dispatcher() -> Dispatcher:
    """Build the `rescore` handler — hunt-level, no stage machine."""

    async def dispatch(pool: asyncpg.Pool, job: asyncpg.Record) -> None:
        job_id: UUID = job["id"]
        payload = json.loads(job["payload"])
        hunt_id_raw = payload.get("hunt_id")
        if hunt_id_raw is None:
            await _mark_failed(pool, job_id, "rescore: payload missing hunt_id")
            return
        hunt_id = UUID(hunt_id_raw)

        async with pool.acquire() as conn:
            hunt = await conn.fetchrow(
                "select settings, rubric_version from hunts where id = $1",
                hunt_id,
            )
            if hunt is None:
                await _mark_failed(pool, job_id, f"rescore: hunt {hunt_id} not found")
                return
            rubric = await _load_rubric(conn, hunt_id)

        settings = json.loads(hunt["settings"]) if hunt["settings"] else {}
        min_confidence = Confidence(settings.get("min_confidence", "medium"))
        cats = int(settings.get("cats", 0))
        dogs = int(settings.get("dogs", 0))

        try:
            async with pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    """
                    insert into job_events (job_id, stage, event, detail)
                    values ($1, 'rescore', 'started', '{}'::jsonb)
                    """,
                    job_id,
                )
                await rescore_hunt(
                    conn,
                    hunt_id=hunt_id,
                    rubric=rubric,
                    rubric_version=hunt["rubric_version"],
                    min_confidence=min_confidence,
                    cats=cats,
                    dogs=dogs,
                )
                await conn.execute(
                    """
                    update jobs set
                        state = 'done',
                        finished_at = now(),
                        locked_by = null,
                        locked_at = null,
                        current_stage = 'rescore'
                    where id = $1
                    """,
                    job_id,
                )
                await conn.execute(
                    """
                    insert into job_events (job_id, stage, event, detail)
                    values ($1, 'rescore', 'completed', '{}'::jsonb)
                    """,
                    job_id,
                )
        except Exception as error:
            log.error("rescore_failed", job_id=str(job_id), error=str(error))
            await _mark_failed(pool, job_id, f"rescore: {error}")
            return
        log.info("rescore_job_done", job_id=str(job_id), hunt_id=str(hunt_id))

    return dispatch


def build_dispatch(
    pool: asyncpg.Pool,
    *,
    dsn: str | None = None,
    fetchers_factory: FetchersFactory | None = None,
) -> dict[JobType, Dispatcher]:
    """The `job_type -> dispatcher` table. `ingest` and `rescore` (P1-6).
    `dsn` (when given) backs the per-domain adapter registry."""
    dsn = dsn or os.environ.get("DATABASE_URL")
    return {
        JobType.INGEST: make_ingest_dispatcher(
            dsn=dsn, fetchers_factory=fetchers_factory or _default_fetchers
        ),
        JobType.RESCORE: make_rescore_dispatcher(),
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
