"""People management (AD-3, DESIGN §20 v3.42).

Split out of `router.py` because this is the half of the panel that *writes to
accounts*, and it deserves to be read on its own.

Two rules shape everything here:

**Deleting a Hunt owner is refused, never cascaded.** `hunts.owner_id` has no
cascade, but `hunt_members`, `hunt_listings`, `jobs`, `visits` and every fact
under them do — so deleting the account of someone who owns a Hunt would take
the Hunt and its entire history with it. The refusal carries the blocking Hunts
so the panel can offer the transfer inline instead of making the operator go
find it.

**Suspension is the reversible alternative to deletion**, and it is the one an
operator should reach for. It is an auth-level ban rather than a column of our
own: a second source of truth for "can this person sign in" is exactly the kind
of thing that drifts, and the ban is what Supabase actually enforces.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Query, status

from manzil_api.admin.dependencies import AdminUser, Audit
from manzil_api.admin.schemas import (
    ActionResult,
    PersonDetail,
    PersonMembership,
    PersonRow,
    ProvisionPerson,
    SetMembership,
    UpdatePerson,
)
from manzil_api.config import Settings, get_settings
from manzil_api.database import create_service_client
from manzil_api.dependencies import DbPool
from manzil_api.exceptions import ManzilAPIError
from supabase import Client

router = APIRouter(prefix="/admin/people", tags=["admin"])

# A ban far enough out to be permanent in practice; lifting it is `"none"`.
SUSPEND_DURATION = "876000h"


class PersonNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "person_not_found"


class OwnsAHunt(ManzilAPIError):
    """Deleting them would take the Hunt and everything under it."""

    status_code = status.HTTP_409_CONFLICT
    code = "person_owns_a_hunt"


class CannotDeleteSelf(ManzilAPIError):
    status_code = status.HTTP_409_CONFLICT
    code = "cannot_delete_self"


class AccountStillReferenced(ManzilAPIError):
    """They left work behind that belongs to a Hunt, not to them."""

    status_code = status.HTTP_409_CONFLICT
    code = "account_still_referenced"


class LockedHuntMembership(ManzilAPIError):
    status_code = status.HTTP_423_LOCKED
    code = "hunt_locked"


async def _require_unlocked_hunt(pool: asyncpg.Pool, hunt_id: UUID) -> None:
    row = await pool.fetchrow("select name, locked_at from hunts where id=$1", hunt_id)
    if row is not None and row["locked_at"] is not None:
        raise LockedHuntMembership(
            f"{row['name']} is locked; unlock it before changing its memberships"
        )


class AuthOperationFailed(ManzilAPIError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "auth_operation_failed"


def _service() -> Client:
    return create_service_client(get_settings())


def _settings() -> Settings:
    return get_settings()


# `auth.users` is not exposed to PostgREST, so every read here goes through the
# pool. The ban timestamp is the only "is this account usable" fact, and it
# lives there rather than in a column of ours.
_ROSTER_SQL = """
select
    u.id as user_id, u.email, u.created_at, u.last_sign_in_at,
    u.email_confirmed_at is not null as confirmed,
    (u.banned_until is not null and u.banned_until > now()) as suspended,
    up.default_display_name as display_name,
    (select count(*) from hunt_members m where m.user_id = u.id) as hunts,
    (select count(*) from hunts h where h.owner_id = u.id) as owns,
    (select exists (select 1 from site_admins sa where sa.user_id = u.id)) as is_site_admin,
    coalesce((
        select sum(j.cost_actual_usd)
        from jobs j
        join hunts h2 on h2.id = j.hunt_id
        where h2.owner_id = u.id
    ), 0) as spend_usd
