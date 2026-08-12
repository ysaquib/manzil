#!/usr/bin/env python
"""Export one Job's plan, timeline, costs, and metadata without its payload.

Usage:

    uv run --package manzil-api python scripts/export_job.py JOB_ID dev
    uv run --package manzil-api python scripts/export_job.py JOB_ID prod
    uv run --package manzil-api python scripts/export_job.py JOB_ID prod -o run.json

`dev` reads `DATABASE_URL` from `.env`, falling back to the standard local
Supabase database. `prod` reads `DATABASE_URL` and `SUPABASE_PROJECT_REF` from
`.env.prod`. Both modes fail closed when the selected URL points at the wrong
kind of target; an accidental production export in `dev` mode is not allowed.

The query names every Job column it exports. It never selects `payload` or
`payload_public`, even transiently. Output files are written atomically with
owner-only permissions because event details may carry operational evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DEV_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "host.docker.internal"}
EXPORT_VERSION = 1

Environment = Literal["prod", "dev"]

# Deliberately explicit: payload and payload_public must never enter this process.
JOB_SELECT_SQL = """
    select id, hunt_id, hunt_listing_id, type::text as type, state::text as state,
           current_stage, attempts, error, locked_by, locked_at, created_at,
           started_at, finished_at, warnings, plan, cost_actual_usd
      from jobs
     where id = $1
"""

EVENT_SELECT_SQL = """
    select id, job_id, stage, event, detail, at
      from job_events
     where job_id = $1
     order by at, id
"""

COST_SELECT_SQL = """
    select stage, llm_calls, llm_cost_usd, input_tokens, output_tokens,
           cache_read_tokens, cache_write_tokens, fetch_calls, fetch_cost_usd,
           fetch_calls_by_provider, updated_at
      from job_stage_costs
     where job_id = $1
     order by stage
