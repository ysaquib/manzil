"""Admin router (AD-1, DESIGN §20 v3.39) — the panel's single choke point.

Every read here runs on the request-scoped asyncpg pool rather than the caller's
supabase client, because the whole point of these routes is to see across Hunts
the caller is not a member of. That makes this module the place where tenant
isolation stops being RLS's job and becomes the router's, which is exactly why
it is one small package with one gate (`require_site_admin`) and one ledger
(`AdminAudit`) instead of admin flags sprinkled through the domain routers.

`/admin/me` is the only route an ordinary account may call, and it answers
`is_site_admin: false` rather than 403 — the frontend asks it on every load to
decide whether to render the nav entry, and a 403 there would be noise in the
console for every non-admin user.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status
from manzil_shared.config import TIER3_FREE_MONTHLY_CREDITS

from manzil_api.admin.dependencies import AdminUser, Audit, NotSiteAdmin
from manzil_api.admin.schemas import (
    ActivityEntry,
    AdminIdentity,
    AdminSummary,
    AuditEntry,
    FeedbackCounts,
    FeedbackReport,
    FeedbackTriageUpdate,
    GrantAdmin,
    HuntSummary,
)
from manzil_api.dependencies import CurrentUser, DbPool
from manzil_api.exceptions import ManzilAPIError

router = APIRouter(prefix="/admin", tags=["admin"])


class PrimordialAdminProtected(ManzilAPIError):
    status_code = status.HTTP_409_CONFLICT
    code = "primordial_admin_protected"


class CannotRevokeSelf(ManzilAPIError):
    status_code = status.HTTP_409_CONFLICT
    code = "cannot_revoke_self"


class FeedbackNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "feedback_not_found"


@router.get("/me", response_model=AdminIdentity, summary="Is the caller a site admin?")
async def whoami(user: CurrentUser, pool: DbPool) -> AdminIdentity:
    row = await pool.fetchrow(
        "select is_primordial, granted_at from site_admins where user_id = $1", UUID(user.id)
    )
    return AdminIdentity(
        user_id=UUID(user.id),
        is_site_admin=row is not None,
        is_primordial=bool(row and row["is_primordial"]),
        granted_at=row["granted_at"] if row else None,
    )


@router.get("/summary", response_model=AdminSummary, summary="Overview counters")
async def summary(admin: AdminUser, pool: DbPool) -> AdminSummary:
    row = await pool.fetchrow(
        """
        select
            (select count(*) from auth.users)                            as users,
            (select count(*) from hunts)                                 as hunts,
            (select count(*) from hunt_listings)                         as listings,
            (select count(*) from jobs where state = 'failed')           as jobs_failed,
            (select count(*) from jobs)                                  as jobs_total,
            (select coalesce(sum(cost_actual_usd), 0) from jobs
              where finished_at > now() - interval '30 days')            as spend_30d,
            (select coalesce(sum(credits), 0) from tier3_credit_usage
              where month = date_trunc('month', now()))                  as credits_used,
            (select count(*) from feedback where triage = 'new')          as feedback_new
        """
    )
    return AdminSummary(
        users=row["users"],
        hunts=row["hunts"],
        listings=row["listings"],
        jobs_failed=row["jobs_failed"],
        jobs_total=row["jobs_total"],
        spend_usd_30d=float(row["spend_30d"]),
        tier3_credits_used=int(row["credits_used"]),
        # The allowance is per provider; the panel shows the configured one.
        tier3_credits_allowance=TIER3_FREE_MONTHLY_CREDITS.get("brightdata"),
        feedback_new=row["feedback_new"],
    )


@router.get("/hunts", response_model=list[HuntSummary], summary="Every Hunt with roll-ups")
async def list_hunts(admin: AdminUser, pool: DbPool) -> list[HuntSummary]:
    rows = await pool.fetch(
        """
        select
            h.id as hunt_id, h.name, h.owner_id, h.created_at,
            up.default_display_name as owner_name,
            (select count(*) from hunt_members m where m.hunt_id = h.id)   as members,
            (select count(*) from hunt_listings l where l.hunt_id = h.id)  as listings,
            (select count(*) from jobs j where j.hunt_id = h.id)           as jobs,
            coalesce(c.llm, 0)   as llm_cost,
            coalesce(c.fetch, 0) as fetch_cost,
            (select max(j.finished_at) from jobs j where j.hunt_id = h.id) as last_activity_at
        from hunts h
        left join user_profiles up on up.user_id = h.owner_id
        left join lateral (
            select sum(sc.llm_cost_usd) as llm, sum(sc.fetch_cost_usd) as fetch
            from job_stage_costs sc
            join jobs j on j.id = sc.job_id
            where j.hunt_id = h.id
        ) c on true
        order by (coalesce(c.llm, 0) + coalesce(c.fetch, 0)) desc, h.created_at desc
        """
    )
    return [
        HuntSummary(
            hunt_id=row["hunt_id"],
            name=row["name"],
            owner_id=row["owner_id"],
            owner_name=row["owner_name"],
            members=row["members"],
            listings=row["listings"],
            jobs=row["jobs"],
            llm_cost_usd=float(row["llm_cost"]),
            fetch_cost_usd=float(row["fetch_cost"]),
            total_cost_usd=float(row["llm_cost"]) + float(row["fetch_cost"]),
            created_at=row["created_at"],
            last_activity_at=row["last_activity_at"],
        )
        for row in rows
    ]


@router.get(
    "/hunts/{hunt_id}/activity",
    response_model=list[ActivityEntry],
    summary="A Hunt's activity feed",
)
async def hunt_activity(
    hunt_id: UUID,
    admin: AdminUser,
    pool: DbPool,
    limit: int = Query(100, ge=1, le=500),
) -> list[ActivityEntry]:
    """Reads `hunt_activity` (AD-F), whose own gate already admits Site Admins —
    so this route adds pagination, not permission."""
    rows = await pool.fetch(
        "select * from hunt_activity where hunt_id = $1 order by occurred_at desc limit $2",
        hunt_id,
        limit,
    )
    return [ActivityEntry(**dict(row)) for row in rows]


@router.get("/audit", response_model=list[AuditEntry], summary="Admin audit log")
async def audit_log(
    admin: AdminUser,
    pool: DbPool,
    limit: int = Query(100, ge=1, le=500),
) -> list[AuditEntry]:
    rows = await pool.fetch(
        "select id, admin_user_id, action, target_type, target_id, target_label, "
        "hunt_id, via_ghost_view, occurred_at "
        "from admin_audit_log order by occurred_at desc limit $1",
        limit,
    )
    return [AuditEntry(**dict(row)) for row in rows]


@router.post(
    "/admins",
    response_model=AdminIdentity,
    status_code=status.HTTP_201_CREATED,
    summary="Grant site admin",
)
async def grant_admin(
    body: GrantAdmin, admin: AdminUser, pool: DbPool, audit: Audit
) -> AdminIdentity:
    row = await pool.fetchrow(
        """
        insert into site_admins (user_id, granted_by, note) values ($1, $2, $3)
        on conflict (user_id) do update set note = excluded.note
        returning is_primordial, granted_at
        """,
        body.user_id,
        UUID(admin.id),
        body.note,
    )
    await audit.record(
        "admin.grant",
        target_type="user",
        target_id=body.user_id,
        after={"note": body.note},
    )
    return AdminIdentity(
        user_id=body.user_id,
        is_site_admin=True,
        is_primordial=row["is_primordial"],
        granted_at=row["granted_at"],
    )


@router.delete(
    "/admins/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke site admin",
)
async def revoke_admin(user_id: UUID, admin: AdminUser, pool: DbPool, audit: Audit) -> None:
    # Both refusals are re-asserted in the database (the primordial trigger, and
    # nothing at all for self-revocation). These checks exist to return a useful
    # status code instead of a raw constraint error — they are not the boundary.
    if str(user_id) == admin.id:
        raise CannotRevokeSelf("An admin cannot revoke their own access")
    is_primordial = await pool.fetchval(
        "select is_primordial from site_admins where user_id = $1", user_id
    )
    if is_primordial:
        raise PrimordialAdminProtected(
            "The primordial site admin owns the application and cannot be revoked"
        )
    await pool.execute("delete from site_admins where user_id = $1", user_id)
    await audit.record("admin.revoke", target_type="user", target_id=user_id)


# ── feedback inbox (AD-2) ────────────────────────────────────────────────────
# `feedback` has had no SELECT policy since P3-16 — the migration that created it
# said in as many words that reads "belong to an operator holding service_role".
# These two routes are that operator. The reporter's email is joined from
# auth.users here rather than stored on the row, so deleting an account still
# removes it from the inbox's view of the world.


@router.get("/feedback", response_model=list[FeedbackReport], summary="Feedback inbox")
async def list_feedback(
    admin: AdminUser,
    pool: DbPool,
    triage: str | None = Query(None, pattern="^(new|seen|actioned|wont_fix)$"),
    category: str | None = Query(None, max_length=20),
    limit: int = Query(100, ge=1, le=500),
) -> list[FeedbackReport]:
    rows = await pool.fetch(
        """
        select
            f.id, f.category, f.body, f.route, f.hunt_id, f.app_version, f.user_agent,
            f.user_id as reporter_id, f.triage, f.triaged_at, f.created_at,
            h.name as hunt_name,
            up.default_display_name as reporter_name,
            u.email as reporter_email
        from feedback f
        left join hunts h on h.id = f.hunt_id
        left join user_profiles up on up.user_id = f.user_id
        left join auth.users u on u.id = f.user_id
        where ($1::text is null or f.triage = $1)
          and ($2::text is null or f.category = $2)
        order by f.created_at desc
        limit $3
        """,
        triage,
        category,
        limit,
    )
    return [FeedbackReport(**dict(row)) for row in rows]


@router.get("/feedback/counts", response_model=FeedbackCounts, summary="Inbox counts by state")
async def feedback_counts(admin: AdminUser, pool: DbPool) -> FeedbackCounts:
    rows = await pool.fetch("select triage, count(*) as n from feedback group by triage")
    return FeedbackCounts(**{row["triage"]: row["n"] for row in rows})


@router.patch(
    "/feedback/{feedback_id}",
    response_model=FeedbackReport,
    summary="Set a report's triage state",
)
async def set_feedback_triage(
    feedback_id: UUID,
    body: FeedbackTriageUpdate,
    admin: AdminUser,
    pool: DbPool,
    audit: Audit,
) -> FeedbackReport:
    previous = await pool.fetchval("select triage from feedback where id = $1", feedback_id)
    if previous is None:
        raise FeedbackNotFound("No such feedback report")

    row = await pool.fetchrow(
        """
        update feedback
        set triage = $2, triaged_at = now(), triaged_by = $3
        where id = $1
        returning id, category, body, route, hunt_id, app_version, user_agent,
                  user_id as reporter_id, triage, triaged_at, created_at
        """,
        feedback_id,
        body.triage,
        UUID(admin.id),
    )
    await audit.record(
        "feedback.triage",
        target_type="feedback",
        target_id=feedback_id,
        hunt_id=row["hunt_id"],
        before={"triage": previous},
        after={"triage": body.triage},
    )
    return FeedbackReport(**dict(row))


__all__ = ["NotSiteAdmin", "router"]