from auth.users u
left join user_profiles up on up.user_id = u.id
"""


def _row_to_person(row: asyncpg.Record) -> dict[str, Any]:
    data = dict(row)
    data["spend_usd"] = float(data.pop("spend_usd") or 0)
    return data


async def _blocking_references(pool: asyncpg.Pool, user_id: UUID) -> list[tuple[str, int]]:
    """Rows that would make the delete fail, discovered from the FK catalog.

    Eleven columns across `visits`, `visit_entries`, `visit_units`,
    `visit_defects`, `visit_fee_proposals`, `visit_custom_items`,
    `hunt_shared_filters` and `listing_unit_group_states` reference
    `auth.users` with **NO ACTION**, so deleting such an account raises a raw
    foreign-key error from GoTrue — a 500 that says nothing useful.

    Reflected rather than hardcoded on purpose: the failure this guards against
    is a *future* table adding another NO ACTION reference, which a fixed list
    would silently miss until somebody hit the 500.

    The identifiers are interpolated because table and column names cannot be
    bound as parameters; they come from `pg_constraint`, never from a caller.
    """
    fks = await pool.fetch(
        """
        select c.conrelid::regclass::text as tbl, a.attname as col
        from pg_constraint c
        join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
        where c.contype = 'f'
          and c.confrelid = 'auth.users'::regclass
          and c.connamespace = 'public'::regnamespace
          and c.confdeltype = 'a'  -- NO ACTION: exactly the ones that block
        """
    )
    blocking: list[tuple[str, int]] = []
    for fk in fks:
        count = await pool.fetchval(
            f"select count(*) from {fk['tbl']} where {fk['col']} = $1", user_id
        )
        if count:
            blocking.append((fk["tbl"], count))
    return sorted(blocking, key=lambda item: -item[1])


async def _memberships(pool: asyncpg.Pool, user_id: UUID) -> list[PersonMembership]:
    rows = await pool.fetch(
        """
        select m.hunt_id, h.name as hunt_name, m.role::text as role,
               (select min(recorded_at) from hunt_member_history mh
                 where mh.hunt_id = m.hunt_id and mh.user_id = m.user_id
                   and mh.action = 'joined') as joined_at
        from hunt_members m
        join hunts h on h.id = m.hunt_id
        where m.user_id = $1
        order by h.name
        """,
        user_id,
    )
    return [PersonMembership(**dict(row)) for row in rows]


@router.get("", response_model=list[PersonRow], summary="Everyone with an account")
async def list_people(
    admin: AdminUser,
    pool: DbPool,
    search: str | None = Query(None, max_length=200),
    search_mode: Literal["text", "id"] = Query("text"),
    limit: int = Query(200, ge=1, le=500),
) -> list[PersonRow]:
    rows = await pool.fetch(
        _ROSTER_SQL
        + """
        where ($1::text is null
               or ($2 = 'id' and u.id::text = $1)
               or ($2 = 'text' and (
                   u.email ilike '%' || $1 || '%'
                   or up.default_display_name ilike '%' || $1 || '%'
               )))
        order by u.created_at desc
        limit $3
        """,
        search,
        search_mode,
        limit,
    )
    return [PersonRow(**_row_to_person(row)) for row in rows]


@router.get("/{user_id}", response_model=PersonDetail, summary="One person")
async def get_person(user_id: UUID, admin: AdminUser, pool: DbPool) -> PersonDetail:
    row = await pool.fetchrow(_ROSTER_SQL + " where u.id = $1", user_id)
    if row is None:
        raise PersonNotFound("No such account")

    memberships = await _memberships(pool, user_id)
    feedback_count = await pool.fetchval(
        "select count(*) from feedback where user_id = $1", user_id
    )
    return PersonDetail(
        **_row_to_person(row),
        memberships=memberships,
        feedback_count=feedback_count,
        # Surfaced up-front so the panel can show the transfer next to the
        # disabled Delete, rather than letting the operator discover it by
        # being refused.
        blocking_owned_hunts=[m for m in memberships if m.role == "owner"],
    )


@router.post(
    "",
    response_model=ActionResult,
    status_code=status.HTTP_201_CREATED,
    summary="Provision an account",
)
async def provision_person(
    body: ProvisionPerson, admin: AdminUser, pool: DbPool, audit: Audit
) -> ActionResult:
    """Create an Auth account and send its password-enrollment email.

    This is the sole account-creation path. The Site Admin dependency and audit
    record are therefore part of the security boundary, not UI conveniences.
    If a Hunt and role are given, membership is a separate fact written only
    after Supabase has created the account.
    """
    service = _service()
    try:
        response = service.auth.admin.invite_user_by_email(
            body.email,
            {"redirect_to": (f"{_settings().frontend_url.rstrip('/')}/auth/reset-password")},
        )
    except Exception as exc:
        raise AuthOperationFailed(f"Supabase could not provision the account: {exc}") from exc

    invited_id = getattr(getattr(response, "user", None), "id", None)
    if invited_id and body.hunt_id and body.role:
        await pool.execute(
            "insert into hunt_members (hunt_id, user_id, role) values ($1, $2, $3::hunt_role) "
            "on conflict (hunt_id, user_id) do update set role = excluded.role",
            body.hunt_id,
            UUID(invited_id),
            body.role,
        )

    await audit.record(
        "user.provision",
        target_type="user",
        target_id=invited_id,
        target_label=body.email,
        hunt_id=body.hunt_id,
        after={"email": body.email, "role": body.role},
    )
    return ActionResult(detail=f"Account created; password setup sent to {body.email}")


@router.patch("/{user_id}", response_model=PersonDetail, summary="Update an account")
async def update_person(
    user_id: UUID, body: UpdatePerson, admin: AdminUser, pool: DbPool, audit: Audit
) -> PersonDetail:
    before = await pool.fetchrow(
        "select u.email, up.default_display_name from auth.users u "
        "left join user_profiles up on up.user_id = u.id where u.id = $1",
        user_id,
    )
    if before is None:
        raise PersonNotFound("No such account")

    if body.display_name is not None:
        # The account default, not a Hunt override — membership rows keep their
        # own nullable display_name and are untouched here.
        await pool.execute(
            "update user_profiles set default_display_name = $2, updated_at = now() "
            "where user_id = $1",
            user_id,
            body.display_name,
        )

    attrs: dict[str, Any] = {}
    if body.email is not None:
        attrs["email"] = body.email
    if body.confirm_email:
        attrs["email_confirm"] = True
    if attrs:
        try:
            _service().auth.admin.update_user_by_id(str(user_id), attrs)
        except Exception as exc:
            raise AuthOperationFailed(f"Supabase rejected the update: {exc}") from exc

    await audit.record(
        "user.update",
        target_type="user",
        target_id=user_id,
        target_label=before["email"],
        before={"email": before["email"], "display_name": before["default_display_name"]},
        after={"email": body.email, "display_name": body.display_name},
    )
    return await get_person(user_id, admin, pool)


@router.post("/{user_id}/suspend", response_model=ActionResult, summary="Suspend an account")
async def suspend_person(
    user_id: UUID, admin: AdminUser, pool: DbPool, audit: Audit
) -> ActionResult:
    if str(user_id) == admin.id:
        raise CannotDeleteSelf("An admin cannot suspend their own account")
    try:
        _service().auth.admin.update_user_by_id(str(user_id), {"ban_duration": SUSPEND_DURATION})
    except Exception as exc:
        raise AuthOperationFailed(f"Supabase rejected the suspension: {exc}") from exc

    await audit.record(
        "user.suspend", target_type="user", target_id=user_id, after={"suspended": True}
    )
    return ActionResult(detail="Account suspended; existing sessions are no longer valid")


@router.post("/{user_id}/restore", response_model=ActionResult, summary="Lift a suspension")
async def restore_person(
    user_id: UUID, admin: AdminUser, pool: DbPool, audit: Audit
) -> ActionResult:
    try:
        _service().auth.admin.update_user_by_id(str(user_id), {"ban_duration": "none"})
    except Exception as exc:
        raise AuthOperationFailed(f"Supabase rejected the restore: {exc}") from exc

    await audit.record(
        "user.restore", target_type="user", target_id=user_id, after={"suspended": False}
    )
    return ActionResult(detail="Account restored")


@router.post(
    "/{user_id}/password-reset",
    response_model=ActionResult,
    summary="Send a password-reset link",
)
async def send_password_reset(
    user_id: UUID, admin: AdminUser, pool: DbPool, audit: Audit
) -> ActionResult:
    email = await pool.fetchval("select email from auth.users where id = $1", user_id)
    if email is None:
        raise PersonNotFound("No such account")
    settings = _settings()
    try:
        _service().auth.reset_password_for_email(
            email, {"redirect_to": f"{settings.frontend_url.rstrip('/')}/auth/reset-password"}
        )
    except Exception as exc:
        raise AuthOperationFailed(f"Supabase could not send the reset: {exc}") from exc

    await audit.record(
        "user.password_reset", target_type="user", target_id=user_id, target_label=email
    )
    return ActionResult(detail=f"Reset link sent to {email}")


@router.put(
    "/{user_id}/memberships",
    response_model=PersonDetail,
    summary="Add someone to a Hunt or change their role",
)
async def set_membership(
    user_id: UUID, body: SetMembership, admin: AdminUser, pool: DbPool, audit: Audit
) -> PersonDetail:
    """Owner changes route through `transfer_hunt_ownership` rather than writing
    the role directly: a Hunt has exactly one owner, and setting a second one
    here would leave the old one in place."""
    await _require_unlocked_hunt(pool, body.hunt_id)
    previous = await pool.fetchval(
        "select role::text from hunt_members where hunt_id = $1 and user_id = $2",
        body.hunt_id,
        user_id,
    )

    if body.role == "owner":
        if previous is None:
            # The RPC requires an existing membership to promote.
            await pool.execute(
                "insert into hunt_members (hunt_id, user_id, role) values ($1, $2, 'member')",
                body.hunt_id,
                user_id,
            )
        await pool.execute(
            "select transfer_hunt_ownership($1::uuid, $2::uuid)", body.hunt_id, user_id
        )
    else:
        await pool.execute(
            "insert into hunt_members (hunt_id, user_id, role) values ($1, $2, $3::hunt_role) "
            "on conflict (hunt_id, user_id) do update set role = excluded.role",
            body.hunt_id,
            user_id,
            body.role,
        )

    await audit.record(
        "membership.set",
        target_type="user",
        target_id=user_id,
        hunt_id=body.hunt_id,
        before={"role": previous},
        after={"role": body.role},
    )
    return await get_person(user_id, admin, pool)


@router.delete(
    "/{user_id}/memberships/{hunt_id}",
    response_model=PersonDetail,
    summary="Remove someone from a Hunt",
)
async def remove_membership(
    user_id: UUID, hunt_id: UUID, admin: AdminUser, pool: DbPool, audit: Audit
) -> PersonDetail:
    await _require_unlocked_hunt(pool, hunt_id)
    role = await pool.fetchval(
        "select role::text from hunt_members where hunt_id = $1 and user_id = $2",
        hunt_id,
        user_id,
    )
    if role == "owner":
        raise OwnsAHunt("Transfer ownership before removing the Owner from their Hunt")

    await pool.execute(
        "delete from hunt_members where hunt_id = $1 and user_id = $2", hunt_id, user_id
    )
    await audit.record(
        "membership.remove",
        target_type="user",
        target_id=user_id,
        hunt_id=hunt_id,
        before={"role": role},
    )
    return await get_person(user_id, admin, pool)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an account")
async def delete_person(user_id: UUID, admin: AdminUser, pool: DbPool, audit: Audit) -> None:
    if str(user_id) == admin.id:
        raise CannotDeleteSelf("An admin cannot delete their own account")

    locked_hunts = await pool.fetch(
        "select h.name from hunt_members hm join hunts h on h.id=hm.hunt_id "
        "where hm.user_id=$1 and h.locked_at is not null order by h.name",
        user_id,
    )
    if locked_hunts:
        names = ", ".join(row["name"] for row in locked_hunts)
        raise LockedHuntMembership(
            f"They belong to locked Hunt(s): {names}. Unlock them before deleting the account"
        )

    owned = await pool.fetch(
        "select id, name from hunts where owner_id = $1 order by name", user_id
    )
    if owned:
        # The refusal names the Hunts. An operator told only "this failed" goes
        # looking; one told which Hunts is one click from the fix.
        names = ", ".join(row["name"] for row in owned)
        raise OwnsAHunt(
            f"They still own {len(owned)} Hunt(s) — {names}. Transfer ownership first; "
            "deleting them would take the Hunt, its Listings, Visits and Jobs with it."
        )

    email = await pool.fetchval("select email from auth.users where id = $1", user_id)
    if email is None:
        raise PersonNotFound("No such account")

    # Work they contributed to a Hunt outlives them — a tour is not deleted
    # because the person who started it closed their account, and §9.7's
    # per-member roll-up cannot survive its author being nulled. So the delete
    # is refused and suspension is offered, which is the reversible action an
    # operator should reach for anyway.
    blocking = await _blocking_references(pool, user_id)
    if blocking:
        summary = ", ".join(f"{count} in {table}" for table, count in blocking)
        raise AccountStillReferenced(
            f"They have contributed work that belongs to its Hunt rather than to them "
            f"({summary}). Deleting the account would destroy records other members "
            f"rely on. Suspend them instead — it revokes access and is reversible."
        )

    try:
        _service().auth.admin.delete_user(str(user_id))
    except Exception as exc:
        raise AuthOperationFailed(f"Supabase could not delete the account: {exc}") from exc

    await audit.record(
        "user.delete",
        target_type="user",
        target_id=user_id,
        target_label=email,
        before={"email": email},
    )