"""

JOB_METADATA_COLUMNS = (
    "id",
    "hunt_id",
    "hunt_listing_id",
    "type",
    "state",
    "current_stage",
    "attempts",
    "error",
    "locked_by",
    "locked_at",
    "created_at",
    "started_at",
    "finished_at",
    "warnings",
)


class ExportError(RuntimeError):
    """The requested export cannot be produced safely or completely."""


def _jsonable(value: Any) -> Any:
    """Convert asyncpg/Postgres values into stable JSON-native values."""
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _json_document(value: Any) -> Any:
    """Decode JSONB returned by an asyncpg connection without a JSON codec."""
    if isinstance(value, str):
        return json.loads(value)
    return value


def _validate_database_target(
    database_url: str, environment: Environment, project_ref: str | None = None
) -> None:
    parsed = urlparse(database_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"postgres", "postgresql"} or not host:
        raise ExportError("DATABASE_URL must be a PostgreSQL URL with a hostname")

    is_local = host in LOCAL_HOSTS
    if environment == "dev":
        if not is_local:
            raise ExportError(
                f"Refusing dev export against non-local database host {host!r}; "
                "use the prod environment explicitly"
            )
        return

    if is_local:
        raise ExportError(
            f"Refusing prod export against local database host {host!r}; check .env.prod"
        )
    if not project_ref:
        raise ExportError("SUPABASE_PROJECT_REF is missing from .env.prod")

    ref = project_ref.strip().lower()
    username = (parsed.username or "").lower()
    direct_host_matches = host == f"db.{ref}.supabase.co"
    pooler_user_matches = username == f"postgres.{ref}" or username.endswith(f".{ref}")
    if not direct_host_matches and not pooler_user_matches:
        raise ExportError(
            "DATABASE_URL does not identify SUPABASE_PROJECT_REF: expected either "
            f"host db.{ref}.supabase.co or a pooler username ending in .{ref}"
        )


def _database_url(environment: Environment) -> str:
    if environment == "prod":
        env_path = ROOT / ".env.prod"
        if not env_path.is_file():
            raise ExportError(f"Production environment file does not exist: {env_path}")
        values = dotenv_values(env_path)
        database_url = str(values.get("DATABASE_URL") or "").strip()
        project_ref = str(values.get("SUPABASE_PROJECT_REF") or "").strip()
        if not database_url:
            raise ExportError("DATABASE_URL is missing from .env.prod")
        _validate_database_target(database_url, environment, project_ref)
        return database_url

    env_path = ROOT / ".env"
    values = dotenv_values(env_path) if env_path.is_file() else {}
    database_url = str(values.get("DATABASE_URL") or DEV_DATABASE_URL).strip()
    _validate_database_target(database_url, environment)
    return database_url


async def read_job_export(
    connection: Any,
    job_id: UUID,
    environment: Environment,
    *,
    exported_at: datetime | None = None,
) -> dict[str, Any]:
    """Read one consistent, payload-free export from an asyncpg connection or pool."""
    job = await connection.fetchrow(JOB_SELECT_SQL, job_id)
    if job is None:
        raise ExportError(f"Job {job_id} does not exist in {environment}")

    events = await connection.fetch(EVENT_SELECT_SQL, job_id)
    stage_cost_rows = await connection.fetch(COST_SELECT_SQL, job_id)

    llm_cost = sum((_decimal(row["llm_cost_usd"]) for row in stage_cost_rows), Decimal(0))
    fetch_cost = sum((_decimal(row["fetch_cost_usd"]) for row in stage_cost_rows), Decimal(0))
    recorded_cost = llm_cost + fetch_cost
    actual_cost = _decimal(job["cost_actual_usd"])

    totals = {
        "llm_calls": sum(row["llm_calls"] for row in stage_cost_rows),
        "fetch_calls": sum(row["fetch_calls"] for row in stage_cost_rows),
        "input_tokens": sum(row["input_tokens"] for row in stage_cost_rows),
        "output_tokens": sum(row["output_tokens"] for row in stage_cost_rows),
        "cache_read_tokens": sum(row["cache_read_tokens"] for row in stage_cost_rows),
        "cache_write_tokens": sum(row["cache_write_tokens"] for row in stage_cost_rows),
        "llm_cost_usd": llm_cost,
        "fetch_cost_usd": fetch_cost,
        "recorded_by_stage_usd": recorded_cost,
        # Legacy Jobs may predate stage costs. Keeping the difference explicit
        # is more honest than silently pretending the two stores reconcile.
        "unattributed_usd": actual_cost - recorded_cost,
    }

    metadata = {column: job[column] for column in JOB_METADATA_COLUMNS}
    metadata["warnings"] = _json_document(metadata["warnings"])
    timeline = []
    for row in events:
        event = dict(row)
        event["detail"] = _json_document(event["detail"])
        timeline.append(event)
    by_stage = []
    for row in stage_cost_rows:
        stage_cost = dict(row)
        stage_cost["fetch_calls_by_provider"] = _json_document(
            stage_cost["fetch_calls_by_provider"]
        )
        by_stage.append(stage_cost)

    return _jsonable(
        {
            "schema_version": EXPORT_VERSION,
            "exported_at": exported_at or datetime.now(UTC),
            "environment": environment,
            "job": metadata,
            "plan": _json_document(job["plan"]),
            "timeline": timeline,
            "costs": {
                "actual_usd": actual_cost,
                "totals": totals,
                "by_stage": by_stage,
            },
        }
    )


def _default_output(job_id: UUID, environment: Environment, exported_at: str) -> Path:
    stamp = datetime.fromisoformat(exported_at).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path.cwd() / f"job-{job_id}-{environment}-{stamp}.json"


def _write_json(path: Path, report: dict[str, Any], *, force: bool) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        raise ExportError(f"Output already exists: {path} (pass --force to replace it)")

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _job_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid Job UUID: {value}") from exc


async def _export(job_id: UUID, environment: Environment) -> dict[str, Any]:
    database_url = _database_url(environment)
    connection = await asyncpg.connect(
        database_url,
        timeout=15,
        command_timeout=30,
        server_settings={"application_name": "manzil_job_export"},
    )
    try:
        async with connection.transaction(readonly=True):
            return await read_job_export(connection, job_id, environment)
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", type=_job_id, help="Job UUID to export")
    parser.add_argument("environment", choices=("prod", "dev"), help="database environment")
    parser.add_argument(
        "-o", "--output", type=Path, help="output path (defaults to a timestamped file)"
    )
    parser.add_argument("--force", action="store_true", help="replace an existing output file")
    args = parser.parse_args()

    try:
        report = asyncio.run(_export(args.job_id, args.environment))
        output = args.output or _default_output(
            args.job_id, args.environment, report["exported_at"]
        )
        _write_json(output, report, force=args.force)
    except (ExportError, OSError, asyncpg.PostgresError) as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {output.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
