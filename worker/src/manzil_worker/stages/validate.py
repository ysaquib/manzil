"""VALIDATE stage (P0-8, DESIGN §10.3): is this a rental listing page?

Heuristics first, LLM to confirm — a page with zero listing signals (no
currency, no bed/bath tokens, no address) is rejected without spending a
call; anything with signals gets the P1 forced-schema confirmation. Rejection
is fatal: the job fails with the reason, it does not retry.
"""

from __future__ import annotations

import structlog
from manzil_shared.config import CLEANED_TEXT_MIN_CHARS
from manzil_shared.errors import StageFatal
from pydantic import BaseModel

from manzil_worker.fetching.classifier import has_listing_signal
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import RunState

log = structlog.get_logger()


class ValidationResult(BaseModel):
    is_listing: bool
    property_name: str | None = None
    reason: str


async def validate_stage(state: RunState, ctx: StageCtx) -> RunState:
    text = state.sources[0].cleaned_text

    # Heuristic gate: too little text or no listing token — no LLM needed.
    if len(text) < CLEANED_TEXT_MIN_CHARS:
        raise StageFatal("not a listing: cleaned text below minimum (heuristic)")
    if not has_listing_signal(text):
        raise StageFatal("not a listing: no currency/bed-bath/address signal (heuristic)")

    result = await ctx.call_structured("validate", ValidationResult, text)
    log.info(
        "validated",
        job_id=str(state.job_id),
        stage="validate",
        is_listing=result.is_listing,
        reason=result.reason,
    )
    if not result.is_listing:
        raise StageFatal(f"not a listing: {result.reason}")
    return state
