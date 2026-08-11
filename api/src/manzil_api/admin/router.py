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
from datetime import UTC, datetime
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
    HuntDelete,
    HuntDeleteResult,
    HuntLockUpdate,
    HuntManagement,
    HuntManagementMember,
    HuntOption,
    HuntPage,
    HuntSummary,
)
from manzil_api.collaboration.exceptions import TransferTargetNotMember
from manzil_api.collaboration.schemas import TransferOwnershipRequest, TransferOwnershipResponse
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


class AdminHuntNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "admin_hunt_not_found"


class HuntDeletionBlocked(ManzilAPIError):
    status_code = status.HTTP_409_CONFLICT
    code = "hunt_deletion_blocked"


class HuntConfirmationMismatch(ManzilAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "hunt_confirmation_mismatch"


class AdminHuntLocked(ManzilAPIError):
    status_code = status.HTTP_423_LOCKED
    code = "hunt_locked"


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
            -- Same accumulator as the Tasks tab and the Hunt table's total.
            -- Dated by `coalesce(finished_at, started_at, created_at)` because
            -- a Job that is still running, or parked at a checkpoint, has
            -- already spent money and has no `finished_at` to be counted by
            -- (DESIGN §20 v3.80).
            (select coalesce(sum(cost_actual_usd), 0) from jobs
              where coalesce(finished_at, started_at, created_at)
                    > now() - interval '30 days')                        as spend_30d,
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

    **What "cost" means here** (DESIGN §20 v3.80). The Hunt's total is
    `sum(jobs.cost_actual_usd)` — the same accumulator every Job card in Tasks
    shows, and the whole bill including re-run Stage attempts. The llm/fetch
    split comes from `job_stage_costs`, whose rows are *replaced* when a Stage
    re-runs (v3.37), so the split can be smaller than the total; the remainder
    is reported as `unattributed_cost_usd` rather than quietly shrinking the
    number. The two are summed in separate CTEs on purpose: one join carrying
    both would multiply each Job's total by its Stage-row count.
    """
    rows = await pool.fetch(
        """
        with filtered as (
            select h.id, h.name, h.owner_id, h.created_at, h.archived_at, h.locked_at,
                   up.default_display_name as owner_name
            from hunts h
            left join user_profiles up on up.user_id = h.owner_id
            where $1::text is null
               or h.name ilike '%' || $1 || '%'
               or up.default_display_name ilike '%' || $1 || '%'
        ),
        billed as (
            select j.hunt_id as id, coalesce(sum(j.cost_actual_usd), 0) as billed
            from jobs j join filtered f on f.id = j.hunt_id
            group by j.hunt_id
        ),
        split as (
            select j.hunt_id as id,
                   coalesce(sum(sc.llm_cost_usd), 0)   as llm,
                   coalesce(sum(sc.fetch_cost_usd), 0) as fetch
            from jobs j
            join filtered f on f.id = j.hunt_id
            join job_stage_costs sc on sc.job_id = j.id
            group by j.hunt_id
        ),
        page as (
            select f.*,
                   coalesce(b.billed, 0) as billed,
                   coalesce(s.llm, 0)    as llm,
                   coalesce(s.fetch, 0)  as fetch
            from filtered f
            left join billed b on b.id = f.id
            left join split s on s.id = f.id
            order by coalesce(b.billed, 0) desc, f.created_at desc
            limit $2 offset $3
        )
        select
            p.id as hunt_id, p.name, p.owner_id, p.owner_name, p.created_at,
            p.archived_at, p.locked_at,
            p.billed as billed_cost, p.llm as llm_cost, p.fetch as fetch_cost,
            (select count(*) from hunt_members m where m.hunt_id = p.id)   as members,
            (select count(*) from hunt_listings l where l.hunt_id = p.id)  as listings,
            (select count(*) from jobs j where j.hunt_id = p.id)           as jobs,
            (select max(j.finished_at) from jobs j where j.hunt_id = p.id) as last_activity_at,
            (select count(*) from filtered)                                as total
        from page p
        order by p.billed desc, p.created_at desc
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
                total_cost_usd=float(row["billed_cost"]),
                unattributed_cost_usd=max(
                    float(row["billed_cost"]) - float(row["llm_cost"]) - float(row["fetch_cost"]),
                    0.0,
                ),
                created_at=row["created_at"],
                last_activity_at=row["last_activity_at"],
                archived_at=row["archived_at"],
                locked_at=row["locked_at"],
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
    "/hunts/{hunt_id}/management",
    response_model=HuntManagement,
    summary="Members and safety state for Hunt administration",
)
async def hunt_management(hunt_id: UUID, admin: AdminUser, pool: DbPool) -> HuntManagement:
    hunt = await pool.fetchrow(
        """
        select h.id, h.name, h.owner_id, h.archived_at, h.locked_at, h.locked_by,
               coalesce(hm.display_name, up.default_display_name, 'Member') as owner_name,
               exists (
                   select 1 from hunt_members mine
                   where mine.hunt_id = h.id and mine.user_id = $2
               ) as caller_is_member
        from hunts h
        join hunt_members hm
          on hm.hunt_id = h.id and hm.user_id = h.owner_id and hm.role = 'owner'
        left join user_profiles up on up.user_id = h.owner_id
        where h.id = $1
        """,
        hunt_id,
        UUID(admin.id),
    )
    if hunt is None:
        raise AdminHuntNotFound("Hunt not found")

    rows = await pool.fetch(
        """
        select hm.user_id,
               coalesce(hm.display_name, up.default_display_name, 'Member') as display_name,
               hm.role::text as role
        from hunt_members hm
        left join user_profiles up on up.user_id = hm.user_id
        where hm.hunt_id = $1
        order by case hm.role when 'owner' then 0 when 'curator' then 1 else 2 end,
                 coalesce(hm.display_name, up.default_display_name, 'Member')
        """,
        hunt_id,
    )
    active_jobs = await pool.fetchval(
        "select count(*) from jobs where hunt_id=$1 "
        "and state in ('queued', 'running', 'waiting_user')",
        hunt_id,
    )
    selected_demo = await pool.fetchval(
        "select exists(select 1 from site_settings where demo_hunt_id=$1)", hunt_id
    )
    blockers: list[str] = []
    if selected_demo:
        blockers.append("Selected Demo Hunt — select another Hunt in Demo Mode first")
    if active_jobs:
        job_word = "Jobs" if active_jobs != 1 else "Job"
        blockers.append(f"{active_jobs} active {job_word} must finish or be cancelled first")

    return HuntManagement(
        hunt_id=hunt["id"],
        name=hunt["name"],
        owner_id=hunt["owner_id"],
        owner_name=hunt["owner_name"],
        caller_is_member=hunt["caller_is_member"],
        archived_at=hunt["archived_at"],
        locked_at=hunt["locked_at"],
        locked_by=hunt["locked_by"],
        members=[HuntManagementMember(**dict(row)) for row in rows],
        deletion_blockers=blockers,
    )


