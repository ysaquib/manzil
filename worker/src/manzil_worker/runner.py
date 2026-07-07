"""The runner (P0-10, DESIGN §10.2): walk the stage list from the resume
cursor; the single load-bearing rule is persist BEFORE advance.

The Phase 0 CLI and the Phase 1+ queue worker are two entry points calling
the same `run_job` — this is not throwaway work.

Exception mapping (IMPLEMENTATION §2):
- StageRetryable  -> backoff + retry, STAGE_RETRIES attempts, then failed
- StageFatal / ExtractionInvalid -> job failed with the reason
- CheckpointRaised -> checkpoint persisted, state parked as waiting_user
  (Phase 0 CLI reports it and exits; answering arrives with the jobs UI)

Phase 0 stage order (DESIGN v2.4): VALIDATE_URL → FETCH → VALIDATE → EXTRACT
→ VERIFY → SCORE. VALIDATE_URL is the deterministic pre-fetch check of the
submitted URL itself; VALIDATE judges fetched page content ("is this a rental
listing page?"), so it necessarily follows the primary fetch.
"""

from __future__ import annotations

import random

import structlog
from manzil_shared.config import STAGE_BACKOFF_BASE_SECONDS, STAGE_RETRIES
from manzil_shared.errors import CheckpointRaised, ManzilError, StageRetryable
from manzil_shared.models import JobState

from manzil_worker.llm.client import RunContext, cost_tally, run_context
from manzil_worker.stages.base import Stage, StageCtx
from manzil_worker.stages.extract import extract_stage
from manzil_worker.stages.fetch import fetch_stage
from manzil_worker.stages.score import score_stage
from manzil_worker.stages.validate import validate_stage
from manzil_worker.stages.validate_url import validate_url_stage
from manzil_worker.stages.verify import verify_stage
from manzil_worker.state import RunState

log = structlog.get_logger()

PHASE0_STAGES: list[tuple[str, Stage]] = [
    ("validate_url", validate_url_stage),
    ("fetch", fetch_stage),
    ("validate", validate_stage),
    ("extract", extract_stage),
    ("verify", verify_stage),
    ("score", score_stage),
]


def _backoff_seconds(attempt: int) -> float:
    """`10s * 2^attempt`, jittered (IMPLEMENTATION §3 tunables)."""
    return STAGE_BACKOFF_BASE_SECONDS * (2**attempt) * random.uniform(0.5, 1.5)


async def _run_stage(name: str, stage: Stage, state: RunState, ctx: StageCtx) -> RunState:
    for attempt in range(STAGE_RETRIES + 1):
        try:
            with cost_tally() as tally:
                state = await stage(state, ctx)
            state.cost_usd += tally.cost_usd
            return state
        except StageRetryable as error:
            if attempt >= STAGE_RETRIES:
                raise
            delay = _backoff_seconds(attempt)
            log.warning(
                "stage_retry",
                job_id=str(state.job_id),
                stage=name,
                attempt=attempt + 1,
                delay=round(delay, 1),
                error=str(error),
            )
            await ctx.sleep(delay)
    raise AssertionError("unreachable")


async def run_job(
    state: RunState,
    ctx: StageCtx,
    stages: list[tuple[str, Stage]] = PHASE0_STAGES,
) -> RunState:
    """Resume-safe: starts at `state.cursor`; a re-run of a completed stage is
    harmless by the idempotency rule."""
    trace_ctx = RunContext(job_type=state.job_type.value, job_id=str(state.job_id), mode=state.mode)
    with run_context(trace_ctx):
        for index in range(state.cursor, len(stages)):
            name, stage = stages[index]
            log.info("stage_start", job_id=str(state.job_id), stage=name, cursor=index)
            try:
                state = await _run_stage(name, stage, state, ctx)
            except CheckpointRaised as checkpoint:
                state.checkpoint = checkpoint.prompt
                state.status = JobState.WAITING_USER
                await ctx.persistence.save(state)
                log.info(
                    "checkpoint",
                    job_id=str(state.job_id),
                    stage=name,
                    question=checkpoint.prompt.question,
                )
                return state
            except ManzilError as error:
                state.status = JobState.FAILED
                state.error = f"{name}: {error}"
                await ctx.persistence.save(state)
                log.error("stage_failed", job_id=str(state.job_id), stage=name, error=str(error))
                return state
            await ctx.persistence.save(state)  # outputs durable BEFORE the cursor moves
            state.cursor = index + 1
            await ctx.persistence.save(state)
    state.status = JobState.DONE
    await ctx.persistence.save(state)
    return state
