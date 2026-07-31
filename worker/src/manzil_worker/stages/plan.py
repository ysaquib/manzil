"""PLAN stage (P3-2, DESIGN §10.4) — the first stage in the ingest walk.

Deterministic manifest builder: it reads the persisted-source freshness and the
Source Policy, decides fetch-vs-skip per source, estimates cost from flat
per-stage figures, and writes the §10.4 manifest onto `RunState.plan`. The
manifest then *is* the runner's stage list (§2.1), so every later stage
insertion travels with the job instead of shifting an integer cursor.

Phase-3-early ingest is 100% deterministic: the single §10.4 judgment call
(ranking >3 candidate sources) is unreachable until DISCOVER (P3-5) exists, so
no LLM call fires here. The `plan_assist` pin stays documented for P3-5.

Skip discipline (this task's only skip): a same-property re-ingest whose
`property_sources` row still has a `cleaned_text_hash` and a `last_success_at`
within `PLAN_FRESH_TTL_HOURS` is planned `action: skip, why: hash_fresh`. PLAN
pre-loads the persisted cleaned text onto `state.sources` so FETCH honors the
skip by using it instead of re-fetching. Cross-hunt "same building, different
property row" reuse is DEDUPE's job (P3-4) and out of scope here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import structlog
from manzil_shared.config import PLAN_FRESH_TTL_HOURS, STAGE_COST_ESTIMATES_USD
from manzil_shared.errors import StageFatal
from manzil_shared.models import FetchOutcome
from pydantic import BaseModel

from manzil_worker.stages.base import StageCtx
from manzil_worker.state import DiscoveredSource, PlanManifest, PlanSource, RunState, SourceState
from manzil_worker.vision_refs import vision_references_ready

log = structlog.get_logger()


class _CandidateRanking(BaseModel):
    ordered_urls: list[str]


async def rank_discovered_sources(
    candidates: list[DiscoveredSource], state: RunState, ctx: StageCtx
) -> list[DiscoveredSource]:
    """The §10.4 optional judgment: rank a pool only when it exceeds three.

    Bad/missing ranking output falls back to DISCOVER's deterministic confidence
    order; source selection must never fail because this optional assist did.
    """
    if len(candidates) <= 3:
        return candidates
    expected = {candidate.url for candidate in candidates}
    content = json.dumps(
        {
            "property": state.property_identity.model_dump() if state.property_identity else None,
            "candidates": [
                {
                    "url": candidate.url,
                    "confidence": candidate.same_property_confidence.value,
                    "evidence": candidate.evidence,
                }
                for candidate in candidates
            ],
        },
        sort_keys=True,
    )
    try:
        ranked = await ctx.call_structured("plan_assist", _CandidateRanking, content)
        if len(ranked.ordered_urls) != len(candidates) or set(ranked.ordered_urls) != expected:
            raise ValueError("ranking must contain every candidate URL exactly once")
    except Exception as error:
        log.warning(
            "plan_assist_fallback",
            job_id=str(state.job_id),
            candidates=len(candidates),
            error=repr(error),
        )
        return candidates
    by_url = {candidate.url: candidate for candidate in candidates}
    return [by_url[url] for url in ranked.ordered_urls]


def _est_cost(stages: list[str], skipped: dict[str, str], *, custom_criteria: int = 0) -> float:
    """Sum flat per-stage estimates over the manifest's non-skipped stages
    (DESIGN §10.4/§2.7). Rounded so the estimate is a clean, comparable figure."""
    total = sum(
        STAGE_COST_ESTIMATES_USD.get(name, 0.0) * (custom_criteria if name == "CUSTOM_MATCH" else 1)
        for name in stages
        if name not in skipped
    )
    return round(total, 4)


async def plan_stage(state: RunState, ctx: StageCtx) -> RunState:
    """Build the §10.4 manifest for an ingest job. Runner-provided `INGEST_STAGES`
    is the single source of truth for the live stage list; PLAN records those
    names verbatim. IMAGE_FETCH and approved-profile VISION are live, and
    not-yet-landed stages are absent."""
    from manzil_worker.runner import INGEST_STAGE_NAMES

    if state.job_type.value == "refresh" and (
        state.refresh_fields or state.custom_criterion_keys
    ):
        return await _plan_refresh(state, ctx)

    fresh = await ctx.fresh_source_lookup(state.property_id, state.url)
    is_fresh = (
        fresh is not None
        and fresh.cleaned_text_hash is not None
        and fresh.last_success_at is not None
        and fresh.last_success_at > datetime.now(UTC) - timedelta(hours=PLAN_FRESH_TTL_HOURS)
    )

    if is_fresh:
        assert fresh is not None  # narrowed by is_fresh
        source_entry = PlanSource(url=state.url, action="skip", why="hash_fresh")
        # Hand FETCH the persisted cleaned text so it skips the network entirely.
        state.sources = [
            SourceState(
                url=state.url,
                outcome=FetchOutcome.SUCCESS,
                cleaned_text=fresh.cleaned_text,
                cleaned_hash=fresh.cleaned_text_hash or "",
                image_urls=fresh.image_urls,
            )
        ]
    else:
        # Brand-new (or stale) source: fetch at tier 1; the ladder escalates at
        # runtime. No `property_sources` row identity yet, so record the URL.
        source_entry = PlanSource(url=state.url, action="fetch", tier=1)

    stages = list(INGEST_STAGE_NAMES)
    if state.source_policy == "trust_link":
        stages.remove("DISCOVER")
        state.single_source_reason = "trust_link"
        state.slate_urls = [state.url]
    # VISION remains fail-closed if its approved, hash-validated reference
    # profile or matching prompt is missing.
    skipped: dict[str, str] = (
        {} if vision_references_ready() else {"VISION": "missing_reference_set"}
    )

    state.plan = PlanManifest(
        job_type=state.job_type.value,
        trigger=ctx.plan_trigger,
        source_policy=state.source_policy,
        sources=[source_entry],
        stages=stages,
        skipped=skipped,
        est_cost_usd=_est_cost(
            stages,
            skipped,
            custom_criteria=sum(criterion.custom_def is not None for criterion in ctx.rubric),
        ),
    )
    log.info(
        "planned",
        job_id=str(state.job_id),
        stage="plan",
        action=source_entry.action,
        source_policy=state.source_policy,
        est_cost_usd=state.plan.est_cost_usd,
    )
    return state


async def _plan_refresh(state: RunState, ctx: StageCtx) -> RunState:
    """Build a deterministic refresh manifest from durable contributing Sources."""
    sources = await ctx.refresh_source_lookup(
        state.hunt_listing_id, state.property_id, state.source_policy
    )
    if not sources:
        raise StageFatal("refresh has no submitted or contributing Sources")

    state.url = sources[0].url
    state.slate_urls = [source.url for source in sources]
    state.prior_source_hashes = {
        source.url: source.cleaned_text_hash
        for source in sources
        if source.cleaned_text_hash is not None
    }
    if state.custom_criterion_keys:
        # A custom-only refresh is deliberately fetch-free. The dispatcher
        # preloads the current cleaned Source text and Floor Plans; preserve
        # that evidence instead of replacing it with an empty placeholder.
        # Still enforce the contributing Slate selected above: a stale known
        # sibling outside the current Source Policy must not become evidence.
        selected_urls = {source.url for source in sources}
        state.sources = [source for source in state.sources if source.url in selected_urls]
        state.floor_plans = [
            plan for plan in state.floor_plans if (plan.source_url or state.url) in selected_urls
        ]
        if not state.sources:
            state.sources = [SourceState(url=sources[0].url)]
        stages = ["PLAN", "CUSTOM_MATCH", "SCORE"]
        state.plan = PlanManifest(
            job_type=state.job_type.value,
            trigger=ctx.plan_trigger,
            source_policy=state.source_policy,
            sources=[
                PlanSource(
                    source_id=str(source.source_id),
                    url=source.url,
                    action="skip",
                    why="custom_match_uses_cached_evidence",
                )
                for source in sources
            ],
            stages=stages,
            skipped={},
            est_cost_usd=_est_cost(stages, {}, custom_criteria=len(state.custom_criterion_keys)),
        )
        return state

    fields = set(state.refresh_fields)
    text = bool(fields & {"pricing", "listing_details"})
    images = "images" in fields
    enrich = bool(fields & {"reviews", "location"})
    # Image discovery is page-derived. Refreshing that class therefore also
    # re-runs the full Catalog extraction over the newly fetched bytes so image
    # persistence cannot accidentally retire every current Floor Plan by
    # projecting an image-only state with no plans.
    page_projection = text or images
    if not text and not images:
        state.sources = [
            SourceState(
                url=sources[0].url,
                image_urls=sources[0].image_urls,
            )
        ]
    stages = ["PLAN"]
    if text or images:
        stages.append("FETCH")
    if page_projection:
        stages.extend(["EXTRACT", "VERIFY", "RECONCILE"])
    if images:
        stages.extend(["IMAGE_FETCH", "IMAGE_CLASSIFY", "VISION"])
    if enrich:
        stages.append("ENRICH")
    custom_defs = [
        criterion.custom_def for criterion in ctx.rubric if criterion.custom_def is not None
    ]
    custom_count = sum(
        1
        for custom in custom_defs
        if (custom.requires_tool is None and "listing_details" in fields)
        or (
            custom.requires_tool is not None
            and custom.requires_tool.value == "maps"
            and "location" in fields
        )
    )
    if custom_count:
        stages.append("CUSTOM_MATCH")
    if text or images or enrich:
        stages.append("SCORE")

    plan_sources = [
        PlanSource(
            source_id=str(source.source_id),
            url=source.url,
            action="fetch" if text or images else "skip",
            tier=source.required_tier if text or images else None,
            why=None if text or images else "refresh_class_does_not_fetch_pages",
        )
        for source in sources
    ]
    skipped = (
        {} if vision_references_ready() else ({"VISION": "missing_reference_set"} if images else {})
    )
    state.plan = PlanManifest(
        job_type=state.job_type.value,
        trigger=ctx.plan_trigger,
        source_policy=state.source_policy,
        sources=plan_sources,
        stages=stages,
        skipped=skipped,
        est_cost_usd=_est_cost(stages, skipped, custom_criteria=custom_count),
    )
    return state
