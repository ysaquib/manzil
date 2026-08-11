"""Jobs, Costs and System (AD-5, DESIGN §20 v3.44).

The operator's half of the panel: the queue as something to act on, spend as
something to understand, and the machine's configuration as something to read
but never edit.

One honesty note that shapes the Costs tab. `job_stage_costs` records spend per
**stage**, not per model — that was AD-C's deliberate choice, because per-call
telemetry is Langfuse's job. "Spend by model" is therefore derived by grouping
stages under the model each is pinned to *right now*, and the response says so
(`grouped_by_current_pin`). It is genuinely useful for "what is Gemini costing
us", and it would be wrong to present it as history: a stage that was re-pinned
last week has its old spend filed under the new model.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status
from manzil_shared.config import TIER3_FREE_MONTHLY_CREDITS, TIER3_PRICES_USD
from manzil_worker.fetching.tier3 import provider_configured
from manzil_worker.llm.config import MODEL_PRICES, STAGE_MODELS, model_for_stage

from manzil_api.admin.dependencies import AdminUser, Audit
from manzil_api.admin.schemas import (
    ActionResult,
    CostsReport,
    JobDetail,
    JobRow,
    SpendBucket,
    SpendPoint,
    SystemReport,
)
from manzil_api.dependencies import DbPool
from manzil_api.exceptions import ManzilAPIError

router = APIRouter(prefix="/admin", tags=["admin"])

# A claimed Job whose heartbeat is older than this is presumed orphaned. The
# worker refreshes `locked_at` at every persist-before-advance point, so a gap
# this size means the process that claimed it is gone.
STALE_LOCK_MINUTES = 15


class JobNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "job_not_found"


class JobNotRetryable(ManzilAPIError):
    status_code = status.HTTP_409_CONFLICT
    code = "job_not_retryable"


class AdminHuntLocked(ManzilAPIError):
    status_code = status.HTTP_423_LOCKED
    code = "hunt_locked"


# ── Jobs ─────────────────────────────────────────────────────────────────────

_JOB_SQL = """
select
    j.id, j.hunt_id, h.name as hunt_name, j.type::text as type, j.state::text as state,
    j.current_stage, j.attempts, j.error, j.cost_actual_usd, j.created_at, j.finished_at,
    j.locked_by, j.locked_at,
    (j.state = 'running' and j.locked_at < now() - ($1 || ' minutes')::interval) as stale,
    p.name as listing_name
