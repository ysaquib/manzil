"""Hunt-scoped operational usage and spend statistics."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from manzil_api.analytics import calendar_window
from manzil_api.dependencies import CurrentUser, DbPool
from manzil_api.exceptions import ManzilAPIError
from manzil_api.hunts.exceptions import HuntNotFound

router = APIRouter(tags=["statistics"])
STATISTICS_WINDOWS = frozenset({7, 14, 30, 90, 365})


class InvalidStatisticsWindow(ManzilAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_statistics_window"


class HuntStatisticsSummary(BaseModel):
    billed_cost_usd: float
    deleted_cost_usd: float
    listing_submissions: int
    jobs_completed: int
    jobs_failed: int
    llm_calls: int
    fetch_calls: int


class HuntStatisticsPoint(BaseModel):
    day: date
    billed_cost_usd: float = 0.0
    deleted_cost_usd: float = 0.0
    listing_submissions: int = 0
    jobs_completed: int = 0
    jobs_failed: int = 0
    llm_calls: int = 0
    fetch_calls: int = 0


class HuntStatisticsReport(BaseModel):
    days: int
    timezone: str
    summary: HuntStatisticsSummary
    daily: list[HuntStatisticsPoint] = Field(default_factory=list)


@router.get(
    "/hunts/{hunt_id}/statistics",
    response_model=HuntStatisticsReport,
    summary="Hunt spend and operational usage",
)
async def hunt_statistics(
    hunt_id: UUID,
    user: CurrentUser,
    pool: DbPool,
    days: int = Query(30),
    timezone: str = Query("UTC", min_length=1, max_length=100),
) -> HuntStatisticsReport:
    if days not in STATISTICS_WINDOWS:
        raise InvalidStatisticsWindow("days must be one of 7, 14, 30, 90, or 365")
    # Deliberately explicit rather than leaning on the direct pool's privileges:
    # every member reads their Hunt; a Site Admin may read it in Ghost View.
    authorized = await pool.fetchval(
        """
        select exists (select 1 from hunts where id = $1)
           and (
               exists (select 1 from hunt_members where hunt_id = $1 and user_id = $2)
               or exists (select 1 from site_admins where user_id = $2)
           )
        """,
        hunt_id,
        UUID(user.id),
    )
    if user.is_demo or not authorized:
        raise HuntNotFound("Hunt not found")

    start, end, labels = calendar_window(days, timezone)
    job_rows = await pool.fetch(
        """
        select (coalesce(finished_at, started_at, created_at) at time zone $4)::date as day,
               coalesce(sum(cost_actual_usd), 0) as billed,
               coalesce(sum(cost_actual_usd) filter (where state = 'deleted'), 0) as deleted,
               count(*) filter (where state = 'done'
                    or (state = 'deleted' and deleted_from_state = 'done')) as completed,
               count(*) filter (where state = 'failed'
                    or (state = 'deleted' and deleted_from_state = 'failed')) as failed
         from jobs
         where hunt_id = $1
           and coalesce(finished_at, started_at, created_at) >= $2
           and coalesce(finished_at, started_at, created_at) < $3
         group by 1 order by 1
        """,
        hunt_id,
        start,
        end,
        timezone,
    )
    submission_rows = await pool.fetch(
        """
        select (created_at at time zone $4)::date as day, count(*) as submissions
          from jobs
         where hunt_id = $1 and type = 'ingest'
           and created_at >= $2 and created_at < $3
         group by 1 order by 1
        """,
        hunt_id,
        start,
        end,
        timezone,
    )
    call_rows = await pool.fetch(
        """
        select (c.updated_at at time zone $4)::date as day,
               coalesce(sum(c.llm_calls), 0) as llm_calls,
               coalesce(sum(c.fetch_calls), 0) as fetch_calls
          from job_stage_costs c join jobs j on j.id = c.job_id
         where j.hunt_id = $1 and c.updated_at >= $2 and c.updated_at < $3
         group by 1 order by 1
        """,
        hunt_id,
        start,
        end,
        timezone,
    )

    points = {label: HuntStatisticsPoint(day=label) for label in labels}
    for row in job_rows:
        point = points[row["day"]]
        point.billed_cost_usd = float(row["billed"] or 0)
        point.deleted_cost_usd = float(row["deleted"] or 0)
        point.jobs_completed = int(row["completed"] or 0)
        point.jobs_failed = int(row["failed"] or 0)
    for row in submission_rows:
        points[row["day"]].listing_submissions = int(row["submissions"] or 0)
    for row in call_rows:
        point = points[row["day"]]
        point.llm_calls = int(row["llm_calls"] or 0)
        point.fetch_calls = int(row["fetch_calls"] or 0)

    daily = list(points.values())
    return HuntStatisticsReport(
        days=days,
        timezone=timezone,
        summary=HuntStatisticsSummary(
            billed_cost_usd=sum(point.billed_cost_usd for point in daily),
            deleted_cost_usd=sum(point.deleted_cost_usd for point in daily),
            listing_submissions=sum(point.listing_submissions for point in daily),
            jobs_completed=sum(point.jobs_completed for point in daily),
            jobs_failed=sum(point.jobs_failed for point in daily),
            llm_calls=sum(point.llm_calls for point in daily),
            fetch_calls=sum(point.fetch_calls for point in daily),
        ),
        daily=daily,
    )