@router.post(
    "/hunts/{hunt_id}/transfer-ownership",
    response_model=TransferOwnershipResponse,
    summary="Transfer a Hunt to an existing member",
)
async def transfer_admin_hunt_ownership(
    hunt_id: UUID,
    body: TransferOwnershipRequest,
    admin: AdminUser,
    pool: DbPool,
    audit: Audit,
) -> TransferOwnershipResponse:
    async with pool.acquire() as connection, connection.transaction():
        hunt = await connection.fetchrow(
            "select name, owner_id, locked_at from hunts where id=$1 for update", hunt_id
        )
        if hunt is None:
            raise AdminHuntNotFound("Hunt not found")
        if hunt["locked_at"] is not None:
            raise AdminHuntLocked("Unlock this Hunt before transferring ownership")
        target = await connection.fetchrow(
            """
            select coalesce(hm.display_name, up.default_display_name, 'Member') as display_name
            from hunt_members hm
            left join user_profiles up on up.user_id = hm.user_id
            where hm.hunt_id=$1 and hm.user_id=$2
            """,
            hunt_id,
            body.new_owner_id,
        )
        if target is None:
            raise TransferTargetNotMember("The new Owner must already be a member of the Hunt")

        await connection.execute("select set_config('request.jwt.claim.sub', $1, true)", admin.id)
        result = await connection.fetchval(
            "select transfer_hunt_ownership($1::uuid, $2::uuid)",
            hunt_id,
            body.new_owner_id,
        )
        if isinstance(result, str):
            result = json.loads(result)
        if result.get("status") != "ok":
            raise TransferTargetNotMember("The new Owner must already be a member of the Hunt")
        await audit.record(
            "hunt.ownership.transfer",
            target_type="hunt",
            target_id=hunt_id,
            target_label=hunt["name"],
            hunt_id=hunt_id,
            before={"owner_id": str(hunt["owner_id"])},
            after={
                "owner_id": str(body.new_owner_id),
                "owner_name": target["display_name"],
            },
            conn=connection,
        )
    return TransferOwnershipResponse(status="ok")


