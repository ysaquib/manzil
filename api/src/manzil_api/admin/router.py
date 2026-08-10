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

import json
import logging
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Query, status
from manzil_shared.config import TIER3_FREE_MONTHLY_CREDITS
from pydantic import BaseModel

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
    HuntOption,
    HuntPage,
    HuntSummary,
)
from manzil_api.demo.router import reset_config_cache
from manzil_api.dependencies import CurrentUser, DbPool
from manzil_api.exceptions import ManzilAPIError

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger("manzil_api")


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


@router.get("/hunts", response_model=HuntPage, summary="A page of Hunts with roll-ups")
async def list_hunts(
    admin: AdminUser,
    pool: DbPool,
    search: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=250),
    offset: int = Query(0, ge=0),
) -> HuntPage:
    """One page of the Hunt table, ordered by spend.

    The shape of this query is the whole point. The obvious version — five
    correlated subqueries in the target list, ``order by`` the cost lateral,
    ``limit`` on the end — makes Postgres compute every roll-up for every Hunt
    in the installation and then throw all but fifty away, because a Sort node
    carries an already-evaluated target list. So the page is chosen first, on
    the ordering key alone, and the four per-row counts are joined on afterwards
    against the fifty rows that survived.

    The cost aggregate still spans every matching Hunt, and that is inherent:
    "most expensive first" cannot be answered without pricing the candidates.
    It is one grouped join rather than a lateral per row, which is the version
    of that cost worth paying.
    """
    rows = await pool.fetch(
        """
        with filtered as (
            select h.id, h.name, h.owner_id, h.created_at,
                   up.default_display_name as owner_name
            from hunts h
            left join user_profiles up on up.user_id = h.owner_id
            where $1::text is null
               or h.name ilike '%' || $1 || '%'
               or up.default_display_name ilike '%' || $1 || '%'
        ),
        costs as (
            select f.id,
                   coalesce(sum(sc.llm_cost_usd), 0)   as llm,
                   coalesce(sum(sc.fetch_cost_usd), 0) as fetch
            from filtered f
            left join jobs j on j.hunt_id = f.id
            left join job_stage_costs sc on sc.job_id = j.id
            group by f.id
        ),
        page as (
            select f.*, c.llm, c.fetch
            from filtered f
            join costs c on c.id = f.id
            order by (c.llm + c.fetch) desc, f.created_at desc
            limit $2 offset $3
        )
        select
            p.id as hunt_id, p.name, p.owner_id, p.owner_name, p.created_at,
            p.llm as llm_cost, p.fetch as fetch_cost,
            (select count(*) from hunt_members m where m.hunt_id = p.id)   as members,
            (select count(*) from hunt_listings l where l.hunt_id = p.id)  as listings,
            (select count(*) from jobs j where j.hunt_id = p.id)           as jobs,
            (select max(j.finished_at) from jobs j where j.hunt_id = p.id) as last_activity_at,
            (select count(*) from filtered)                                as total
        from page p
        order by (p.llm + p.fetch) desc, p.created_at desc
        """,
        search,
        limit,
        offset,
    )
    # `total` rides on every row, so an empty page carries no count — ask
    # separately only in that case rather than paying for a second query on
    # every request.
    if rows:
        total = rows[0]["total"]
    else:
        total = await pool.fetchval(
            """
            select count(*)
            from hunts h
            left join user_profiles up on up.user_id = h.owner_id
            where $1::text is null
               or h.name ilike '%' || $1 || '%'
               or up.default_display_name ilike '%' || $1 || '%'
            """,
            search,
        )
    return HuntPage(
        total=total,
        items=[
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
        ],
    )


