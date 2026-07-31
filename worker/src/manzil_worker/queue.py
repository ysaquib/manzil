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
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog
from manzil_shared.config import (
    CHECKPOINT_TIMEOUT_HOURS,
    JOB_ORPHAN_AFTER_SECONDS,
    MANZIL_JOB_MAX_ATTEMPTS,
    REFRESH_TTL_HOURS,
    SCHEDULER_TICK_SECONDS,
    UTILITY_BASELINE_RETRY_SECONDS,
    WORKER_IDLE_BACKOFF_SECONDS,
)
from manzil_shared.models import (
    Confidence,
    JobType,
    NonNegotiable,
    RubricCriterion,
    RubricOption,
    TargetScope,
    UnitApplicability,
)

from manzil_worker.discovery_sources import source_metadata
from manzil_worker.enrich.contacts import (
    ContactProvenance,
    ContactRecord,
    build_contact_records,
)
from manzil_worker.enrich.images import SupabaseImageStore
from manzil_worker.fetching.registry import InMemoryRegistry, PostgresRegistry
from manzil_worker.fetching.tiers import Fetcher, site_domain
from manzil_worker.llm.config import model_for_stage
from manzil_worker.postgres_persistence import PostgresPersistence, make_tool_event_sink
from manzil_worker.runner import (
    INGEST_STAGE_NAMES,
    INGEST_STAGES,
    PHASE0_STAGE_NAMES,
    PHASE0_STAGES,
    REFRESH_STAGE_NAMES,
    REFRESH_STAGES,
    run_job,
)
from manzil_worker.scoped_facts import (
    append_candidate_resolution,
    persist_reconciled_claims,
    persist_single_source_claims,
)
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.pet_costs import slot_for_fee, slot_for_one_time_fee
from manzil_worker.stages.rescore import rescore_hunt
from manzil_worker.state import (
    DedupeCandidate,
    FloorPlanIn,
    GeocodeIn,
    PlanManifest,
    PlanSource,
    PropertyIdentityIn,
    RefreshSource,
    RunState,
    SourceClaim,
    SourceFreshness,
    SourceState,
)

if TYPE_CHECKING:
    import asyncpg

    from manzil_worker.stages.base import (
        CallAgent,
        CallStructured,
        CommuteMinutes,
        DedupeCandidates,
        FreshSourceLookup,
        GeocodeAddress,
        NearbyPlaces,
        RefreshSourceLookup,
    )

log = structlog.get_logger()

JOB_ORPHAN_AFTER = timedelta(seconds=JOB_ORPHAN_AFTER_SECONDS)

# A dispatcher runs one claimed job to a terminal state (raising only on
# unexpected failure — the runner maps stage errors to `failed` itself).
Dispatcher = Callable[["asyncpg.Pool", "asyncpg.Record"], Awaitable[None]]

# Scheduler duty (P3-9 scaffold): invoked by run_worker_loop at most every
# SCHEDULER_TICK_SECONDS when wired (production only). P3-11's checkpoint sweep
# and P3-12's TTL refresh extend the same seam.
SchedulerTick = Callable[["asyncpg.Pool"], Awaitable[None]]
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


def _make_reconcile_rubric_lookup(pool: asyncpg.Pool):
    async def lookup(property_id: UUID) -> list[RubricCriterion]:
        rows = await pool.fetch(
            """
            select rc.hunt_id, rc.catalog_key, rc.custom_def, rc.options,
                   rc.unknown_delta, rc.non_negotiable, rc.is_bonus, rc.position
            from rubric_criteria rc
            where rc.enabled and exists (
                select 1 from hunt_listings hl
                where hl.hunt_id = rc.hunt_id
                  and hl.property_id = $1
            )
            """,
            property_id,
        )
        return [_rubric_criterion(row) for row in rows]

    return lookup


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
            custom_criterion_keys=payload.get("custom_criterion_keys", []),
        )
    if payload.get("checkpoint_answer"):
        state.checkpoint_answer = payload["checkpoint_answer"]
    return state


# ── ingest dispatch ──────────────────────────────────────────────────────────

_PROCESS_FETCHERS: dict[int, Fetcher] | None = None


def _default_fetchers() -> dict[int, Fetcher]:
    """Real fetch ladder (mirrors the CLI): tier 1 always, tier 2 browser, tier 3
    unblocker only when a provider key is configured. The instances are shared
    for the process lifetime so Tier 2's per-domain politeness lock covers Jobs,
    not merely Sources within one Job."""
    global _PROCESS_FETCHERS
    if _PROCESS_FETCHERS is not None:
        return _PROCESS_FETCHERS
    from manzil_worker.fetching.tier3 import Tier3Fetcher, tier3_configured
    from manzil_worker.fetching.tiers import Tier1Fetcher, Tier2Fetcher

    fetchers: dict[int, Fetcher] = {1: Tier1Fetcher(), 2: Tier2Fetcher()}
    if tier3_configured():
        fetchers[3] = Tier3Fetcher()
    else:
        log.info("tier3_off_ladder", reason="no unblocker provider key in os.environ")
    _PROCESS_FETCHERS = fetchers
    return _PROCESS_FETCHERS


async def _persist_discovery_results(
    conn: asyncpg.Connection,
    *,
    hunt_listing_id: UUID,
    property_id: UUID,
    submitted_url: str,
    state: RunState,
) -> None:
    """Persist DISCOVER's link-only Source pool and Listing assurance state.

    This projection is shared by a full ingest and the P3-5 policy-relaxation
    refresh. It never fetches or deletes Sources: discovery is append-only, and
    an existing URL owned by another Property is left in place for DEDUPE rather
    than silently re-parented.
    """
    for discovered in state.discovered_sources:
        if discovered.url == submitted_url:
            continue
        await conn.execute(
            """
            insert into property_sources (property_id, url, site_domain, is_official)
            values ($1, $2, $3, $4)
            on conflict (url) do update set
                is_official = property_sources.is_official or excluded.is_official
            where property_sources.property_id = excluded.property_id
            """,
            property_id,
            discovered.url,
            discovered.site_domain,
            discovered.is_official,
        )

    if state.official_source_url is not None:
        await conn.execute(
            "update properties set official_url = $2 where id = $1",
            property_id,
            state.official_source_url,
        )
    await conn.execute(
        "update hunt_listings set single_source_reason = $2 where id = $1",
        hunt_listing_id,
        state.single_source_reason,
    )


async def _persist_property_contacts(
    conn: asyncpg.Connection,
    *,
    property_id: UUID,
    source_id: UUID,
    source_is_official: bool,
    state: RunState,
) -> None:
    """Write the run's contact observations (P3-21, DESIGN §8.2, §16).

    Two producers, three rungs: EXTRACT's page block is `official_site` when the
    fetched Source is the property's official site and `listing` otherwise, and
    ENRICH's Places block is always `google_places`. Precedence between them is
    the `property_contacts_current` view's job, not this function's — every
    observation is recorded, and the view picks the winner.

    Values that fail normalization are dropped, never raised: a missing contact is
    the designed give-up state (§13.2 renders no Contact row and the reader falls
    back to the official link), so an unparseable phone must not fail a job.
    """
    official_url = await conn.fetchval(
        "select official_url from properties where id = $1", property_id
    )

    records: list[tuple[ContactRecord, UUID | None]] = []
    if state.property_contact is not None:
        provenance = (
            ContactProvenance.OFFICIAL_SITE if source_is_official else ContactProvenance.LISTING
        )
        for record in build_contact_records(
            phone=state.property_contact.phone,
            contact_url=state.property_contact.contact_url,
            provenance=provenance,
            official_url=official_url,
        ):
            records.append((record, source_id))
    if state.maps_contact is not None:
        for record in build_contact_records(
            phone=state.maps_contact.phone,
            contact_url=state.maps_contact.contact_url,
            provenance=ContactProvenance.GOOGLE_PLACES,
            official_url=official_url,
        ):
            # No source_id: Places is an API observation, not one of our Sources.
            records.append((record, None))

    for record, record_source_id in records:
        await conn.execute(
            """
            insert into property_contacts (property_id, kind, value, provenance, source_id)
            values ($1, $2, $3, $4, $5)
            on conflict (property_id, kind, value, provenance)
                do update set observed_at = now(), source_id = excluded.source_id
            """,
            property_id,
            record.kind.value,
            record.value,
            record.provenance.value,
            record_source_id,
        )


async def _upsert_floor_plans(
    conn: asyncpg.Connection,
    *,
    property_id: UUID,
    source_id: UUID,
    state: RunState,
) -> tuple[list[FloorPlanIn], list[UUID], dict[str, UUID]]:
    """Persist Source-local Floor Plans before scoped claims (P3-SC2 order)."""
    scorable = [
        plan for plan in state.floor_plans if plan.beds is not None and plan.baths is not None
    ]
    floor_plan_ids: list[UUID] = []
    ids_by_ref: dict[str, UUID] = {}
    for index, plan in enumerate(scorable):
        if plan.response_key is None:
            plan.response_key = f"plan:{index}"
        conflict = (
            "(source_id, source_native_id) where source_native_id is not null"
            if plan.source_native_id is not None
            else "(source_id, plan_name, beds, baths) where source_native_id is null"
        )
        floor_plan_id: UUID = await conn.fetchval(
            f"""
            insert into floor_plans
                (property_id, source_id, source_native_id, detail_url, plan_name, beds, baths,
                 unit_types,
                 sqft_min, sqft_max, rent_min, rent_max, deposit, availability_date,
                 last_seen_at, is_current, raw)
            values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, $11, $12, $13, $14,
                    now(), true, $15::jsonb)
            on conflict {conflict} do update set
                detail_url = coalesce(excluded.detail_url, floor_plans.detail_url),
                unit_types = excluded.unit_types,
                sqft_min = excluded.sqft_min,
                sqft_max = excluded.sqft_max,
                rent_min = excluded.rent_min,
                rent_max = excluded.rent_max,
                deposit = excluded.deposit,
                availability_date = excluded.availability_date,
                last_seen_at = now(),
                is_current = true,
                raw = excluded.raw
            returning id
            """,
            property_id,
            source_id,
            plan.source_native_id,
            plan.detail_url,
            plan.plan_name or "unnamed",
            plan.beds,
            Decimal(str(plan.baths)),
            json.dumps(plan.unit_types),
            plan.sqft_min,
            plan.sqft_max,
            None if plan.rent_min is None else Decimal(str(plan.rent_min)),
            None if plan.rent_max is None else Decimal(str(plan.rent_max)),
            None if plan.deposit is None else Decimal(str(plan.deposit)),
            date.fromisoformat(plan.availability_date) if plan.availability_date else None,
            json.dumps(plan.model_dump(mode="json")),
        )
        floor_plan_ids.append(floor_plan_id)
        ids_by_ref[plan.response_key] = floor_plan_id

    if state.sources[0].authoritative_extraction:
        await conn.execute(
            """
            update floor_plans set is_current = false
            where source_id = $1 and is_current
              and not (id = any($2::uuid[]))
            """,
            source_id,
            floor_plan_ids,
        )
    return list(scorable), floor_plan_ids, ids_by_ref


