"""FETCH stage (Phase 0: single source — the submitted URL).

Runs the tier ladder (§10.7) and lands the cleaned page on RunState. Outcome
routing: `success` and `not_listing` proceed (the classifier's not_listing is
a candidate verdict — VALIDATE is the authority); `error` is retryable;
`shell`/`blocked` at the top tier is fatal — §10.1: hard failure only when
zero sources are fetchable, and in Phase 0 there is exactly one source.
"""

from __future__ import annotations

import structlog
from manzil_shared.errors import StageFatal, StageRetryable
from manzil_shared.models import FetchOutcome

from manzil_worker.enrich.images import discover_image_urls
from manzil_worker.fetching.ladder import fetch_with_ladder
from manzil_worker.fetching.registry import MAX_TIER
from manzil_worker.fetching.slug_hint import search_hint
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import RunState, SourceState

log = structlog.get_logger()

_PROCEED = (FetchOutcome.SUCCESS, FetchOutcome.NOT_LISTING)


def _planned_skip(state: RunState) -> bool:
    """True when PLAN marked this run's source `action: skip` (why: hash_fresh):
    the persisted cleaned text is already on `state.sources`, so FETCH must use it
    rather than hit the network (DESIGN §10.4, P3-2)."""
    if state.plan is None:
        return False
    entry = next((s for s in state.plan.sources if s.url == state.url), None)
    return entry is not None and entry.action == "skip" and bool(state.sources)


async def fetch_stage(state: RunState, ctx: StageCtx) -> RunState:
    if _planned_skip(state):
        source = state.sources[0]
        log.info(
            "fetch_skipped",
            job_id=str(state.job_id),
            stage="fetch",
            why="hash_fresh",
            hash=source.cleaned_hash,
        )
        return state
    if ctx.registry is None:
        raise StageFatal("fetch: no adapter registry in StageCtx")
    ladder = await fetch_with_ladder(state.url, ctx.registry, ctx.fetchers)
    source = SourceState(
        url=state.url,
        tier_used=ladder.result.tier,
        outcome=ladder.outcome,
        cleaned_text=ladder.cleaned.text,
        cleaned_hash=ladder.cleaned.text_hash,
        fee_tables_found=ladder.cleaned.fee_tables_found,
        image_urls=discover_image_urls(ladder.result.body, ladder.result.final_url),
    )
    state.sources = [source]
    log.info(
        "fetched",
        job_id=str(state.job_id),
        stage="fetch",
        tier=ladder.result.tier,
        outcome=ladder.outcome.value,
    )

    if ladder.outcome is FetchOutcome.ERROR:
        raise StageRetryable(f"fetch error for {state.url} (status {ladder.result.status_code})")
    if ladder.outcome not in _PROCEED:
        message = (
            f"source unfetchable: {ladder.outcome.value} at tier {ladder.result.tier} "
            f"(attempts: {[(t, o.value) for t, o in ladder.attempts]})"
        )
        # Say when the ladder topped out early: tier 3 off the ladder (no provider
        # key in this process's environment, §10.7) reads very differently from
        # tier 3 tried-and-blocked.
        if MAX_TIER not in ctx.fetchers:
            message += (
                "; tier 3 (unblocker) was not attempted — no provider key "
                "configured in this process's environment"
            )
        # §20 2026-07-07 stopgap: the URL slug usually names the property —
        # hand the human the search that DISCOVER (P3-5) will one day run.
        hint = search_hint(state.url)
        if hint:
            message += (
                f'; property identity from the URL: try searching "{hint}" on a '
                "fetchable source (e.g. rent.com, apartmentguide.com) and resubmit"
            )
        raise StageFatal(message)
    return state
