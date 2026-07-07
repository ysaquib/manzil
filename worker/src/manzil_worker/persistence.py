"""Phase 0 persistence: one JSON file per run under `.manzil/runs/`.

The persist-before-advance discipline (DESIGN §10.2) needs a durable sink
before the jobs table exists (per-hunt tables land in migration 0002, P1-1);
a file per run keeps runs inspectable and resumable in the meantime. P1-2
replaces this with the Postgres jobs row behind the same Persistence
protocol.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from manzil_worker.state import RunState

DEFAULT_RUNS_DIR = Path(".manzil") / "runs"


class FilePersistence:
    def __init__(self, runs_dir: Path = DEFAULT_RUNS_DIR) -> None:
        self.runs_dir = runs_dir

    def path_for(self, job_id: UUID) -> Path:
        return self.runs_dir / f"{job_id}.json"

    async def save(self, state: RunState) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(state.job_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(state.model_dump_json(indent=2))
        tmp.replace(path)  # atomic: a crash mid-write never corrupts the run file

    def load(self, job_id: UUID) -> RunState:
        return RunState.model_validate_json(self.path_for(job_id).read_text())