def _auxiliary_claims(state: RunState, source_url: str) -> list[SourceClaim]:
    """Convert non-Catalog EXTRACT blocks into ordinary scoped claims."""
    model = next((claim.model for claim in state.source_claims), None) or model_for_stage("extract")
    prompt_version = next((claim.prompt_version for claim in state.source_claims), 0)
    claims: list[SourceClaim] = []

    def add(key: str, value: object, evidence: str | None) -> None:
        claims.append(
            SourceClaim(
                criterion_key=key,
                value=value,
                confidence=Confidence.HIGH,
                evidence_quote=evidence,
                source_id=source_url,
                model=model,
                prompt_version=prompt_version,
                target_scope=TargetScope.PROPERTY,
            )
        )

    if state.utilities is not None and state.utilities.included is not None:
        add("utilities_included", list(state.utilities.included), state.utilities.evidence_quote)
    if state.mandatory_fees is not None and state.mandatory_fees.fees:
        add(
            "mandatory_fees",
            [fee.model_dump(mode="json") for fee in state.mandatory_fees.fees],
            state.mandatory_fees.evidence_quote,
        )
    if state.one_time_fees is not None and state.one_time_fees.fees:
        add(
            "one_time_fees",
            [fee.model_dump(mode="json") for fee in state.one_time_fees.fees],
            state.one_time_fees.evidence_quote,
        )
    # Snapshot compatibility only: P3-SC4 emits heating_type directly in
    # state.source_claims. Older persisted RunState snapshots may still carry
    # the former singleton block, so preserve it without promoting its scope.
    if state.heating is not None and state.heating.heating is not None:
        add("heating_type", state.heating.heating, state.heating.evidence_quote)
    return claims


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

    source = next(item for item in state.sources if item.url == state.url)
    source_ids_by_url: dict[str, UUID] = {
        row["url"]: row["id"]
        for row in await conn.fetch(
            "select id, url from property_sources where property_id = $1",
            property_id,
        )
    }
    source_official_by_url: dict[str, bool] = {
        row["url"]: row["is_official"]
        for row in await conn.fetch(
            "select url, is_official from property_sources where property_id = $1",
            property_id,
        )
    }
    for fetched_source in state.sources:
        # PLAN may preload an already-persisted Source for a hash-fresh skip.
        # Keep that row untouched. Synthetic/replay states historically omit
        # fetched_at, however, so a Source with no persisted identity still
        # needs the normal upsert.
        planned = (
            next(
                (item for item in state.plan.sources if item.url == fetched_source.url),
                None,
            )
            if state.plan is not None
            else None
        )
        if (
            fetched_source.fetched_at is None
            and fetched_source.url in source_ids_by_url
            and planned is not None
            and planned.action == "skip"
        ):
            continue
        source_row = await conn.fetchrow(
            """
            insert into property_sources
                (property_id, url, site_domain, is_official, cleaned_text_hash,
                 cleaned_text, image_urls, last_fetched_at, last_success_at)
            values ($1, $2, $3, $4, $5, $6, $7::jsonb, now(), now())
            on conflict (url) do update set
                is_official = property_sources.is_official or excluded.is_official,
                cleaned_text_hash = excluded.cleaned_text_hash,
                cleaned_text = excluded.cleaned_text,
                image_urls = excluded.image_urls,
                last_fetched_at = now(),
                last_success_at = now()
            returning id, is_official
            """,
            property_id,
            fetched_source.url,
            site_domain(fetched_source.url),
            fetched_source.is_official or state.official_source_url == fetched_source.url,
            fetched_source.cleaned_hash,
            fetched_source.cleaned_text,
            json.dumps(fetched_source.image_urls),
        )
        source_ids_by_url[fetched_source.url] = source_row["id"]
        source_official_by_url[fetched_source.url] = source_row["is_official"]
    source_id = source_ids_by_url[source.url]
    await conn.execute(
        """
        update hunt_listings
        set submitted_source_id = coalesce(submitted_source_id, $2)
        where id = $1
        """,
        hunt_listing_id,
        source_id,
    )
    # The persisted flag, not this run's: DISCOVER may have already marked the URL
    # official, and the upsert ORs the two. P3-21 reads it to rank the page's
    # contact block as the official-site rung rather than a plain listing.
    source_is_official = source_official_by_url[source.url]

    await _persist_discovery_results(
        conn,
        hunt_listing_id=hunt_listing_id,
        property_id=property_id,
        submitted_url=source.url,
        state=state,
    )

    # IMAGE_FETCH outputs are content-addressed. The later scheduler cleanup
    # removes unreferenced Storage objects after the retention window.
    #
    # Retirement is **Source-local** (§P3-SC5, DESIGN "refresh authority is
    # Source-local"): only a Source this run actually fetched may retire its
    # own images. A Property-wide sweep here would let a run over one Source
    # silently retire every other Source's photos and Floor Plan diagrams.
    refreshed_source_ids = [
        source_ids_by_url[fetched.url]
        for fetched in state.sources
        if fetched.url in source_ids_by_url
    ]
    current_hashes = [image.content_hash for image in state.property_images]
    if state.image_fetch_completed and refreshed_source_ids:
        await conn.execute(
            "update property_images set is_current = false "
            "where property_id = $1 and source_id = any($2::uuid[]) "
            "and not (content_hash = any($3::text[]))",
            property_id,
            refreshed_source_ids,
            current_hashes,
        )
    image_ids_by_hash: dict[str, UUID] = {}
    for image in state.property_images:
        image_source_id = await conn.fetchval(
            "select id from property_sources where property_id = $1 and url = $2",
            property_id,
            image.source_url_page or source.url,
        )
        image_id = await conn.fetchval(
            """
            insert into property_images
                (property_id, source_url, storage_path, content_hash, width,
                 height, byte_size, kind, vision_assessment, source_id,
                 source_page_order, perceptual_hash, normalization_profile,
                 discovery_context, is_current)
            values ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11,
                    $12, $13, $14::jsonb, true)
            on conflict (property_id, content_hash) where content_hash is not null do update set
                source_url = excluded.source_url,
                storage_path = excluded.storage_path,
                width = excluded.width,
                height = excluded.height,
                byte_size = excluded.byte_size,
                kind = coalesce(excluded.kind, property_images.kind),
                source_id = coalesce(excluded.source_id, property_images.source_id),
                source_page_order = excluded.source_page_order,
                perceptual_hash = excluded.perceptual_hash,
                normalization_profile = excluded.normalization_profile,
                discovery_context = excluded.discovery_context,
                is_current = true,
                vision_assessment = coalesce(
                    excluded.vision_assessment, property_images.vision_assessment
                )
            returning id
            """,
            property_id,
            image.source_url,
            image.storage_path,
            image.content_hash,
            image.width,
            image.height,
            image.byte_size,
            image.kind,
            json.dumps(image.vision_assessment) if image.vision_assessment is not None else None,
            image_source_id,
            image.source_page_order,
            image.perceptual_hash,
            image.normalization_profile,
            json.dumps(image.discovery_context),
        )
        image_ids_by_hash[image.content_hash] = image_id

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
                lng = coalesce(lng, $4),
                city = coalesce(city, $5),
                state = coalesce(state, $6),
                county = coalesce(county, $7)
            where id = $1
            """,
            property_id,
            geocode.place_id,
            geocode.lat,
            geocode.lng,
            geocode.city,
            geocode.state,
            geocode.county,
        )

    # P3-21: after the identity projection so the contact-URL domain guard sees the
    # freshest official_url, and before scoring — which never reads contacts.
    await _persist_property_contacts(
        conn,
        property_id=property_id,
        source_id=source_id,
        source_is_official=source_is_official,
        state=state,
    )

    # P3-SC2's load-bearing persistence order: Floor Plans first so response-local
    # references can resolve, then candidate/resolution facts + lineage, then
    # scores/projection. No scoped fact can point across Properties.
    scorable: list[FloorPlanIn] = []
    floor_plan_ids: list[UUID] = []
    floor_plan_ids_by_ref: dict[str, UUID] = {}
    floor_plan_ids_by_source_ref: dict[tuple[str, str], UUID] = {}
    if state.source_results:
        for result in state.source_results:
            result_source_id = source_ids_by_url.get(result.source_url)
            result_source = next(
                (item for item in state.sources if item.url == result.source_url),
                None,
            )
            if result_source_id is None or result_source is None:
                continue
            isolated = state.model_copy(deep=True)
            isolated.sources = [result_source.model_copy(deep=True)]
            isolated.floor_plans = [plan.model_copy(deep=True) for plan in result.floor_plans]
            result_scorable, result_ids, result_refs = await _upsert_floor_plans(
                conn,
                property_id=property_id,
                source_id=result_source_id,
                state=isolated,
            )
            floor_plan_ids_by_source_ref.update(
                {(result.source_url, ref): plan_id for ref, plan_id in result_refs.items()}
            )
            scorable.extend(result_scorable)
            floor_plan_ids.extend(result_ids)
            if result.source_url == state.url:
                floor_plan_ids_by_ref = result_refs
    else:
        scorable, floor_plan_ids, floor_plan_ids_by_ref = await _upsert_floor_plans(
            conn,
            property_id=property_id,
            source_id=source_id,
            state=state,
        )
        floor_plan_ids_by_source_ref.update(
            {(source.url, ref): plan_id for ref, plan_id in floor_plan_ids_by_ref.items()}
        )
    # `floor_plan_images.producer_job_id` FKs to `jobs`, and this projection is
    # reachable from paths where the job row does not exist (replay fixtures,
    # ad-hoc reprocessing). Resolve it once, defensively, exactly as the
    # Extraction writes below already do — provenance is worth recording but
    # never worth failing the whole terminal transaction over.
    persisted_job_id = await conn.fetchval("select id from jobs where id = $1", state.job_id)

    linked_pairs: set[tuple[UUID, UUID]] = set()
    for image in state.property_images:
        property_image_id = image_ids_by_hash.get(image.content_hash)
        image_page_url = image.source_url_page or source.url
        image_source_id = await conn.fetchval(
            "select id from property_sources where property_id = $1 and url = $2",
            property_id,
            image_page_url,
        )
        if property_image_id is None or image_source_id is None:
            continue
        for ref in image.exact_floor_plan_refs:
            # Resolve the response-local ref against the map for *this image's
            # own Source*. Using the primary Source's map would let an image
            # from Source B link to a Floor Plan from Source A, breaking the
            # v1 same-Source association rule (workbook §7.2).
            floor_plan_id = floor_plan_ids_by_source_ref.get((image_page_url, ref))
            if floor_plan_id is None:
                continue
            linked_pairs.add((floor_plan_id, property_image_id))
            context = image.discovery_context
            method = (
                "source_native_id" if context.get("source_native_plan_id") else "containing_card"
            )
            current_link = await conn.fetchval(
                """
                select id from current_floor_plan_images
                where floor_plan_id = $1 and property_image_id = $2
                """,
                floor_plan_id,
                property_image_id,
            )
            if current_link is None:
                await conn.execute(
                    """
                    insert into floor_plan_images
                        (floor_plan_id, property_image_id, source_id, action,
                         association_method, confidence, evidence_context,
                         display_order, producer_job_id)
                    values ($1, $2, $3, 'link', $4, 'high', $5::jsonb, $6, $7)
                    """,
                    floor_plan_id,
                    property_image_id,
                    image_source_id,
                    method,
                    json.dumps(context),
                    image.source_page_order,
                    persisted_job_id,
                )

    # Retire associations this Source no longer asserts. Append-only: an
    # `unlink` row drops the pair out of `current_floor_plan_images` while the
    # link's history survives. Only a *complete* refresh may do this — a
    # partial or failed discovery retires nothing (§P3-SC5 lifecycle).
    if state.image_fetch_completed and refreshed_source_ids:
        stale = await conn.fetch(
            """
            select floor_plan_id, property_image_id, source_id
            from current_floor_plan_images
            where source_id = any($1::uuid[])
            """,
            refreshed_source_ids,
        )
        for row in stale:
            pair = (row["floor_plan_id"], row["property_image_id"])
            if pair in linked_pairs:
                continue
            await conn.execute(
                """
                insert into floor_plan_images
                    (floor_plan_id, property_image_id, source_id, action,
                     association_method, confidence, evidence_context,
                     producer_job_id)
                values ($1, $2, $3, 'unlink', 'containing_card', 'high',
                        '{"reason": "absent_from_complete_refresh"}'::jsonb, $4)
                """,
                row["floor_plan_id"],
                row["property_image_id"],
                row["source_id"],
                persisted_job_id,
            )
    if state.image_fetch_completed:
        unsupported_visuals = await conn.fetch(
            """
            select e.*
            from current_extractions e
            where e.property_id = $1
              and e.resolution_rule in (
                  'vision_weighted_median_exact',
                  'vision_weighted_median_gallery'
              )
              and exists (
                  select 1 from extraction_images xi
                  where xi.extraction_id = e.id
              )
              and not exists (
                  select 1
                  from extraction_images xi
                  join property_images pi on pi.id = xi.property_image_id
                  where xi.extraction_id = e.id and pi.is_current
              )
            """,
            property_id,
        )
        for prior in unsupported_visuals:
            await append_candidate_resolution(
                conn,
                property_id=property_id,
                hunt_id=prior["hunt_id"],
                criterion_key=prior["criterion_key"],
                value=None,
                confidence=Confidence.NOT_FOUND,
                evidence_quote=None,
                source_id=None,
                origin_key=f"vision_refresh:{state.job_id}",
                target_scope=TargetScope(prior["target_scope"]),
                floor_plan_id=prior["floor_plan_id"],
                applicability=(
                    UnitApplicability(prior["applicability"])
                    if prior["applicability"] is not None
                    else None
                ),
                claim_group_id=uuid4(),
                model="deterministic:image_refresh",
                job_id=persisted_job_id,
                resolution_rule="vision_image_refresh_not_found",
            )
    if state.source_results:
        page_candidates = [
            claim for result in state.source_results for claim in result.source_claims
        ]
        candidate_groups = {claim.claim_group_id for claim in page_candidates}
        page_resolutions = [
            claim
            for claim in state.resolved_claims
            if any(group_id in candidate_groups for group_id in claim.candidate_claim_group_ids)
        ]
        await persist_reconciled_claims(
            conn,
            property_id=property_id,
            hunt_id=None,
            job_id=persisted_job_id,
            candidate_claims=page_candidates,
            resolved_claims=page_resolutions,
            source_ids_by_url=source_ids_by_url,
            floor_plan_ids_by_source_ref=floor_plan_ids_by_source_ref,
            authoritative_source_urls=(
                source.url for source in state.sources if source.authoritative_extraction
            ),
        )
        non_page_claims = [
            claim for claim in state.resolved_claims if claim not in page_resolutions
        ]
        if non_page_claims:
            await persist_single_source_claims(
                conn,
                property_id=property_id,
                hunt_id=None,
                source_id=source_id,
                source_url=source.url,
                job_id=persisted_job_id,
                claims=non_page_claims,
                floor_plan_ids_by_ref=floor_plan_ids_by_ref,
                authoritative=False,
            )
    else:
        await persist_single_source_claims(
            conn,
            property_id=property_id,
            hunt_id=None,
            source_id=source_id,
            source_url=source.url,
            job_id=persisted_job_id,
            claims=[*state.source_claims, *_auxiliary_claims(state, source.url)],
            floor_plan_ids_by_ref=floor_plan_ids_by_ref,
            authoritative=source.authoritative_extraction,
        )
    hunt_id = await conn.fetchval(
        "select hunt_id from hunt_listings where id = $1", hunt_listing_id
    )
    for claim in state.custom_claims:
        claim_floor_plan_id = claim.floor_plan_id
        if claim_floor_plan_id is None and claim.floor_plan_ref is not None:
            claim_floor_plan_id = floor_plan_ids_by_source_ref.get(
                (claim.source_id or source.url, claim.floor_plan_ref)
            )
        await append_candidate_resolution(
            conn,
            property_id=property_id,
            hunt_id=hunt_id,
            criterion_key=claim.criterion_key,
            value=claim.value,
            confidence=claim.confidence,
            evidence_quote=claim.evidence_quote,
            source_id=source_ids_by_url.get(claim.source_id or ""),
            origin_key=claim.origin_key or f"custom_match:{claim.criterion_key}",
            target_scope=claim.target_scope,
            floor_plan_id=claim_floor_plan_id,
            applicability=claim.applicability,
            claim_group_id=claim.claim_group_id,
            model=claim.model,
            job_id=persisted_job_id,
            resolution_rule=claim.resolution_rule or "custom_match",
        )
    for claim in state.source_claims:
        if not claim.image_hashes or not claim.resolution_rule:
            continue
        claim_floor_plan_id = (
            floor_plan_ids_by_ref.get(claim.floor_plan_ref)
            if claim.floor_plan_ref is not None
            else claim.floor_plan_id
        )
        resolution_ids = await conn.fetch(
            """
            select id from extractions
            where job_id = $1 and property_id = $2 and record_kind = 'resolved'
              and criterion_key = $3 and target_scope = $4
              and floor_plan_id is not distinct from $5
              and resolution_rule = $6
            """,
            persisted_job_id,
            property_id,
            claim.criterion_key,
            claim.target_scope.value,
            claim_floor_plan_id,
            claim.resolution_rule,
        )
        for row in resolution_ids:
            extraction_ids = [
                row["id"],
                *[
                    candidate["candidate_extraction_id"]
                    for candidate in await conn.fetch(
                        """
                        select candidate_extraction_id
                        from extraction_resolution_candidates
                        where resolution_extraction_id = $1
                        """,
                        row["id"],
                    )
                ],
            ]
            for order, content_hash in enumerate(claim.image_hashes):
                property_image_id = image_ids_by_hash.get(content_hash)
                if property_image_id is None:
                    property_image_id = await conn.fetchval(
                        """
                        select id from property_images
                        where property_id = $1 and content_hash = $2
                        """,
                        property_id,
                        content_hash,
                    )
                if property_image_id is None:
                    continue
                for extraction_id in extraction_ids:
                    await conn.execute(
                        """
                        insert into extraction_images
                            (extraction_id, property_image_id, contribution_order)
                        values ($1, $2, $3)
                        on conflict do nothing
                        """,
                        extraction_id,
                        property_image_id,
                        order,
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

    # §9.5 blocks are facts above and also project into editable fee slots.
    mandatory = state.mandatory_fees
    if mandatory is not None and mandatory.fees:
        # Mappable fees fill their checklist slot (state `extracted`); a human
        # `manual` entry is never overwritten (§9.5). Unmapped fees still
        # compose via the extraction row above — they just lack a slot.
        for fee in mandatory.fees:
            slot = slot_for_fee(fee.name)
            if slot is None:
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
                Decimal(str(fee.amount_monthly)),
                mandatory.evidence_quote,
            )
    one_time = state.one_time_fees
    if one_time is not None and one_time.fees:
        # One-time fees fill the move-in checklist slots (§9.5) — display
        # only, never composed. `manual` entries are never overwritten.
        for fee in one_time.fees:
            slot = slot_for_one_time_fee(fee.name)
            if slot is None:
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
                Decimal(str(fee.amount)),
                one_time.evidence_quote,
            )
    if state.job_type is JobType.INGEST:
        initialized_classes = ["pricing", "listing_details"]
        if state.image_fetch_completed:
            initialized_classes.append("images")
        if state.plan is not None and "ENRICH" in state.plan.stages:
            initialized_classes.extend(_successful_refresh_fields(state, ["reviews", "location"]))
        await _mark_refresh_classes_current(
            conn,
            hunt_listing_id=hunt_listing_id,
            job_id=persisted_job_id,
            fields=initialized_classes,
        )
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
    # Plans found — clear the no-availability marker and store the display
    # plan's §9.5 composition detail for the all-in cell/drawer (P3-9).
    await conn.execute(
        """
        update hunt_listings
        set unavailable_at = null,
            all_in_components = $2::jsonb,
            move_in_components = $3::jsonb
        where id = $1
        """,
        hunt_listing_id,
        json.dumps(state.all_in_components) if state.all_in_components is not None else None,
        json.dumps(state.move_in_components) if state.move_in_components is not None else None,
    )
    # strict=True: SCORE guarantees one PlanScore per scorable plan, so any length
    # mismatch is a real filter/order drift and must surface, not truncate.
    for _plan_in, floor_plan_id, plan_score in zip(
        scorable, floor_plan_ids, state.scores, strict=True
    ):
        await conn.execute(
            """
            insert into scores
                (hunt_listing_id, floor_plan_id, total, breakdown, rubric_version,
                 all_in_components, move_in_components)
            values ($1, $2, $3, $4::jsonb, $5, $6::jsonb, $7::jsonb)
            on conflict (hunt_listing_id, floor_plan_id) do update set
                total = excluded.total,
                breakdown = excluded.breakdown,
                rubric_version = excluded.rubric_version,
                all_in_components = excluded.all_in_components,
                move_in_components = excluded.move_in_components,
                computed_at = now()
            """,
            hunt_listing_id,
            floor_plan_id,
            Decimal(str(plan_score.breakdown["total"])),
            json.dumps(plan_score.breakdown),
            rubric_version,
            json.dumps(plan_score.all_in_components)
            if plan_score.all_in_components is not None
            else None,
            json.dumps(plan_score.move_in_components)
            if plan_score.move_in_components is not None
            else None,
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
    for table in ("property_sources", "extractions", "floor_plans"):
        await conn.execute(
            f"update {table} set property_id = $2 where property_id = $1",
            placeholder_id,
            canonical_id,
        )
    # Content-addressed duplicates may already exist on both Properties. Keep the
    # canonical row/assessment, discard the placeholder duplicate, then re-point
    # the remaining images without violating the Property/hash unique index.
    #
    # Before deleting a duplicate, move its Floor Plan associations onto the
    # surviving canonical image (§P3-SC5). `floor_plan_images.property_image_id`
    # cascades on delete, so skipping this would silently strip a merged plan of
    # its diagrams. `on conflict do nothing` covers the case where both sides
    # already assert the same pair.
    await conn.execute(
        """
        update floor_plan_images incoming
        set property_image_id = canonical.id
        from property_images placeholder
        join property_images canonical
          on canonical.property_id = $2
         and canonical.content_hash = placeholder.content_hash
        where incoming.property_image_id = placeholder.id
          and placeholder.property_id = $1
          and placeholder.content_hash is not null
          and not exists (
              select 1 from floor_plan_images existing
              where existing.floor_plan_id = incoming.floor_plan_id
                and existing.property_image_id = canonical.id
          )
        """,
        placeholder_id,
        canonical_id,
    )
    await conn.execute(
        """
        delete from property_images incoming
        using property_images canonical
        where incoming.property_id = $1
          and canonical.property_id = $2
          and incoming.content_hash is not null
          and incoming.content_hash = canonical.content_hash
        """,
        placeholder_id,
        canonical_id,
    )
    await conn.execute(
        "update property_images set property_id = $2 where property_id = $1",
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
            "select id, name, canonical_address, place_id, lat, lng from properties where id <> $1",
            exclude_property_id,
        )
        return [DedupeCandidate(**dict(row)) for row in rows]

    return candidates


def make_ingest_dispatcher(
    *,
    dsn: str | None,
    fetchers_factory: FetchersFactory,
    call_structured: CallStructured | None = None,
    call_agent: CallAgent | None = None,
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
        min_vision_confidence = Confidence(settings.get("min_vision_confidence", "low"))
        cats = int(settings.get("cats", 0))
        dogs = int(settings.get("dogs", 0))
        proximity_mode = str(settings.get("proximity_mode", "driving"))
        cost_estimate_mode = str(settings.get("cost_estimate_mode", "conservative"))
        generalized_vision_policy = str(settings.get("generalized_vision_policy", "full_rubric"))
        occupants = int(settings.get("occupants", 1))

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
            # An already-known exact Source URL is stronger identity evidence
            # than a fresh placeholder, including when geocode-less DEDUPE had
            # no inputs with which to find it. Converge the Listing onto the
            # Source's existing Property; never re-parent the Source.
            source_property_id = await conn.fetchval(
                "select property_id from property_sources where url = $1",
                done_state.sources[0].url,
            )
            canonical_id: UUID = source_property_id or done_state.property_id or placeholder_id
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
            reconcile_rubric_lookup=_make_reconcile_rubric_lookup(pool),
            rubric_version=listing["rubric_version"],
            min_confidence=min_confidence,
            min_vision_confidence=min_vision_confidence,
            cats=cats,
            dogs=dogs,
            proximity_mode=proximity_mode,
            cost_estimate_mode=cost_estimate_mode,
            generalized_vision_policy=generalized_vision_policy,
            occupants=occupants,
            utility_baselines_lookup=_make_utility_baselines_lookup(pool),
            persistence=persistence,
            fresh_source_lookup=_make_fresh_source_lookup(pool),
            dedupe_candidates=_make_dedupe_candidates(pool, listing["property_id"]),
            image_store=SupabaseImageStore.from_env(),
            existing_image_hashes=_make_existing_image_hashes(pool),
            existing_image_classifications=_make_existing_image_classifications(pool),
            tool_event_sink=make_tool_event_sink(pool, job_id),
            plan_trigger="user:retry" if resumed else "user:submit",
            **({} if call_structured is None else {"call_structured": call_structured}),
            **({} if call_agent is None else {"call_agent": call_agent}),
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
            select cleaned_text_hash, cleaned_text, image_urls, last_success_at
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
            image_urls=(
                json.loads(row["image_urls"])
                if isinstance(row["image_urls"], str)
                else (row["image_urls"] or [])
            ),
            last_success_at=row["last_success_at"],
        )

    return lookup


def _policy_max_tier(source_policy: str) -> int:
    return {
        "trust_link": 0,
        "tier_1": 1,
        "tier_1_plus_official": 1,
        "tiers_1_2": 2,
        "tiers_1_2_3": 3,
    }.get(source_policy, 3)


def _make_refresh_source_lookup(pool: asyncpg.Pool) -> RefreshSourceLookup:
    """Select the submitted Source plus current contributing Sources.

    Current candidates/Floor Plans define contribution. The submitted Source is
    permanent even under `trust_link`; other Sources obey the current policy's
    tier cap. Census Syndication Families are collapsed by freshness.
    """

    async def lookup(
        hunt_listing_id: UUID | None, property_id: UUID | None, source_policy: str
    ) -> list[RefreshSource]:
        if hunt_listing_id is None or property_id is None:
            return []
        rows = await pool.fetch(
            """
            select ps.id, ps.url, ps.site_domain, ps.is_official,
                   ps.cleaned_text_hash, ps.image_urls,
                   coalesce(far.required_tier, 1) as required_tier,
                   ps.last_success_at,
                   (ps.id = hl.submitted_source_id) as submitted,
                   (
                     exists (
                       select 1 from current_extraction_candidates c
                       where c.property_id = hl.property_id and c.source_id = ps.id
                     )
                     or exists (
                       select 1 from floor_plans fp
                       where fp.property_id = hl.property_id
                         and fp.source_id = ps.id and fp.is_current
                     )
                   ) as contributing
            from hunt_listings hl
            join property_sources ps on ps.property_id = hl.property_id
            left join fetch_adapter_registry far on far.site_domain = ps.site_domain
            where hl.id = $1 and hl.property_id = $2
            order by (ps.id = hl.submitted_source_id) desc,
                     ps.last_success_at desc nulls last, ps.id
            """,
            hunt_listing_id,
            property_id,
        )
        max_tier = _policy_max_tier(source_policy)
        selected: list[RefreshSource] = []
        seen_families: set[str] = set()
        for row in rows:
            submitted = bool(row["submitted"])
            domain = str(row["site_domain"])
            metadata = source_metadata(domain, int(row["required_tier"]))
            if not submitted and source_policy == "trust_link":
                continue
            if not submitted and not row["contributing"]:
                continue
            official_carveout = bool(row["is_official"]) and source_policy == "tier_1_plus_official"
            if not submitted and metadata.census_tier > max_tier and not official_carveout:
                continue
            if not submitted and metadata.syndication_family in seen_families:
                continue
            seen_families.add(metadata.syndication_family)
            image_urls = row["image_urls"]
            if isinstance(image_urls, str):
                image_urls = json.loads(image_urls)
            selected.append(
                RefreshSource(
                    source_id=row["id"],
                    url=row["url"],
                    cleaned_text_hash=row["cleaned_text_hash"],
                    required_tier=metadata.census_tier,
                    image_urls=image_urls or [],
                )
            )
        return selected

    return lookup


def _make_utility_baselines_lookup(pool: asyncpg.Pool):  # type: ignore[no-untyped-def]
    """SCORE's §9.5 baselines seam: BaselineSet for one locality + beds bucket."""

    async def lookup(city: str | None, state: str | None, county: str | None, bucket: int):
        from manzil_worker.enrich.utility_baselines import baselines_for_property_locality

        async with pool.acquire() as conn:
            return await baselines_for_property_locality(
                conn, city=city, state=state, county=county, bucket=bucket
            )

    return lookup


