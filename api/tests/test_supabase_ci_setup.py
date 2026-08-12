from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "setup-supabase-ci.sh"


def classify(tmp_path: Path, text: str) -> int:
    log = tmp_path / "reset.log"
    log.write_text(text)
    return subprocess.run(
        ["bash", str(SCRIPT), "--classify-log", str(log)],
        check=False,
        capture_output=True,
        text=True,
    ).returncode


def test_only_post_seed_storage_or_kong_health_failures_are_retryable(tmp_path: Path) -> None:
    storage_race = "Seeding data\nRestarting containers\nstorage timed out with 502"
    assert classify(tmp_path, storage_race) == 0
    assert classify(tmp_path, "Seeding data\nRestarting containers\nkong healthcheck timeout") == 0


def test_sql_and_pre_seed_failures_are_never_retryable(tmp_path: Path) -> None:
    assert classify(tmp_path, "Applying migration 42\nERROR: relation missing\n") != 0
    assert classify(tmp_path, "storage timeout before migrations\n") != 0
    assert classify(tmp_path, "Seeding data\nRestarting containers\nstorage unhealthy\n") != 0