from jobs j
left join hunts h on h.id = j.hunt_id
left join hunt_listings hl on hl.id = j.hunt_listing_id
left join properties p on p.id = hl.property_id
"""


def _job_row(row: Any) -> JobRow:
    data = dict(row)
    data["cost_actual_usd"] = float(data["cost_actual_usd"] or 0)
    return JobRow(**data)


@router.get("/jobs", response_model=list[JobRow], summary="The queue, across every Hunt")
async def list_jobs(
    admin: AdminUser,
    pool: DbPool,
    state: str | None = Query(None, max_length=20),
    hunt_id: UUID | None = None,
    stale_only: bool = False,
    limit: int = Query(100, ge=1, le=500),
) -> list[JobRow]:
    rows = await pool.fetch(
        _JOB_SQL
        + """
        where ($2::text is null or j.state::text = $2)
          and ($3::uuid is null or j.hunt_id = $3)
          and (not $4 or (j.state = 'running'
                          and j.locked_at < now() - ($1 || ' minutes')::interval))
        order by j.created_at desc
        limit $5
        """,
        str(STALE_LOCK_MINUTES),
        state,
        hunt_id,
        stale_only,
        limit,
    )
    return [_job_row(row) for row in rows]


@router.get("/jobs/{job_id}", response_model=JobDetail, summary="One Job, with its timeline")
async def get_job(job_id: UUID, admin: AdminUser, pool: DbPool) -> JobDetail:
    row = await pool.fetchrow(_JOB_SQL + " where j.id = $2", str(STALE_LOCK_MINUTES), job_id)
    if row is None:
        raise JobNotFound("No such Job")

    events = await pool.fetch(
        "select stage, event, detail, at from job_events where job_id = $1 order by at",
        job_id,
    )
    costs = await pool.fetch(
        "select stage, llm_cost_usd, fetch_cost_usd, llm_calls, fetch_calls "
        "from job_stage_costs where job_id = $1 order by llm_cost_usd + fetch_cost_usd desc",
        job_id,
    )
    return JobDetail(
        **_job_row(row).model_dump(),
        events=[dict(event) for event in events],
        stage_costs=[
            {
                "stage": cost["stage"],
                "llm_cost_usd": float(cost["llm_cost_usd"]),
                "fetch_cost_usd": float(cost["fetch_cost_usd"]),
                "llm_calls": cost["llm_calls"],
                "fetch_calls": cost["fetch_calls"],
            }
            for cost in costs
        ],
    )


@router.post("/jobs/{job_id}/retry", response_model=ActionResult, summary="Re-queue a Job")
async def retry_job(job_id: UUID, admin: AdminUser, pool: DbPool, audit: Audit) -> ActionResult:
    row = await pool.fetchrow(
        "select j.state::text as state, j.hunt_id, h.locked_at "
        "from jobs j join hunts h on h.id=j.hunt_id where j.id = $1",
        job_id,
    )
    if row is None:
        raise JobNotFound("No such Job")
    if row["locked_at"] is not None:
        raise AdminHuntLocked("Unlock this Hunt before retrying its Jobs")
    if row["state"] not in ("failed", "cancelled"):
        raise JobNotRetryable(f"A {row['state']} Job cannot be retried")

    # `attempts` is reset so the runner's backoff ladder starts clean; the lock
    # is cleared so the loop can claim it.
    await pool.execute(
        "update jobs set state = 'queued', attempts = 0, error = null, "
        "locked_by = null, locked_at = null, finished_at = null where id = $1",
        job_id,
    )
    await audit.record(
        "job.retry",
        target_type="job",
        target_id=job_id,
        hunt_id=row["hunt_id"],
        before={"state": row["state"]},
        after={"state": "queued"},
    )
    return ActionResult(detail="Job re-queued")


@router.post("/jobs/{job_id}/cancel", response_model=ActionResult, summary="Cancel a Job")
async def cancel_job(job_id: UUID, admin: AdminUser, pool: DbPool, audit: Audit) -> ActionResult:
    row = await pool.fetchrow(
        "select j.state::text as state, j.hunt_id, h.locked_at "
        "from jobs j join hunts h on h.id=j.hunt_id where j.id = $1",
        job_id,
    )
    if row is None:
        raise JobNotFound("No such Job")
    if row["locked_at"] is not None:
        raise AdminHuntLocked("Unlock this Hunt before cancelling its Jobs")
    if row["state"] in ("done", "cancelled"):
        raise JobNotRetryable(f"A {row['state']} Job cannot be cancelled")

    await pool.execute(
        "update jobs set state = 'cancelled', finished_at = now() where id = $1", job_id
    )
    await audit.record(
        "job.cancel",
        target_type="job",
        target_id=job_id,
        hunt_id=row["hunt_id"],
        before={"state": row["state"]},
        after={"state": "cancelled"},
    )
    return ActionResult(detail="Job cancelled")


@router.post(
    "/jobs/release-locks",
    response_model=ActionResult,
    summary="Release every stale lock",
)
async def release_stale_locks(admin: AdminUser, pool: DbPool, audit: Audit) -> ActionResult:
    """A Job whose worker died stays `running` forever, holding a lock nobody
    will ever release. This is the orphan scan as a button — it re-queues rather
    than failing them, because nothing is known to be wrong with the work."""
    released = await pool.fetch(
        """
        update jobs j set state = 'queued', locked_by = null, locked_at = null
        from hunts h
        where h.id = j.hunt_id and h.archived_at is null and h.locked_at is null
          and j.state = 'running'
          and j.locked_at < now() - ($1 || ' minutes')::interval
        returning j.id
        """,
        str(STALE_LOCK_MINUTES),
    )
    await audit.record(
        "job.release_locks",
        target_type="job",
        after={"released": len(released)},
    )
    return ActionResult(detail=f"Released {len(released)} stale lock(s)")


# ── Costs ────────────────────────────────────────────────────────────────────


@router.get("/costs", response_model=CostsReport, summary="Spend, three ways")
async def costs(
    admin: AdminUser,
    pool: DbPool,
    days: int = Query(14, ge=1, le=365),
) -> CostsReport:
    # asyncpg binds a text parameter; the cast happens in SQL.
    window = str(days)

    by_stage = await pool.fetch(
        """
        select c.stage as label,
               sum(c.llm_cost_usd) as llm, sum(c.fetch_cost_usd) as fetch,
               sum(c.llm_calls) as llm_calls, sum(c.fetch_calls) as fetch_calls
        from job_stage_costs c
        where c.updated_at > now() - ($1 || ' days')::interval
        group by c.stage
        having sum(c.llm_cost_usd + c.fetch_cost_usd) > 0
        order by sum(c.llm_cost_usd + c.fetch_cost_usd) desc
        """,
        window,
    )

    by_hunt = await pool.fetch(
        """
        select coalesce(h.name, 'unknown') as label,
               sum(c.llm_cost_usd) as llm, sum(c.fetch_cost_usd) as fetch,
               sum(c.llm_calls) as llm_calls, sum(c.fetch_calls) as fetch_calls
        from job_stage_costs c
        join jobs j on j.id = c.job_id
        left join hunts h on h.id = j.hunt_id
        where c.updated_at > now() - ($1 || ' days')::interval
        group by h.name
        having sum(c.llm_cost_usd + c.fetch_cost_usd) > 0
        order by sum(c.llm_cost_usd + c.fetch_cost_usd) desc
        """,
        window,
    )

    daily = await pool.fetch(
        """
        select date_trunc('day', c.updated_at)::date as day,
               sum(c.llm_cost_usd) as llm, sum(c.fetch_cost_usd) as fetch
        from job_stage_costs c
        where c.updated_at > now() - ($1 || ' days')::interval
        group by 1 order by 1
        """,
        window,
    )

    # Stage spend folded under each stage's *current* pin. See the module
    # docstring: useful, and explicitly not history.
    by_model: dict[str, dict[str, float]] = {}
    for row in by_stage:
        model = STAGE_MODELS.get(row["label"].lower(), "unpinned / deterministic")
        bucket = by_model.setdefault(model, {"llm": 0.0, "fetch": 0.0, "calls": 0.0})
        bucket["llm"] += float(row["llm"])
        bucket["fetch"] += float(row["fetch"])
        bucket["calls"] += int(row["llm_calls"] or 0)

    credits = await pool.fetch(
        "select provider, credits from tier3_credit_usage where month = date_trunc('month', now())"
    )

    def bucket(row: Any) -> SpendBucket:
        return SpendBucket(
            label=row["label"],
            llm_cost_usd=float(row["llm"]),
            fetch_cost_usd=float(row["fetch"]),
            total_cost_usd=float(row["llm"]) + float(row["fetch"]),
            llm_calls=int(row["llm_calls"] or 0),
            fetch_calls=int(row["fetch_calls"] or 0),
        )

    return CostsReport(
        days=days,
        by_stage=[bucket(row) for row in by_stage],
        by_hunt=[bucket(row) for row in by_hunt],
        by_model=sorted(
            (
                SpendBucket(
                    label=model,
                    llm_cost_usd=value["llm"],
                    fetch_cost_usd=value["fetch"],
                    total_cost_usd=value["llm"] + value["fetch"],
                    llm_calls=int(value["calls"]),
                    fetch_calls=0,
                )
                for model, value in by_model.items()
            ),
            key=lambda item: item.total_cost_usd,
            reverse=True,
        ),
        grouped_by_current_pin=True,
        daily=[
            SpendPoint(
                day=row["day"],
                llm_cost_usd=float(row["llm"]),
                fetch_cost_usd=float(row["fetch"]),
            )
            for row in daily
        ],
        tier3_credits_used=sum(int(row["credits"]) for row in credits),
        tier3_credits_allowance=TIER3_FREE_MONTHLY_CREDITS.get("brightdata"),
    )


# ── System ───────────────────────────────────────────────────────────────────


@router.get("/system", response_model=SystemReport, summary="Queue health and configuration")
async def system(admin: AdminUser, pool: DbPool) -> SystemReport:
    queue = await pool.fetchrow(
        """
        select
            count(*) filter (where state = 'queued')  as queued,
            count(*) filter (where state = 'running') as running,
            count(*) filter (where state = 'running'
                             and locked_at < now() - ($1 || ' minutes')::interval) as stale,
            (select extract(epoch from now() - min(created_at))
               from jobs where state = 'queued')      as oldest_queued_seconds,
            (select max(locked_at) from jobs where state = 'running') as last_heartbeat,
            count(*) filter (where finished_at > now() - interval '24 hours') as finished_24h,
            count(*) filter (where state = 'failed'
                             and finished_at > now() - interval '24 hours') as failed_24h
        from jobs
        """,
        str(STALE_LOCK_MINUTES),
    )
    migration = await pool.fetchval(
        "select version from supabase_migrations.schema_migrations order by version desc limit 1"
    )

    # Presence, never value — the convention the env probes already use.
    import os

    services = [
        {
            "name": "OpenRouter",
            "detail": "Every LLM call routes here",
            "configured": bool(os.environ.get("OPENROUTER_API_KEY")),
        },
        {
            # Key AND zone: a Web Unlocker with a key but no zone is not a
            # working tier 3, it is a 400 per request (§20 2026-08-11).
            "name": "Bright Data",
            "detail": f"Web Unlocker · tier 3 · ${TIER3_PRICES_USD.get('brightdata', 0):.4f}/req",
            "configured": provider_configured("brightdata"),
        },
        {
            "name": "Google Maps",
            "detail": "Geocoding · Places · ENRICH",
            "configured": bool(os.environ.get("GOOGLE_MAPS_API_KEY")),
        },
        {
            "name": "Langfuse",
            "detail": "Tracing — an untraced call is a bug (NFR6)",
            "configured": bool(os.environ.get("LANGFUSE_PUBLIC_KEY")),
        },
        {
            "name": "ScrapingBee",
            "detail": "Alternate tier-3 provider",
            "configured": provider_configured("scrapingbee"),
        },
    ]

    pins = []
    for stage in sorted(set(STAGE_MODELS)):
        try:
            model = model_for_stage(stage)
        except Exception:  # an env override naming an unpriced slug
            model = STAGE_MODELS[stage]
        price = MODEL_PRICES.get(model)
        pins.append(
            {
                "stage": stage,
                "model": model,
                "input_per_mtok": price[0] if price else None,
                "output_per_mtok": price[1] if price else None,
            }
        )

    return SystemReport(
        queued=queue["queued"],
        running=queue["running"],
        stale_locks=queue["stale"],
        oldest_queued_seconds=float(queue["oldest_queued_seconds"] or 0),
        last_heartbeat=queue["last_heartbeat"],
        finished_24h=queue["finished_24h"],
        failed_24h=queue["failed_24h"],
        last_migration=migration,
        model_pins=pins,
        services=services,
        priced_models=len(MODEL_PRICES),
        mode=os.environ.get("MANZIL_MODE", "workflow"),
    )