def _make_existing_image_hashes(pool: asyncpg.Pool):  # type: ignore[no-untyped-def]
    """IMAGE_FETCH's dumb DB seam: the currently stored content-hash set."""

    async def lookup(property_id: UUID) -> set[str]:
        rows = await pool.fetch(
            "select content_hash from property_images where property_id = $1",
            property_id,
        )
        return {row["content_hash"] for row in rows if row["content_hash"]}

    return lookup


def _make_existing_image_classifications(pool: asyncpg.Pool):  # type: ignore[no-untyped-def]
    async def lookup(property_id: UUID) -> dict[str, dict[str, Any]]:
        rows = await pool.fetch(
            """
            select content_hash, vision_assessment
            from property_images
            where property_id = $1 and is_current
              and vision_assessment ? 'classification'
            """,
            property_id,
        )
        return {
            row["content_hash"]: (
                json.loads(row["vision_assessment"])
                if isinstance(row["vision_assessment"], str)
                else row["vision_assessment"]
            )
            for row in rows
            if row["content_hash"] and row["vision_assessment"]
        }

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
        min_vision_confidence = Confidence(settings.get("min_vision_confidence", "low"))
        cats = int(settings.get("cats", 0))
        dogs = int(settings.get("dogs", 0))
        cost_estimate_mode = str(settings.get("cost_estimate_mode", "conservative"))
        generalized_vision_policy = str(settings.get("generalized_vision_policy", "full_rubric"))
        occupants = int(settings.get("occupants", 1))

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
                    min_vision_confidence=min_vision_confidence,
                    cats=cats,
                    dogs=dogs,
                    cost_estimate_mode=cost_estimate_mode,
                    generalized_vision_policy=generalized_vision_policy,
                    occupants=occupants,
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


