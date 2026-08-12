"""Payload-free Job export script coverage."""

from __future__ import annotations

import importlib.util
import json
import stat
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_job.py"


def _load_script():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("export_job", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_environment_guard_refuses_crossed_targets() -> None:
    export_job = _load_script()
    export_job._validate_database_target(
        "postgresql://postgres:postgres@127.0.0.1:54322/postgres", "dev"
    )
    export_job._validate_database_target(
        "postgresql://postgres.projectref:secret@aws-0.pooler.supabase.com:5432/postgres",
        "prod",
        "projectref",
    )

    with pytest.raises(export_job.ExportError, match="non-local"):
        export_job._validate_database_target(
            "postgresql://postgres.projectref:secret@aws-0.pooler.supabase.com:5432/postgres",
            "dev",
        )
    with pytest.raises(export_job.ExportError, match="local database"):
        export_job._validate_database_target(
            "postgresql://postgres:postgres@localhost:54322/postgres", "prod", "projectref"
        )


def test_writer_is_private_atomic_and_refuses_an_accidental_overwrite(tmp_path: Path) -> None:
    export_job = _load_script()
    output = tmp_path / "job.json"
    report = {"schema_version": 1, "timeline": []}

    export_job._write_json(output, report, force=False)

    assert json.loads(output.read_text()) == report
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".job.json.*"))
    with pytest.raises(export_job.ExportError, match="already exists"):
        export_job._write_json(output, report, force=False)


@pytest.mark.asyncio
async def test_export_includes_full_history_and_costs_but_never_payload(
    db_pool, collab_hunt
) -> None:
    export_job = _load_script()
    plan = {"stages": ["fetch", "extract", "score"], "reason": "test manifest"}
    job_id = await db_pool.fetchval(
        """
        insert into jobs (
            hunt_id, hunt_listing_id, type, state, current_stage, plan, payload,
            attempts, cost_actual_usd, started_at, finished_at, warnings
        ) values (
            $1, $2, 'ingest', 'done', 'score', $3::jsonb, $4::jsonb,
            2, 0.0123, now() - interval '4 seconds', now(), $5::jsonb
        ) returning id
        """,
        collab_hunt["hunt_id"],
        collab_hunt["member_listing_id"],
        json.dumps(plan),
        json.dumps({"secret_marker": "PAYLOAD_MUST_NOT_ESCAPE", "run_state": {"cursor": 3}}),
        json.dumps([{"stage": "fetch", "code": "degraded", "message": "Used fallback"}]),
    )
    await db_pool.executemany(
        """
        insert into job_events (job_id, stage, event, detail, at)
        values ($1, $2, $3, $4::jsonb, $5)
        """,
        [
            (
                job_id,
                "fetch",
                "started",
                json.dumps({"attempt": 1}),
                datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC),
            ),
            (
                job_id,
                "score",
                "completed",
                json.dumps({"score": 8.5}),
                datetime(2026, 8, 11, 12, 0, 4, tzinfo=UTC),
            ),
        ],
    )
    await db_pool.executemany(
        """
        insert into job_stage_costs (
            job_id, stage, llm_calls, llm_cost_usd, input_tokens, output_tokens,
            cache_read_tokens, cache_write_tokens, fetch_calls, fetch_cost_usd,
            fetch_calls_by_provider
        ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
        """,
        [
            (job_id, "extract", 1, 0.010000, 100, 20, 10, 0, 0, 0, "{}"),
            (job_id, "fetch", 0, 0, 0, 0, 0, 0, 1, 0.001000, '{"bright_data": 1}'),
        ],
    )

    try:
        report = await export_job.read_job_export(
            db_pool,
            UUID(str(job_id)),
            "dev",
            exported_at=datetime(2026, 8, 11, 13, 0, 0, tzinfo=UTC),
        )
        encoded = json.dumps(report)

        assert report["plan"] == plan
        assert [event["event"] for event in report["timeline"]] == ["started", "completed"]
        assert report["timeline"][0]["detail"] == {"attempt": 1}
        assert report["job"]["warnings"][0]["code"] == "degraded"
        assert report["costs"]["actual_usd"] == 0.0123
        assert report["costs"]["totals"] == {
            "llm_calls": 1,
            "fetch_calls": 1,
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_read_tokens": 10,
            "cache_write_tokens": 0,
            "llm_cost_usd": 0.01,
            "fetch_cost_usd": 0.001,
            "recorded_by_stage_usd": 0.011,
            "unattributed_usd": 0.0013,
        }
        assert "payload" not in report["job"]
        assert "payload_public" not in report["job"]
        assert "PAYLOAD_MUST_NOT_ESCAPE" not in encoded
        assert "payload" not in export_job.JOB_SELECT_SQL.lower()
    finally:
        await db_pool.execute("delete from jobs where id = $1", job_id)
