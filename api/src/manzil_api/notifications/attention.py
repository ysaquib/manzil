"""Hunt attention: the recent-job severity summary behind the Tasks navbar dot
and the Ghost View equivalent (`notifications/router.py`, `admin/hunt_operations.py`).

The failed-task indicator looks back only over the Hunt's most recent Jobs,
not its entire history, so one long-past failure does not keep the navbar red
forever after it has been dealt with. The window scales with how much Job
traffic a Hunt actually produces -- twice its active Listing count -- clamped
to a floor and a ceiling: never so small that one ordinary retry cycle
outruns it, never so large that a huge Hunt scans unbounded history for one
flag (DESIGN §20 2026-08-25).
"""

from __future__ import annotations

from uuid import UUID

import asyncpg

from manzil_api.notifications.schemas import AttentionResponse

ATTENTION_WINDOW_MIN = 8
ATTENTION_WINDOW_MAX = 64
ATTENTION_WINDOW_PER_LISTING = 2


def attention_window(active_listings: int) -> int:
    """Recent-Job lookback for attention severity.

    `ATTENTION_WINDOW_PER_LISTING` Jobs per active Listing, clamped to
    [`ATTENTION_WINDOW_MIN`, `ATTENTION_WINDOW_MAX`].
    """
    return max(
        ATTENTION_WINDOW_MIN,
        min(ATTENTION_WINDOW_PER_LISTING * active_listings, ATTENTION_WINDOW_MAX),
    )


async def fetch_hunt_attention(pool: asyncpg.Pool, hunt_id: UUID) -> AttentionResponse:
    active_listings = await pool.fetchval(
        "select count(*) from hunt_listings where hunt_id = $1 and status = 'active'",
        hunt_id,
    )
    window = attention_window(int(active_listings or 0))
    counts = await pool.fetchrow(
        """
        with recent as (
            select state from jobs
            where hunt_id = $1
            order by created_at desc
            limit $2
        )
        select count(*) filter (where state = 'failed') as failed,
               count(*) filter (where state = 'waiting_user') as waiting_user,
               count(*) filter (where state = 'running') as running
        from recent
        """,
        hunt_id,
        window,
    )
    failed, waiting, running = (int(counts[key]) for key in ("failed", "waiting_user", "running"))
    task_status = (
        "failed" if failed else "waiting_user" if waiting else "running" if running else None
    )
    return AttentionResponse(
        waiting_checkpoint_count=waiting,
        failed=failed,
        waiting_user=waiting,
        running=running,
        task_status=task_status,
    )