def make_enrich_refresh_dispatcher(
    *,
    nearby_places: NearbyPlaces | None = None,
    commute_minutes: CommuteMinutes | None = None,
) -> Dispatcher:
    """Build the `refresh` handler — P3-8 interim, `payload.scope == "enrich"`
    only (P3-12's planner-driven refresh subsumes this). Re-derives the Maps-only
    location criteria (`grocery_proximity`) for every active listing at the
    hunt's current `proximity_mode`, then rescores the hunt. Zero LLM spend by
    construction: geocodes ride the properties forever-cache and the review
    synthesis is not on this path. Seams injectable for tests; defaults live."""

    async def dispatch(pool: asyncpg.Pool, job: asyncpg.Record) -> None:
        from manzil_worker.enrich.maps import MapsError, geocode_property
        from manzil_worker.stages.base import _live_commute_minutes, _live_nearby_places
        from manzil_worker.stages.enrich import grocery_extraction, nearest_grocery_minutes

        nearby = nearby_places or _live_nearby_places
        commute = commute_minutes or _live_commute_minutes

        job_id: UUID = job["id"]
        payload = json.loads(job["payload"])
        scope = payload.get("scope")
        if scope != "enrich":
            await _mark_failed(
                pool, job_id, f"refresh: unsupported scope {scope!r} (full refresh lands P3-12)"
            )
            return
        hunt_id_raw = payload.get("hunt_id")
        if hunt_id_raw is None:
            await _mark_failed(pool, job_id, "refresh: payload missing hunt_id")
            return
        hunt_id = UUID(hunt_id_raw)

        async with pool.acquire() as conn:
            hunt = await conn.fetchrow(
                "select settings, rubric_version from hunts where id = $1",
                hunt_id,
            )
            if hunt is None:
                await _mark_failed(pool, job_id, f"refresh: hunt {hunt_id} not found")
                return
            rubric = await _load_rubric(conn, hunt_id)

        settings = json.loads(hunt["settings"]) if hunt["settings"] else {}
        proximity_mode = str(settings.get("proximity_mode", "driving"))
        min_confidence = Confidence(settings.get("min_confidence", "medium"))
        min_vision_confidence = Confidence(settings.get("min_vision_confidence", "low"))
        cats = int(settings.get("cats", 0))
        dogs = int(settings.get("dogs", 0))
        cost_estimate_mode = str(settings.get("cost_estimate_mode", "conservative"))
        generalized_vision_policy = str(settings.get("generalized_vision_policy", "full_rubric"))
        occupants = int(settings.get("occupants", 1))

        try:
            async with pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    """
                    insert into job_events (job_id, stage, event, detail)
                    values ($1, 'refresh', 'started', $2::jsonb)
                    """,
                    job_id,
                    json.dumps({"scope": "enrich", "proximity_mode": proximity_mode}),
                )
                listings = await conn.fetch(
                    """
                    select id, property_id from hunt_listings
                    where hunt_id = $1 and status = 'active'
                    """,
                    hunt_id,
                )
                enriched = 0
                for listing in listings:
                    property_id: UUID = listing["property_id"]
                    try:
                        _, lat, lng = await geocode_property(conn, property_id)
                        found = await nearest_grocery_minutes(
                            lat,
                            lng,
                            proximity_mode,
                            nearby_places=nearby,
                            commute_minutes=commute,
                        )
                    except MapsError as error:
                        log.warning(
                            "enrich_refresh_property_skipped",
                            job_id=str(job_id),
                            property_id=str(property_id),
                            error=str(error),
                        )
                        continue
                    if found is None:
                        continue
                    minutes, place_name = found
                    ext = grocery_extraction(minutes, place_name, proximity_mode)
                    await append_candidate_resolution(
                        conn,
                        property_id=property_id,
                        hunt_id=None,
                        criterion_key=ext.criterion_key,
                        value=ext.value,
                        confidence=ext.confidence,
                        evidence_quote=ext.evidence_quote,
                        source_id=None,
                        origin_key="google_maps:grocery",
                        target_scope=TargetScope.PROPERTY,
                        floor_plan_id=None,
                        applicability=None,
                        claim_group_id=ext.claim_group_id,
                        model=ext.model,
                        job_id=job_id,
                    )
                    enriched += 1
                await rescore_hunt(
                    conn,
                    hunt_id=hunt_id,
                    rubric=rubric,
                    rubric_version=hunt["rubric_version"],
                    min_confidence=min_confidence,
                    min_vision_confidence=min_vision_confidence,
                    cats=cats,
                    dogs=dogs,
                    cost_estimate_mode=cost_estimate_mode,
                    generalized_vision_policy=generalized_vision_policy,
                    occupants=occupants,
                )
                await conn.execute(
                    """
                    update jobs set
                        state = 'done',
                        finished_at = now(),
                        locked_by = null,
                        locked_at = null,
                        current_stage = 'refresh'
                    where id = $1
                    """,
                    job_id,
                )
                await conn.execute(
                    """
                    insert into job_events (job_id, stage, event, detail)
                    values ($1, 'refresh', 'completed', $2::jsonb)
                    """,
                    job_id,
                    json.dumps({"enriched": enriched, "listings": len(listings)}),
                )
        except Exception as error:
            log.error("enrich_refresh_failed", job_id=str(job_id), error=str(error))
            await _mark_failed(pool, job_id, f"refresh: {error}")
            return
        log.info("enrich_refresh_done", job_id=str(job_id), hunt_id=str(hunt_id))

    return dispatch


