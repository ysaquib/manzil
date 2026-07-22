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


def _est_cost(stages: list[str], skipped: dict[str, str]) -> float:
    """Sum flat per-stage estimates over the manifest's non-skipped stages
    (DESIGN §10.4/§2.7). Rounded so the estimate is a clean, comparable figure."""
    total = sum(STAGE_COST_ESTIMATES_USD.get(name, 0.0) for name in stages if name not in skipped)
    return round(total, 4)


async def plan_stage(state: RunState, ctx: StageCtx) -> RunState:
    """Build the §10.4 manifest for an ingest job. Runner-provided `INGEST_STAGES`
    is the single source of truth for the live stage list; PLAN records those
    names verbatim. IMAGE_FETCH is live, VISION is explicitly skipped until its
    reference/prompt gate passes, and not-yet-landed stages are absent."""
    from manzil_worker.runner import INGEST_STAGE_NAMES

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
    # P3-7 is fail-closed until the complete, versioned human reference set is
    # present. IMAGE_FETCH still runs so assets/hashes can be prepared safely.
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
        est_cost_usd=_est_cost(stages, skipped),
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
