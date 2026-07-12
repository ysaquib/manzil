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
from manzil_shared.errors import CheckpointRaised, ManzilError, StageFatal, StageRetryable
from manzil_shared.models import JobState

from manzil_worker.llm.client import RunContext, cost_tally, run_context
from manzil_worker.stages.base import Stage, StageCtx
from manzil_worker.stages.dedupe import dedupe_stage
from manzil_worker.stages.extract import extract_stage
from manzil_worker.stages.fetch import fetch_stage
from manzil_worker.stages.plan import plan_stage
from manzil_worker.stages.score import score_stage
from manzil_worker.stages.validate import validate_stage
from manzil_worker.stages.validate_url import validate_url_stage
from manzil_worker.stages.verify import verify_stage
from manzil_worker.state import RunState

log = structlog.get_logger()

# Legacy fixed list (lowercase names, no PLAN): the fallback the runner walks for
# every pre-P3 RunState snapshot (`plan is None`) — old parked jobs resume exactly
# as before. New ingest jobs run the manifest-driven walk below.
PHASE0_STAGES: list[tuple[str, Stage]] = [
    ("validate_url", validate_url_stage),
    ("fetch", fetch_stage),
    ("validate", validate_stage),
    ("extract", extract_stage),
    ("verify", verify_stage),
    ("score", score_stage),
]
PHASE0_STAGE_NAMES: list[str] = [name for name, _ in PHASE0_STAGES]

# The live ingest stage list (P3-2, §2.1) — the single source of truth PLAN
# records into the manifest and the runner walks by name. UPPERCASE per the
# pinned §10.4 manifest shape; PLAN is stages[0] (it builds the manifest, then
# the walk continues at cursor 1). RECONCILE/VISION/ENRICH join as their tasks
# land — a new stage is one list entry, never a resume-breaking cursor shift.
INGEST_STAGES: list[tuple[str, Stage]] = [
    ("PLAN", plan_stage),
    ("VALIDATE_URL", validate_url_stage),
    ("FETCH", fetch_stage),
    ("VALIDATE", validate_stage),
    ("EXTRACT", extract_stage),
    ("DEDUPE", dedupe_stage),
    ("VERIFY", verify_stage),
    ("SCORE", score_stage),
]
INGEST_STAGE_NAMES: list[str] = [name for name, _ in INGEST_STAGES]

# name -> callable, for resolving a manifest's `stages` on resume. All stages a
# manifest can name live here (ingest today; later waves extend it).
STAGE_REGISTRY: dict[str, Stage] = dict(INGEST_STAGES)


def _manifest_walk(state: RunState) -> list[tuple[str, Stage]]:
    """Resolve `state.plan.stages` (names) to `(name, callable)` through the
    registry. A name with no registered stage is a fatal manifest error rather
    than a silent skip."""
    assert state.plan is not None
    walk: list[tuple[str, Stage]] = []
    for name in state.plan.stages:
        stage = STAGE_REGISTRY.get(name)
        if stage is None:
            raise StageFatal(f"plan references unknown stage {name!r}")
        walk.append((name, stage))
    return walk


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
    harmless by the idempotency rule.

    Walk selection (§2.1): once `state.plan` is set the runner walks the
    manifest's stage list by name (so stage insertions ride the plan, not an
    integer cursor); with `plan is None` it walks the caller's fixed `stages`
    (`PHASE0_STAGES` for the CLI/legacy snapshots, `INGEST_STAGES` for a fresh
    queue ingest whose PLAN sets `state.plan` on its first stage)."""
    walk = _manifest_walk(state) if state.plan is not None else stages
    trace_ctx = RunContext(job_type=state.job_type.value, job_id=str(state.job_id), mode=state.mode)
    with run_context(trace_ctx):
        for index in range(state.cursor, len(walk)):
            name, stage = walk[index]
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