def make_discover_refresh_dispatcher(
    *,
    dsn: str | None,
    fetchers_factory: FetchersFactory,
    call_structured: CallStructured | None = None,
    call_agent: CallAgent | None = None,
) -> Dispatcher:
    """Run only DISCOVER after a Listing's Source Policy is relaxed (P3-5).

    The submitted Source is already durable, so this refresh neither refetches
    nor re-extracts it. The one-stage manifest still uses the ordinary runner
    and PostgresPersistence contract: state/tool events, cost, and the terminal
    link projection are durable and resumable exactly like ingest.
    """

    async def dispatch(pool: asyncpg.Pool, job: asyncpg.Record) -> None:
        job_id: UUID = job["id"]
        payload = json.loads(job["payload"])
        if payload.get("scope") != "discover":
            await _mark_failed(pool, job_id, "refresh: expected scope 'discover'")
            return
        if job["hunt_listing_id"] is None:
            await _mark_failed(pool, job_id, "refresh: discover job has no hunt_listing_id")
            return
        submitted_url = payload.get("url")
        if not isinstance(submitted_url, str) or not submitted_url:
            await _mark_failed(pool, job_id, "refresh: discover payload missing url")
            return

        async with pool.acquire() as conn:
            listing = await conn.fetchrow(
                """
                select hl.property_id, hl.hunt_id, hl.source_policy,
                       p.name, p.canonical_address, p.official_url
                from hunt_listings hl
                join properties p on p.id = hl.property_id
                where hl.id = $1
                """,
                job["hunt_listing_id"],
            )
        if listing is None:
            await _mark_failed(pool, job_id, "refresh: hunt_listing not found")
            return

        source_policy = str(listing["source_policy"])
        state = _build_run_state(job)
        state.property_id = listing["property_id"]
        state.source_policy = source_policy
        state.property_identity = PropertyIdentityIn(
            name=listing["name"],
            address=listing["canonical_address"],
            official_url=listing["official_url"],
        )
        state.plan = PlanManifest(
            job_type=JobType.REFRESH.value,
            trigger="user:source_policy",
            source_policy=source_policy,
            sources=[PlanSource(url=submitted_url, action="skip", why="existing_source")],
            stages=["DISCOVER"],
            skipped={},
            est_cost_usd=0.04,
        )

        async def project(conn: asyncpg.Connection, done_state: RunState) -> None:
            await _persist_discovery_results(
                conn,
                hunt_listing_id=job["hunt_listing_id"],
                property_id=listing["property_id"],
                submitted_url=submitted_url,
                state=done_state,
            )

        persistence = PostgresPersistence(
            pool,
            job_id,
            ["DISCOVER"],
            start_cursor=state.cursor,
            on_done=project,
        )
        registry = PostgresRegistry(dsn) if dsn else InMemoryRegistry()
        ctx = StageCtx(
            fetchers=fetchers_factory(),
            registry=registry,
            persistence=persistence,
            tool_event_sink=make_tool_event_sink(pool, job_id),
            **({} if call_structured is None else {"call_structured": call_structured}),
            **({} if call_agent is None else {"call_agent": call_agent}),
        )
        await run_job(state, ctx)

    return dispatch


