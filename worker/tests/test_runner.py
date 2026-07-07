"""P0-10: runner semantics — persist BEFORE advance, retry with backoff,
fatal mapping, checkpoint parking, cursor resume (DESIGN §10.2)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from manzil_shared.errors import CheckpointRaised, StageFatal, StageRetryable
from manzil_shared.models import CheckpointKind, CheckpointPrompt, JobState, JobType
from manzil_worker.runner import run_job
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import RunState


class RecordingPersistence:
    def __init__(self) -> None:
        self.snapshots: list[tuple[int, str]] = []

    async def save(self, state: RunState) -> None:
        self.snapshots.append((state.cursor, state.status.value))


def make_state() -> RunState:
    return RunState(job_id=uuid4(), job_type=JobType.INGEST, url="https://x.test/1")


def make_ctx(persistence: RecordingPersistence) -> StageCtx:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    ctx = StageCtx(persistence=persistence, sleep=fake_sleep)
    ctx.sleeps = sleeps  # type: ignore[attr-defined]
    return ctx


def named_stage(name: str, log: list[str]):  # type: ignore[no-untyped-def]
    async def stage(state: RunState, ctx: StageCtx) -> RunState:
        log.append(name)
        return state

    return (name, stage)


def test_happy_path_persists_outputs_before_advancing_cursor() -> None:
    log: list[str] = []
    persistence = RecordingPersistence()
    stages = [named_stage("a", log), named_stage("b", log)]

    state = asyncio.run(run_job(make_state(), make_ctx(persistence), stages))

    assert log == ["a", "b"]
    assert state.status is JobState.DONE
    assert state.cursor == 2
    # Two saves per stage — outputs at the old cursor, then the advance — plus
    # the final done save. The first save after stage "a" must still say cursor 0.
    assert [c for c, _ in persistence.snapshots] == [0, 1, 1, 2, 2]
    assert persistence.snapshots[-1] == (2, "done")


def test_resume_starts_at_the_cursor_and_skips_completed_stages() -> None:
    log: list[str] = []
    persistence = RecordingPersistence()
    stages = [named_stage("a", log), named_stage("b", log), named_stage("c", log)]

    state = make_state()
    state.cursor = 2  # stages a and b already persisted by a previous run
    state = asyncio.run(run_job(state, make_ctx(persistence), stages))

    assert log == ["c"]
    assert state.status is JobState.DONE


def test_retryable_stage_is_retried_with_backoff_then_succeeds() -> None:
    attempts: list[int] = []

    async def flaky(state: RunState, ctx: StageCtx) -> RunState:
        attempts.append(1)
        if len(attempts) < 3:
            raise StageRetryable("transient")
        return state

    persistence = RecordingPersistence()
    ctx = make_ctx(persistence)
    state = asyncio.run(run_job(make_state(), ctx, [("flaky", flaky)]))

    assert state.status is JobState.DONE
    assert len(attempts) == 3
    sleeps = ctx.sleeps  # type: ignore[attr-defined]
    assert len(sleeps) == 2
    assert all(s > 0 for s in sleeps)
    assert sleeps[1] > sleeps[0] * 0.5  # exponential shape survives jitter


def test_retry_exhaustion_fails_the_job() -> None:
    async def always_failing(state: RunState, ctx: StageCtx) -> RunState:
        raise StageRetryable("still down")

    persistence = RecordingPersistence()
    state = asyncio.run(run_job(make_state(), make_ctx(persistence), [("down", always_failing)]))

    assert state.status is JobState.FAILED
    assert state.error is not None and "still down" in state.error
    assert persistence.snapshots[-1][1] == "failed"  # failure state is persisted


def test_fatal_stage_fails_the_job_and_stops_the_run() -> None:
    log: list[str] = []

    async def fatal(state: RunState, ctx: StageCtx) -> RunState:
        raise StageFatal("not a listing: heuristic")

    state = asyncio.run(
        run_job(
            make_state(),
            make_ctx(RecordingPersistence()),
            [("fatal", fatal), named_stage("never", log)],
        )
    )

    assert state.status is JobState.FAILED
    assert state.error == "fatal: not a listing: heuristic"
    assert log == []  # nothing after the failure runs


def test_checkpoint_parks_the_run_as_waiting_user() -> None:
    prompt = CheckpointPrompt(
        kind=CheckpointKind.CONFIRM_VALUE,
        question="Does $2,450 look right?",
        default="yes",
    )

    async def asks(state: RunState, ctx: StageCtx) -> RunState:
        raise CheckpointRaised(prompt)

    log: list[str] = []
    persistence = RecordingPersistence()
    state = asyncio.run(
        run_job(make_state(), make_ctx(persistence), [("asks", asks), named_stage("never", log)])
    )

    assert state.status is JobState.WAITING_USER
    assert state.checkpoint == prompt
    assert state.cursor == 0  # resuming re-runs the asking stage, idempotently
    assert log == []
    assert persistence.snapshots[-1][1] == "waiting_user"