@router.delete(
    "/hunts/{hunt_id}",
    response_model=HuntDeleteResult,
    summary="Permanently delete a Hunt and its Hunt-scoped data",
)
async def delete_admin_hunt(
    hunt_id: UUID,
    body: HuntDelete,
    admin: AdminUser,
    pool: DbPool,
    audit: Audit,
) -> HuntDeleteResult:
    async with pool.acquire() as connection, connection.transaction():
        hunt = await connection.fetchrow(
            "select name, owner_id, locked_at from hunts where id=$1 for update", hunt_id
        )
        if hunt is None:
            raise AdminHuntNotFound("Hunt not found")
        if hunt["locked_at"] is not None:
            raise AdminHuntLocked("Unlock this Hunt before permanently deleting it")
        if body.confirmation_name != hunt["name"]:
            raise HuntConfirmationMismatch("Type the exact Hunt name to confirm deletion")
        if await connection.fetchval(
            "select exists(select 1 from site_settings where demo_hunt_id=$1)", hunt_id
        ):
            raise HuntDeletionBlocked(
                "The selected Demo Hunt cannot be deleted; select another Hunt in Demo Mode first"
            )

        active_jobs = await connection.fetch(
            "select id from jobs where hunt_id=$1 "
            "and state in ('queued', 'running', 'waiting_user') for update",
            hunt_id,
        )
        if active_jobs:
            raise HuntDeletionBlocked(
                f"{len(active_jobs)} active Job{'s' if len(active_jobs) != 1 else ''} "
                "must finish or be cancelled first"
            )

        impact = await connection.fetchrow(
            """
            select
                (select count(*) from hunt_members where hunt_id=$1) as members,
                (select count(*) from hunt_listings where hunt_id=$1) as listings,
                (select count(*) from jobs where hunt_id=$1) as jobs,
                (select count(*) from visits where hunt_id=$1) as visits
            """,
            hunt_id,
        )
        result = HuntDeleteResult(
            hunt_id=hunt_id,
            name=hunt["name"],
            members=impact["members"],
            listings=impact["listings"],
            jobs=impact["jobs"],
            visits=impact["visits"],
        )

        await connection.execute("select set_config('request.jwt.claim.sub', $1, true)", admin.id)
        await connection.execute("delete from hunts where id=$1", hunt_id)
        await audit.record(
            "hunt.permanent_delete",
            target_type="hunt",
            target_id=hunt_id,
            target_label=hunt["name"],
            hunt_id=hunt_id,
            before={
                "owner_id": str(hunt["owner_id"]),
                "counts": {
                    "members": result.members,
                    "listings": result.listings,
                    "jobs": result.jobs,
                    "visits": result.visits,
                },
            },
            after={"deleted": True},
            conn=connection,
        )
    return result


@router.put(
    "/hunts/{hunt_id}/lock",
    response_model=HuntManagement,
    summary="Lock or unlock a Hunt",
)
async def set_hunt_lock(
    hunt_id: UUID,
    body: HuntLockUpdate,
    admin: AdminUser,
    pool: DbPool,
    audit: Audit,
) -> HuntManagement:
    async with pool.acquire() as connection, connection.transaction():
        hunt = await connection.fetchrow(
            "select name, locked_at, locked_by from hunts where id=$1 for update", hunt_id
        )
        if hunt is None:
            raise AdminHuntNotFound("Hunt not found")

        changed = body.locked is not (hunt["locked_at"] is not None)
        if changed:
            await connection.execute(
                "update hunts set locked_at=$2, locked_by=$3 where id=$1",
                hunt_id,
                datetime.now(UTC) if body.locked else None,
                UUID(admin.id) if body.locked else None,
            )
            if body.locked:
                await connection.execute(
                    """
                    update jobs
                    set state='cancelled', finished_at=coalesce(finished_at, now()),
                        locked_by=null, locked_at=null,
                        error=coalesce(error, 'Cancelled because the Hunt was locked')
                    where hunt_id=$1 and state in ('queued', 'running', 'waiting_user')
                    """,
                    hunt_id,
                )
            await audit.record(
                "hunt.lock" if body.locked else "hunt.unlock",
                target_type="hunt",
                target_id=hunt_id,
                target_label=hunt["name"],
                hunt_id=hunt_id,
                before={"locked": not body.locked},
                after={"locked": body.locked},
                conn=connection,
            )

    return await hunt_management(hunt_id, admin, pool)


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


__all__ = ["NotSiteAdmin", "router"]