async def _mark_refresh_classes_current(
    conn: asyncpg.Connection,
    *,
    hunt_listing_id: UUID,
    job_id: UUID,
    fields: list[str],
) -> None:
    classes = set(fields)
    # A complete page check uses the full Catalog whenever bytes changed, so
    # either text class proves both text classes current.
    if classes & {"pricing", "listing_details", "images"}:
        classes.update({"pricing", "listing_details"})
    for refresh_class in sorted(classes):
        await conn.execute(
            """
            insert into hunt_listing_refresh_status
                (hunt_listing_id, refresh_class, last_success_at, producer_job_id)
            values ($1, $2, now(), $3)
            on conflict (hunt_listing_id, refresh_class) do update set
                last_success_at = excluded.last_success_at,
                producer_job_id = excluded.producer_job_id
            """,
            hunt_listing_id,
            refresh_class,
            job_id,
        )


def _successful_refresh_fields(state: RunState, fields: list[str]) -> list[str]:
    failed_codes = {warning.code for warning in state.warnings if warning.stage == "ENRICH"}
    failed_classes: set[str] = set()
    if "enrich_no_geocode" in failed_codes:
        failed_classes.update({"location", "reviews"})
    if "location_refresh_failed" in failed_codes:
        failed_classes.add("location")
    if "reviews_refresh_failed" in failed_codes:
        failed_classes.add("reviews")
    return [field for field in fields if field not in failed_classes]


async def _persist_unchanged_text_refresh(
    conn: asyncpg.Connection,
    *,
    hunt_listing_id: UUID,
    property_id: UUID,
    job_id: UUID,
    state: RunState,
) -> None:
    for source in state.sources:
        await conn.execute(
            """
            update property_sources set
                cleaned_text_hash = $3,
                cleaned_text = $4,
                image_urls = $5::jsonb,
                last_fetched_at = $6,
                last_success_at = $6
            where property_id = $1 and url = $2
            """,
            property_id,
            source.url,
            source.cleaned_hash,
            source.cleaned_text,
            json.dumps(source.image_urls),
            source.fetched_at,
        )
    await _mark_refresh_classes_current(
        conn,
        hunt_listing_id=hunt_listing_id,
        job_id=job_id,
        fields=_successful_refresh_fields(state, state.refresh_fields),
    )


async def _persist_enrich_only_refresh(
    conn: asyncpg.Connection,
    *,
    hunt_listing_id: UUID,
    property_id: UUID,
    job_id: UUID,
    state: RunState,
    rubric: list[RubricCriterion],
    rubric_version: int,
    settings: dict[str, Any],
) -> None:
    for claim in state.source_claims:
        await append_candidate_resolution(
            conn,
            property_id=property_id,
            hunt_id=None,
            criterion_key=claim.criterion_key,
            value=claim.value,
            confidence=claim.confidence,
            evidence_quote=claim.evidence_quote,
            source_id=None,
            origin_key=claim.source_id or f"refresh:{claim.criterion_key}",
            target_scope=claim.target_scope,
            floor_plan_id=claim.floor_plan_id,
            applicability=claim.applicability,
            claim_group_id=claim.claim_group_id,
            model=claim.model,
            job_id=job_id,
            resolution_rule="single_source",
        )
    submitted_source_id = await conn.fetchval(
        "select submitted_source_id from hunt_listings where id = $1",
        hunt_listing_id,
    )
    if submitted_source_id is not None:
        await _persist_property_contacts(
            conn,
            property_id=property_id,
            source_id=submitted_source_id,
            source_is_official=False,
            state=state,
        )
    await rescore_hunt(
        conn,
        hunt_id=UUID(
            str(
                await conn.fetchval(
                    "select hunt_id from hunt_listings where id = $1", hunt_listing_id
                )
            )
        ),
        rubric=rubric,
        rubric_version=rubric_version,
        min_confidence=Confidence(settings.get("min_confidence", "medium")),
        min_vision_confidence=Confidence(settings.get("min_vision_confidence", "low")),
        cats=int(settings.get("cats", 0)),
        dogs=int(settings.get("dogs", 0)),
        cost_estimate_mode=str(settings.get("cost_estimate_mode", "conservative")),
        generalized_vision_policy=str(settings.get("generalized_vision_policy", "full_rubric")),
        occupants=int(settings.get("occupants", 1)),
    )
    await _mark_refresh_classes_current(
        conn,
        hunt_listing_id=hunt_listing_id,
        job_id=job_id,
        fields=_successful_refresh_fields(state, state.refresh_fields),
    )


async def _persist_custom_only_refresh(
    conn: asyncpg.Connection,
    *,
    hunt_listing_id: UUID,
    property_id: UUID,
    job_id: UUID,
    state: RunState,
    rubric: list[RubricCriterion],
    rubric_version: int,
    settings: dict[str, Any],
) -> None:
    hunt_id = await conn.fetchval(
        "select hunt_id from hunt_listings where id = $1", hunt_listing_id
    )
    source_ids = {
        row["url"]: row["id"]
        for row in await conn.fetch(
            "select id, url from property_sources where property_id = $1", property_id
        )
    }
    floor_plan_ids = {
        (row["url"], str(row["id"])): row["id"]
        for row in await conn.fetch(
            """
            select fp.id, ps.url
            from floor_plans fp
            join property_sources ps on ps.id = fp.source_id
            where fp.property_id = $1 and fp.is_current
            """,
            property_id,
        )
    }
    for claim in state.custom_claims:
        floor_plan_id = claim.floor_plan_id
        if floor_plan_id is None and claim.floor_plan_ref is not None:
            floor_plan_id = floor_plan_ids.get(
                (claim.source_id or state.url, claim.floor_plan_ref)
            )
        await append_candidate_resolution(
            conn,
            property_id=property_id,
            hunt_id=hunt_id,
            criterion_key=claim.criterion_key,
            value=claim.value,
            confidence=claim.confidence,
            evidence_quote=claim.evidence_quote,
            source_id=source_ids.get(claim.source_id or ""),
            origin_key=claim.origin_key or f"custom_match:{claim.criterion_key}",
            target_scope=claim.target_scope,
            floor_plan_id=floor_plan_id,
            applicability=claim.applicability,
            claim_group_id=claim.claim_group_id,
            model=claim.model,
            job_id=job_id,
            resolution_rule=claim.resolution_rule or "custom_match",
        )
    await rescore_hunt(
        conn,
        hunt_id=hunt_id,
        rubric=rubric,
        rubric_version=rubric_version,
        min_confidence=Confidence(settings.get("min_confidence", "medium")),
        min_vision_confidence=Confidence(settings.get("min_vision_confidence", "low")),
        cats=int(settings.get("cats", 0)),
        dogs=int(settings.get("dogs", 0)),
        cost_estimate_mode=str(settings.get("cost_estimate_mode", "conservative")),
        generalized_vision_policy=str(settings.get("generalized_vision_policy", "full_rubric")),
        occupants=int(settings.get("occupants", 1)),
    )


