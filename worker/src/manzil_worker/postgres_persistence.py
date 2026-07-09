"""Postgres persistence (P1-2, DESIGN §8.2/§10.1): the durable sink behind the
same `Persistence` protocol as `FilePersistence`.

Where Phase 0's `FilePersistence` dumps the whole `RunState` to a JSON file,
this maps it onto the `jobs` row: scalar run outcomes land in dedicated columns
(`state`, `current_stage`, `error`, `cost_actual_usd`, `plan`) for queryability,
and the full `RunState` snapshot lives under `payload.run_state` so an orphan
reclaim can reconstruct and resume the run verbatim. Every `save` also refreshes
`locked_at` — the persist-before-advance points are exactly the stage boundaries
where a heartbeat belongs (§8.2). Stage transitions append `job_events` rows so
the History tab / Tasks view have a per-stage timeline.

`save` is the pinned protocol surface; `load` mirrors `FilePersistence.load` so
the queue dispatch can rebuild a `RunState` from the row on resume.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from manzil_shared.models import JobState

from manzil_worker.state import RunState

if TYPE_CHECKING:
    import asyncpg

# jobs.state accepts these terminal values; the rest of JobState maps 1:1 too.
_TERMINAL = (JobState.DONE, JobState.FAILED, JobState.CANCELLED)

# A projection hook: derived-row writes (e.g. scores/extractions) that must
# commit atomically with the DONE flip. Runs inside the terminal-save
# transaction, so a failure rolls the whole terminal transition back — the job
# never reaches `done` without its projection (persist-before-advance for it).
OnDone = Callable[["asyncpg.Connection", RunState], Awaitable[None]]


class PostgresPersistence:
    """Persist-before-advance sink writing to one `jobs` row.

    `stage_names` is the ordered stage list the runner walks (indexed by
    `RunState.cursor`); it turns the numeric cursor into `current_stage` text and
    names the `job_events` rows. `start_cursor` seeds the completed-event
    watermark so a resumed run does not re-announce already-finished stages.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        job_id: UUID,
        stage_names: list[str],
        *,
        start_cursor: int | None = None,
        on_done: OnDone | None = None,
    ) -> None:
        self._pool = pool
        self.job_id = job_id
        self._stage_names = stage_names
        self._last_completed = start_cursor
        self._terminal_emitted = False
        self._on_done = on_done
        self._projected = False

    def _current_stage(self, cursor: int) -> str | None:
        # The stage the job is at / resumes from; None once every stage is done.
        if 0 <= cursor < len(self._stage_names):
            return self._stage_names[cursor]
        return None

    async def save(self, state: RunState) -> None:
        cursor = state.cursor
        if self._last_completed is None:
            self._last_completed = cursor
        snapshot = json.dumps(state.model_dump(mode="json"))
        plan = json.dumps(state.plan) if state.plan is not None else None
        finished = state.status in _TERMINAL
        current_stage = self._current_stage(cursor)

        async with self._pool.acquire() as conn, conn.transaction():
            # The projection commits in THIS transaction, before the DONE flip is
            # visible — so a projection failure rolls back the terminal state and
            # the job stays reclaimable/retryable rather than ending done-empty.
            if state.status is JobState.DONE and self._on_done is not None and not self._projected:
                await self._on_done(conn, state)
                self._projected = True
            await conn.execute(
                """
                update jobs set
                    state = $2::job_state,
                    current_stage = $3,
                    error = $4,
                    cost_actual_usd = $5,
                    payload = jsonb_set(coalesce(payload, '{}'::jsonb),
                                        '{run_state}', $6::jsonb, true),
                    plan = $7::jsonb,
                    locked_at = now(),
                    finished_at = case when $8 then now() else finished_at end
                where id = $1
                """,
                self.job_id,
                state.status.value,
                current_stage,
                state.error,
                Decimal(str(state.cost_usd)),
                snapshot,
                plan,
                finished,
            )
            # A stage completes when the cursor advances past it (persist-before-
            # advance means outputs are already durable at that point).
            while self._last_completed < cursor:
                await self._emit(conn, self._stage_names[self._last_completed], "completed")
                self._last_completed += 1
            if not self._terminal_emitted:
                if state.status is JobState.FAILED:
                    await self._emit(
                        conn, current_stage or "run", "failed", {"error": state.error}
                    )
                    self._terminal_emitted = True
                elif state.status is JobState.WAITING_USER and state.checkpoint is not None:
                    await self._emit(
                        conn,
                        current_stage or "run",
                        "checkpoint_asked",
                        {"question": state.checkpoint.question},
                    )
                    self._terminal_emitted = True

    async def _emit(
        self,
        conn: asyncpg.Connection,
        stage: str,
        event: str,
        detail: dict | None = None,
    ) -> None:
        await conn.execute(
            "insert into job_events (job_id, stage, event, detail) values ($1, $2, $3, $4::jsonb)",
            self.job_id,
            stage,
            event,
            json.dumps(detail or {}),
        )

    async def load(self, job_id: UUID) -> RunState:
        row = await self._pool.fetchval("select payload from jobs where id = $1", job_id)
        if row is None:
            raise LookupError(f"no jobs row for {job_id}")
        payload = json.loads(row)
        snapshot = payload.get("run_state")
        if snapshot is None:
            raise LookupError(f"jobs row {job_id} has no persisted run_state to resume")
        return RunState.model_validate(snapshot)