@router.get(
    "/hunts/options",
    response_model=list[HuntOption],
    summary="Hunt typeahead suggestions",
)
async def hunt_options(
    admin: AdminUser,
    pool: DbPool,
    q: str = Query(min_length=3, max_length=200),
    limit: int = Query(20, ge=1, le=50),
) -> list[HuntOption]:
    """Name/owner prefix search for Hunt pickers.

    ``q`` is required and floored at three characters by the signature rather
    than by the caller: an admin picking a Hunt out of a six-figure table must
    not be able to ask for "all of them", however the frontend is written. The
    ceiling on ``limit`` is the same argument from the other end.
    """
    rows = await pool.fetch(
        """
        select h.id as hunt_id, h.name, up.default_display_name as owner_name
        from hunts h
        left join user_profiles up on up.user_id = h.owner_id
        where h.name ilike '%' || $1 || '%'
           or up.default_display_name ilike '%' || $1 || '%'
        order by h.name
        limit $2
        """,
        q,
        limit,
    )
    return [HuntOption(**dict(row)) for row in rows]


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
    """Read the internal AD-F union after the live ``AdminUser`` check above.

    The raw union deliberately has no PostgREST grant. Hunt Owners use the
    bounded ``get_hunt_activity`` RPC; this service-role route is the separate
    Site Admin boundary.
    """
    rows = await pool.fetch(
        "select * from private.hunt_activity_all "
        "where hunt_id = $1 order by occurred_at desc limit $2",
        hunt_id,
        limit,
    )
    entries: list[ActivityEntry] = []
    for row in rows:
        values = dict(row)
        # This pool intentionally has no process-global jsonb codec. Keep the
        # database's structured contract at the API boundary instead of
        # returning a JSON-encoded string inside JSON.
        if isinstance(values["detail"], str):
            values["detail"] = json.loads(values["detail"])
        entries.append(ActivityEntry(**values))
    return entries


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


class DemoToggle(BaseModel):
    enabled: bool


class DemoPreflightFailed(ManzilAPIError):
    status_code = status.HTTP_409_CONFLICT
    code = "demo_preflight_failed"


@router.get("/demo", summary="Demo mode status and preflight")
async def demo_status(admin: AdminUser, pool: DbPool) -> dict:
    """Whether the demo is on, and what currently stands in the way of turning
    it on. Surfacing the blockers is the point: an operator should be able to
    see why the switch will refuse before they flip it."""
    row = await pool.fetchrow("select demo_enabled, demo_hunt_id, updated_at from site_settings")
    problems = await pool.fetchval("select private.demo_preflight()")
    return {
        "enabled": bool(row["demo_enabled"]),
        "hunt_id": str(row["demo_hunt_id"]) if row["demo_hunt_id"] else None,
        "updated_at": row["updated_at"],
        "blockers": list(problems or []),
    }


@router.patch("/demo", summary="Enable or disable public demo mode")
async def set_demo(body: DemoToggle, admin: AdminUser, pool: DbPool, audit: Audit) -> dict:
    """The kill switch.

    Enabling runs `private.demo_preflight()` inside the same transaction as the
    update, so the demo cannot be switched on while an unguarded table or a
    writable view exists. Disabling never preflights -- an emergency shutoff
    must not be blocked by the conditions that made it an emergency.

    The two directions also differ in how they treat the Admin Audit Log, and
    the asymmetry is deliberate (R2 H4, DESIGN §20). **Enabling** commits the
    setting and its audit entry in one transaction: making the app publicly
    reachable with no record of who did it is not an acceptable outcome, and if
    the ledger is unavailable the safe answer is to stay private. **Disabling**
    commits the setting first and audits afterwards, because the one thing worse
    than an unaudited shutoff is a shutoff that a failing audit table can
    refuse. A failure there is logged loudly rather than raised.

    Either way `set_demo_enabled` rotates `demo_generation`, so every token
    issued before this call stops working -- a disable is a revocation, not a
    pause.
    """
    previous = await pool.fetchval("select demo_enabled from site_settings")
    actor = UUID(admin.id)

    if body.enabled:
        async with pool.acquire() as conn, conn.transaction():
            try:
                await conn.fetchval("select set_demo_enabled($1, $2)", True, actor)
            except asyncpg.InsufficientPrivilegeError as exc:
                raise DemoPreflightFailed(
                    f"Demo mode cannot be enabled: {exc.detail or exc}"
                ) from exc
            await audit.record(
                "demo.toggle",
                target_type="site_settings",
                before={"demo_enabled": previous},
                after={"demo_enabled": True},
                conn=conn,
            )
    else:
        await pool.fetchval("select set_demo_enabled($1, $2)", False, actor)
        try:
            await audit.record(
                "demo.toggle",
                target_type="site_settings",
                before={"demo_enabled": previous},
                after={"demo_enabled": False},
            )
        except Exception:  # the shutoff already succeeded; never re-raise
            logger.error(
                "Demo mode was disabled by %s but the audit entry failed to "
                "write. The shutoff stands; reconcile the ledger by hand.",
                actor,
                exc_info=True,
            )

    reset_config_cache()
    return {"enabled": body.enabled}


__all__ = ["NotSiteAdmin", "router"]