def make_class_refresh_dispatcher(
    *,
    dsn: str | None,
    fetchers_factory: FetchersFactory,
    call_structured: CallStructured | None = None,
    call_agent: CallAgent | None = None,
) -> Dispatcher:
    """P3-12 planner-driven Listing refresh."""

    async def dispatch(pool: asyncpg.Pool, job: asyncpg.Record) -> None:
        job_id: UUID = job["id"]
        if job["hunt_listing_id"] is None:
            await _mark_failed(pool, job_id, "refresh: job has no hunt_listing_id")
            return
        payload = json.loads(job["payload"])
        fields = payload.get("fields")
        custom_scope = payload.get("scope") == "custom_match"
        custom_keys = payload.get("custom_criterion_keys")
        if not custom_scope and (
            payload.get("scope") != "classes" or not isinstance(fields, list) or not fields
        ):
            await _mark_failed(pool, job_id, "refresh: invalid class scope")
            return
        if custom_scope and (
            not isinstance(custom_keys, list)
            or not custom_keys
            or not all(isinstance(key, str) for key in custom_keys)
        ):
            await _mark_failed(pool, job_id, "refresh: invalid custom_match scope")
            return
        async with pool.acquire() as conn:
            listing = await conn.fetchrow(
                """
                select hl.property_id, hl.hunt_id, hl.source_policy,
                       h.settings, h.rubric_version,
                       p.name, p.canonical_address, p.official_url,
                       p.place_id, p.lat, p.lng, p.city, p.state, p.county
                from hunt_listings hl
                join hunts h on h.id = hl.hunt_id
                join properties p on p.id = hl.property_id
                where hl.id = $1 and hl.status = 'active'
                """,
                job["hunt_listing_id"],
            )
            if listing is None:
                await _mark_failed(pool, job_id, "refresh: active Listing not found")
                return
            rubric = await _load_rubric(conn, listing["hunt_id"])
            cached_sources = []
            cached_plans = []
            if custom_scope:
                cached_sources = await conn.fetch(
                    """
                    select url, cleaned_text, cleaned_text_hash, image_urls
                    from property_sources
                    where property_id = $1 and last_success_at is not null
                    order by last_success_at desc
                    """,
                    listing["property_id"],
                )
                cached_plans = await conn.fetch(
                    """
                    select fp.*, ps.url as source_url
                    from floor_plans fp join property_sources ps on ps.id = fp.source_id
                    where fp.property_id = $1 and fp.is_current
                    order by fp.first_seen_at, fp.id
                    """,
                    listing["property_id"],
                )
        settings = json.loads(listing["settings"]) if listing["settings"] else {}
        resumed = payload.get("run_state") is not None
        state = _build_run_state(job)
        state.property_id = state.property_id or listing["property_id"]
        state.source_policy = str(listing["source_policy"])
        state.refresh_fields = (
            [] if custom_scope else list(dict.fromkeys(str(field) for field in fields))
        )
        state.custom_criterion_keys = list(custom_keys or [])
        if custom_scope and not resumed:
            state.sources = [
                SourceState(
                    url=row["url"],
                    cleaned_text=row["cleaned_text"] or "",
                    cleaned_hash=row["cleaned_text_hash"] or "",
                    image_urls=list(
                        json.loads(row["image_urls"])
                        if isinstance(row["image_urls"], str)
                        else (row["image_urls"] or [])
                    ),
                )
                for row in cached_sources
            ]
            state.floor_plans = [
                FloorPlanIn(
                    response_key=str(row["id"]),
                    source_url=row["source_url"],
                    source_native_id=row["source_native_id"],
                    detail_url=row["detail_url"],
                    plan_name=row["plan_name"],
                    beds=row["beds"],
                    baths=float(row["baths"]) if row["baths"] is not None else None,
                    unit_types=list(
                        json.loads(row["unit_types"])
                        if isinstance(row["unit_types"], str)
                        else (row["unit_types"] or [])
                    ),
                    sqft_min=row["sqft_min"],
                    sqft_max=row["sqft_max"],
                    rent_min=float(row["rent_min"]) if row["rent_min"] is not None else None,
                    rent_max=float(row["rent_max"]) if row["rent_max"] is not None else None,
                    deposit=float(row["deposit"]) if row["deposit"] is not None else None,
                    availability_date=(
                        row["availability_date"].isoformat()
                        if row["availability_date"] is not None
                        else None
                    ),
                )
                for row in cached_plans
            ]
            state.property_identity = PropertyIdentityIn(
                name=listing["name"],
                address=listing["canonical_address"],
                official_url=listing["official_url"],
            )
        if state.geocode is None and listing["place_id"] and listing["lat"] is not None:
            state.geocode = GeocodeIn(
                place_id=listing["place_id"],
                lat=float(listing["lat"]),
                lng=float(listing["lng"]),
                city=listing["city"],
                state=listing["state"],
                county=listing["county"],
            )

        enrich_only = set(state.refresh_fields) <= {"reviews", "location"}

        async def project(conn: asyncpg.Connection, done_state: RunState) -> None:
            if custom_scope:
                await _persist_custom_only_refresh(
                    conn,
                    hunt_listing_id=job["hunt_listing_id"],
                    property_id=listing["property_id"],
                    job_id=job_id,
                    state=done_state,
                    rubric=rubric,
                    rubric_version=listing["rubric_version"],
                    settings=settings,
                )
                return
            if enrich_only:
                await _persist_enrich_only_refresh(
                    conn,
                    hunt_listing_id=job["hunt_listing_id"],
                    property_id=listing["property_id"],
                    job_id=job_id,
                    state=done_state,
                    rubric=rubric,
                    rubric_version=listing["rubric_version"],
                    settings=settings,
                )
                return
            unchanged_text_only = (
                set(done_state.refresh_fields) <= {"pricing", "listing_details"}
                and done_state.sources
                and all(source.content_changed is False for source in done_state.sources)
            )
            if unchanged_text_only:
                await _persist_unchanged_text_refresh(
                    conn,
                    hunt_listing_id=job["hunt_listing_id"],
                    property_id=listing["property_id"],
                    job_id=job_id,
                    state=done_state,
                )
                return
            await _persist_ingest_results(
                conn,
                hunt_listing_id=job["hunt_listing_id"],
                property_id=listing["property_id"],
                rubric_version=listing["rubric_version"],
                state=done_state,
            )
            await _mark_refresh_classes_current(
                conn,
                hunt_listing_id=job["hunt_listing_id"],
                job_id=job_id,
                fields=_successful_refresh_fields(done_state, done_state.refresh_fields),
            )

        stage_names = list(state.plan.stages) if state.plan is not None else REFRESH_STAGE_NAMES
        persistence = PostgresPersistence(
            pool, job_id, stage_names, start_cursor=state.cursor, on_done=project
        )
        registry = PostgresRegistry(dsn) if dsn else InMemoryRegistry()
        ctx = StageCtx(
            fetchers=fetchers_factory(),
            registry=registry,
            rubric=rubric,
            reconcile_rubric_lookup=_make_reconcile_rubric_lookup(pool),
            rubric_version=listing["rubric_version"],
            min_confidence=Confidence(settings.get("min_confidence", "medium")),
            min_vision_confidence=Confidence(settings.get("min_vision_confidence", "low")),
            cats=int(settings.get("cats", 0)),
            dogs=int(settings.get("dogs", 0)),
            proximity_mode=str(settings.get("proximity_mode", "driving")),
            cost_estimate_mode=str(settings.get("cost_estimate_mode", "conservative")),
            generalized_vision_policy=str(settings.get("generalized_vision_policy", "full_rubric")),
            occupants=int(settings.get("occupants", 1)),
            utility_baselines_lookup=_make_utility_baselines_lookup(pool),
            persistence=persistence,
            refresh_source_lookup=_make_refresh_source_lookup(pool),
            image_store=SupabaseImageStore.from_env(),
            existing_image_hashes=_make_existing_image_hashes(pool),
            existing_image_classifications=_make_existing_image_classifications(pool),
            tool_event_sink=make_tool_event_sink(pool, job_id),
            plan_trigger=(
                "user:retry" if resumed else str(payload.get("trigger") or "user:refresh")
            ),
            **({} if call_structured is None else {"call_structured": call_structured}),
            **({} if call_agent is None else {"call_agent": call_agent}),
        )
        await run_job(state, ctx, REFRESH_STAGES)

    return dispatch


def make_refresh_dispatcher(
    *,
    dsn: str | None,
    fetchers_factory: FetchersFactory,
    call_structured: CallStructured | None = None,
    call_agent: CallAgent | None = None,
) -> Dispatcher:
    """Route the refresh scopes that have landed before P3-12's full planner."""
    enrich = make_enrich_refresh_dispatcher()
    discover = make_discover_refresh_dispatcher(
        dsn=dsn,
        fetchers_factory=fetchers_factory,
        call_structured=call_structured,
        call_agent=call_agent,
    )
    classes = make_class_refresh_dispatcher(
        dsn=dsn,
        fetchers_factory=fetchers_factory,
        call_structured=call_structured,
        call_agent=call_agent,
    )

    async def dispatch(pool: asyncpg.Pool, job: asyncpg.Record) -> None:
        payload = json.loads(job["payload"])
        if payload.get("scope") in {"classes", "custom_match"}:
            await classes(pool, job)
        elif payload.get("scope") == "discover":
            await discover(pool, job)
        else:
            await enrich(pool, job)

    return dispatch


def build_dispatch(
    pool: asyncpg.Pool,
    *,
    dsn: str | None = None,
    fetchers_factory: FetchersFactory | None = None,
    call_structured: CallStructured | None = None,
    call_agent: CallAgent | None = None,
) -> dict[JobType, Dispatcher]:
    """The `job_type -> dispatcher` table. `ingest` and `rescore` (P1-6).
    `dsn` (when given) backs the per-domain adapter registry."""
    dsn = dsn or os.environ.get("DATABASE_URL")
    return {
        JobType.INGEST: make_ingest_dispatcher(
            dsn=dsn,
            fetchers_factory=fetchers_factory or _default_fetchers,
            call_structured=call_structured,
            call_agent=call_agent,
        ),
        JobType.RESCORE: make_rescore_dispatcher(),
        JobType.REFRESH: make_refresh_dispatcher(
            dsn=dsn,
            fetchers_factory=fetchers_factory or _default_fetchers,
            call_structured=call_structured,
            call_agent=call_agent,
        ),
    }


# ── the loop ─────────────────────────────────────────────────────────────────


# In-flight regional passes (and their task handles, so they aren't GC'd): the
# in-process guard; the Postgres advisory lock below is the cross-process one.
_BASELINE_TASKS: dict[str, asyncio.Task[None]] = {}
# Attempt cooldown: a region stays due until its pass WRITES (all-or-nothing), so
# without this a persistently failing pass would fire one live LLM call per
# tick. Monotonic-clock timestamps of the last attempt, success or not.
_BASELINE_LAST_ATTEMPT: dict[str, float] = {}


async def _enqueue_rescores_for_region(conn: Any, region) -> None:
    if region.geo_level == "city":
        await conn.execute(
            """
            insert into jobs (hunt_id, type, state, payload)
            select distinct hl.hunt_id, 'rescore'::job_type, 'queued'::job_state,
                   jsonb_build_object('hunt_id', hl.hunt_id)
            from hunt_listings hl
            join properties p on p.id = hl.property_id
            where hl.status = 'active' and p.city = $1 and p.state = $2
            """,
            region.region_name,
            region.state,
        )
    elif region.geo_level == "county":
        await conn.execute(
            """
            insert into jobs (hunt_id, type, state, payload)
            select distinct hl.hunt_id, 'rescore'::job_type, 'queued'::job_state,
                   jsonb_build_object('hunt_id', hl.hunt_id)
            from hunt_listings hl
            join properties p on p.id = hl.property_id
            where hl.status = 'active'
              and p.city is null and p.county = $1 and p.state = $2
            """,
            region.region_name,
            region.state,
        )
    else:
        await conn.execute(
            """
            insert into jobs (hunt_id, type, state, payload)
            select distinct hl.hunt_id, 'rescore'::job_type, 'queued'::job_state,
                   jsonb_build_object('hunt_id', hl.hunt_id)
            from hunt_listings hl
            join properties p on p.id = hl.property_id
            where hl.status = 'active'
              and p.city is null and p.county is null and p.state = $1
            """,
            region.state,
        )


