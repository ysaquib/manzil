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

from manzil_worker.fetching.ladder import fetch_with_ladder
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import RunState, SourceState

log = structlog.get_logger()

_PROCEED = (FetchOutcome.SUCCESS, FetchOutcome.NOT_LISTING)


async def fetch_stage(state: RunState, ctx: StageCtx) -> RunState:
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
        raise StageFatal(
            f"source unfetchable: {ladder.outcome.value} at tier {ladder.result.tier} "
            f"(attempts: {[(t, o.value) for t, o in ladder.attempts]})"
        )
    return state