async def _run_region_baselines(pool: asyncpg.Pool, region) -> None:
    from manzil_worker.enrich.utility_baselines import refresh_region_baselines

    try:
        async with pool.acquire() as conn:
            locked = await conn.fetchval(
                "select pg_try_advisory_lock(hashtext($1))", region.lock_key()
            )
            if not locked:
                return
            try:
                await refresh_region_baselines(conn, region)
                await _enqueue_rescores_for_region(conn, region)
            finally:
                await conn.fetchval("select pg_advisory_unlock(hashtext($1))", region.lock_key())
    except Exception as error:
        log.warning(
            "utility_baselines_failed",
            geo_level=region.geo_level,
            state=region.state,
            region_name=region.region_name,
            error=str(error),
        )


async def utility_baselines_tick(pool: asyncpg.Pool) -> None:
    """The first scheduler duty (P3-9): one guarded asyncio task per due region."""
    from manzil_worker.enrich.utility_baselines import due_baseline_regions

    async with pool.acquire() as conn:
        regions = await due_baseline_regions(conn)
    now = asyncio.get_running_loop().time()
    for region in regions:
        key = region.lock_key()
        if key in _BASELINE_TASKS:
            continue
        last = _BASELINE_LAST_ATTEMPT.get(key)
        if last is not None and now - last < UTILITY_BASELINE_RETRY_SECONDS:
            continue
        _BASELINE_LAST_ATTEMPT[key] = now
        task = asyncio.create_task(_run_region_baselines(pool, region))
        _BASELINE_TASKS[key] = task
        task.add_done_callback(lambda _t, k=key: _BASELINE_TASKS.pop(k, None))


async def checkpoint_timeout_tick(pool: asyncpg.Pool) -> None:
    """Apply declared defaults to checkpoints that have waited 24 hours.

    The pre-default snapshot is retained on the original Job so a later human
    answer can create a correction Job from the same durable Stage boundary.
    The completed Job itself is never rewound or rewritten into a new history.
    """
    async with pool.acquire() as conn, conn.transaction():
        locked = await conn.fetchval(
            "select pg_try_advisory_xact_lock(hashtext('manzil:p3-11:checkpoint-timeout'))"
        )
        if not locked:
            return
        rows = await conn.fetch(
            """
            select j.id, j.current_stage, j.payload
            from jobs j
            join lateral (
                select max(e.at) as asked_at
                from job_events e
                where e.job_id = j.id and e.event = 'checkpoint_asked'
            ) asked on asked.asked_at is not null
            where j.state = 'waiting_user'
              and asked.asked_at <= now() - make_interval(hours => $1)
            order by asked.asked_at, j.id
            for update of j skip locked
            """,
            CHECKPOINT_TIMEOUT_HOURS,
        )
        for row in rows:
            payload = row["payload"]
            payload = json.loads(payload) if isinstance(payload, str) else dict(payload or {})
            run_state = payload.get("run_state")
            if not isinstance(run_state, dict):
                continue
            prompt = run_state.get("checkpoint")
            if not isinstance(prompt, dict):
                continue
            default = prompt.get("default")
            options = prompt.get("options")
            if (
                not isinstance(default, str)
                or not isinstance(options, list)
                or default not in options
            ):
                log.warning(
                    "checkpoint_timeout_invalid_prompt",
                    job_id=str(row["id"]),
                    default=default,
                )
                continue

            resolved_at = datetime.now(UTC).isoformat()
            snapshot = json.loads(json.dumps(run_state))
            answer = {"choice": default, "context_ref": prompt.get("context_ref")}
            payload["auto_resolved_checkpoint"] = {
                "prompt": prompt,
                "answer": answer,
                "resolved_at": resolved_at,
                "snapshot": snapshot,
            }
            payload["checkpoint_answer"] = answer
            run_state["status"] = "running"
            run_state["checkpoint"] = None
            payload["run_state"] = run_state

            await conn.execute(
                """
                update jobs set
                    state = 'queued',
                    payload = $2::jsonb,
                    locked_by = null,
                    locked_at = null,
                    finished_at = null
                where id = $1
                """,
                row["id"],
                json.dumps(payload),
            )
            await conn.execute(
                """
                insert into job_events (job_id, stage, event, detail)
                values ($1, $2, 'checkpoint_auto_resolved', $3::jsonb)
                """,
                row["id"],
                row["current_stage"] or prompt.get("kind") or "checkpoint",
                json.dumps(
                    {
                        "answer": {"choice": default},
                        "kind": prompt.get("kind"),
                        "question": prompt.get("question"),
                    }
                ),
            )


async def refresh_ttl_tick(pool: asyncpg.Pool) -> None:
    """Enqueue one class-combined refresh per due active Listing."""
    async with pool.acquire() as conn, conn.transaction():
        locked = await conn.fetchval(
            "select pg_try_advisory_xact_lock(hashtext('manzil:p3-12:ttl-refresh'))"
        )
        if not locked:
            return
        rows = await conn.fetch(
            """
            select hl.id, hl.hunt_id, ps.url,
                   coalesce(
                     jsonb_object_agg(
                       hrs.refresh_class, hrs.last_success_at
                     ) filter (where hrs.refresh_class is not null),
                     '{}'::jsonb
                   ) as freshness,
                   exists (
                     select 1 from rubric_criteria rc
                     join criteria_catalog cc on cc.key = rc.catalog_key
                     where rc.hunt_id = hl.hunt_id and rc.enabled
                       and cc.refresh_class = 'images'
                   ) as needs_images,
                   exists (
                     select 1 from rubric_criteria rc
                     join criteria_catalog cc on cc.key = rc.catalog_key
                     where rc.hunt_id = hl.hunt_id and rc.enabled
                       and cc.refresh_class = 'reviews'
                   ) as needs_reviews
            from hunt_listings hl
            join property_sources ps on ps.id = hl.submitted_source_id
            left join hunt_listing_refresh_status hrs on hrs.hunt_listing_id = hl.id
            where hl.status = 'active'
              and not exists (
                select 1 from jobs j
                where j.hunt_listing_id = hl.id
                  and j.state in ('queued', 'running', 'waiting_user')
                  and j.type in ('ingest', 'refresh')
              )
            group by hl.id, hl.hunt_id, ps.url
            order by hl.created_at
            """
        )
        now = datetime.now(UTC)
        for row in rows:
            raw = row["freshness"]
            freshness = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            relevant = ["pricing", "listing_details"]
            if row["needs_images"]:
                relevant.append("images")
            if row["needs_reviews"]:
                relevant.append("reviews")
            due = []
            for refresh_class in relevant:
                last = freshness.get(refresh_class)
                if isinstance(last, str):
                    last = datetime.fromisoformat(last.replace("Z", "+00:00"))
                ttl = timedelta(hours=REFRESH_TTL_HOURS[refresh_class])
                if last is None or last <= now - ttl:
                    due.append(refresh_class)
            if not due:
                continue
            await conn.execute(
                """
                insert into jobs
                    (hunt_id, hunt_listing_id, type, state, payload)
                values ($1, $2, 'refresh', 'queued', $3::jsonb)
                """,
                row["hunt_id"],
                row["id"],
                json.dumps(
                    {
                        "url": row["url"],
                        "scope": "classes",
                        "fields": due,
                        "trigger": f"ttl:{','.join(due)}",
                        "hunt_id": str(row["hunt_id"]),
                        "listing_id": str(row["id"]),
                    }
                ),
            )


async def scheduler_tick(pool: asyncpg.Pool) -> None:
    """Compose all currently landed scheduler duties."""
    await checkpoint_timeout_tick(pool)
    await utility_baselines_tick(pool)
    await refresh_ttl_tick(pool)


async def run_worker_loop(
    pool: asyncpg.Pool,
    stop: asyncio.Event,
    *,
    dispatch: dict[JobType, Dispatcher] | None = None,
    worker_id: str | None = None,
    idle_backoff: float = WORKER_IDLE_BACKOFF_SECONDS,
    until_empty: bool = False,
    scheduler_tick: SchedulerTick | None = None,
    tick_interval: float = SCHEDULER_TICK_SECONDS,
) -> None:
    """Tick: reclaim orphans → claim → dispatch by `job_type` → repeat.

    Clean-shutdown drain: once `stop` is set the loop claims nothing new but the
    in-flight job (already claimed this tick) runs to completion before exit.
    `until_empty` returns when the queue drains instead of idling — the bounded
    drain the dev-seed and tests use.

    `scheduler_tick` is the P3-9 scheduler scaffold (P3-11/P3-12 extend it):
    a duty callable invoked at most every `tick_interval` seconds, deliberately
    opt-in (None default) so tests and dev-seed drains never trigger scheduled
    duties — the production entry (api worker_loop) passes the real one. A
    failing tick logs and retries next interval; it never stops the loop.
    """
    dispatch = dispatch if dispatch is not None else build_dispatch(pool)
    worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    last_tick = float("-inf")

    while not stop.is_set():
        if scheduler_tick is not None:
            now = asyncio.get_running_loop().time()
            if now - last_tick >= tick_interval:
                last_tick = now
                try:
                    await scheduler_tick(pool)
                except Exception as error:
                    log.warning("scheduler_tick_failed", error=str(error))

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
