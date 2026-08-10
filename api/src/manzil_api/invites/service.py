from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from manzil_api import privileged
from manzil_api.config import Settings
from manzil_api.database import create_service_client
from manzil_api.invites.exceptions import (
    InviteDeliveryNotRetryable,
    InviteGone,
    InviteNotFound,
)
from manzil_api.invites.schemas import InviteAccepted, InviteCreate, InviteResponse
from supabase import Client

MEMBER_COLOR_TOKENS = (
    "dusky",
    "brick",
    "orange",
    "ochre",
    "olive",
    "moss",
    "teal",
    "cyan",
    "blue",
    "indigo",
    "violet",
    "plum",
    "pink",
)
# Existing profiles may still carry the former gray-backed `stone` token. It
# remains valid on reads/writes but is intentionally absent from the picker.
ACCEPTED_MEMBER_COLOR_TOKENS = (*MEMBER_COLOR_TOKENS, "stone")


def _response(
    row: dict[str, Any], frontend_url: str, delivery_status: str = "queued"
) -> InviteResponse:
    return InviteResponse(
        **row,
        link=f"{frontend_url.rstrip('/')}/invite/{row['token']}",
        delivery_status=delivery_status,
    )


async def create_invite(
    client: Client,
    settings: Settings,
    hunt_id: UUID,
    user_id: str,
    body: InviteCreate,
) -> InviteResponse:
    token = secrets.token_urlsafe(24)
    response = (
        client.table("invites")
        .insert(
            {
                "hunt_id": str(hunt_id),
                "email": body.email,
                "token": token,
                "role_granted": body.role,
                "created_by": user_id,
                "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            }
        )
        .execute()
    )
    row = response.data[0]
    return _response(row, settings.frontend_url)


async def list_invites(
    client: Client, frontend_url: str, hunt_id: UUID, pool: asyncpg.Pool
) -> list[InviteResponse]:
    response = (
        client.table("invites")
        .select("*")
        .eq("hunt_id", str(hunt_id))
        .is_("accepted_by", "null")
        .gt("expires_at", datetime.now(UTC).isoformat())
        .execute()
    )
    rows = response.data or []
    statuses = (
        {
            str(row["source_id"]): row["status"]
            for row in await pool.fetch(
                """select distinct on (e.source_id) e.source_id, d.status
                 from private.notification_events e
                 join private.notification_deliveries d on d.event_id = e.id
                where e.source_kind = 'invite' and e.source_id = any($1::uuid[])
                order by e.source_id, d.created_at desc""",
                [UUID(row["id"]) for row in rows],
            )
        }
        if rows
        else {}
    )
    return [_response(row, frontend_url, statuses.get(row["id"], "queued")) for row in rows]


async def resend_invite(
    client: Client,
    pool: asyncpg.Pool,
    frontend_url: str,
    invite_id: UUID,
    user_id: str,
) -> InviteResponse:
    rows = (
        client.table("invites")
        .select("*")
        .eq("id", str(invite_id))
        .is_("accepted_by", "null")
        .gt("expires_at", datetime.now(UTC).isoformat())
        .execute()
        .data
        or []
    )
    if not rows:
        raise InviteGone("Invite is expired, revoked, or already accepted")
    row = rows[0]
    async with pool.acquire() as conn, conn.transaction():
        # Lock the Invite itself so two concurrent resend requests cannot both
        # observe the same terminal delivery and enqueue duplicate mail.
        locked = await conn.fetchrow(
            """select * from invites where id = $1 and accepted_by is null
                 and expires_at > now() for update""",
            invite_id,
        )
        if locked is None:
            raise InviteGone("Invite is expired, revoked, or already accepted")
        latest_status = await conn.fetchval(
            """select d.status from private.notification_events e
                 join private.notification_deliveries d on d.event_id = e.id
                where e.source_kind = 'invite' and e.source_id = $1
                order by d.created_at desc limit 1""",
            invite_id,
        )
        if latest_status not in {"failed", "bounced", "suppressed", "complained"}:
            raise InviteDeliveryNotRetryable(
                "The latest invitation email is still active and cannot be resent"
            )

        row = dict(locked)
        hunt_id = UUID(str(row["hunt_id"]))
        hunt = await conn.fetchrow("select name from hunts where id = $1", hunt_id)
        inviter = await conn.fetchval(
            """select coalesce(
                   (select hm.display_name from hunt_members hm
                     where hm.hunt_id = $1 and hm.user_id = $2),
                   (select up.default_display_name from user_profiles up where up.user_id = $2),
                   'A Manzil Site Admin'
               )""",
            hunt_id,
            UUID(user_id),
        )
        event_id = uuid4()
        await conn.execute(
            """insert into private.notification_events
                 (id,event_type,hunt_id,actor_user_id,source_kind,source_id,dedupe_key,context)
               values ($1,'hunt_invited',$2,$3,'invite',$4,$5,$6::jsonb)""",
            event_id,
            hunt_id,
            UUID(user_id),
            invite_id,
            f"hunt_invited:{invite_id}:resend:{event_id}",
            json.dumps(
                {
                    "hunt_name": hunt["name"],
                    "inviter_name": inviter,
                    "role": row["role_granted"],
                    "expires_at": row["expires_at"],
                },
                default=str,
            ),
        )
        await conn.execute(
            """insert into private.notification_deliveries(event_id,recipient_email)
               values ($1,$2)""",
            event_id,
            row["email"].lower(),
        )
    return _response(row, frontend_url, "queued")


async def revoke_invite(client: Client, invite_id: UUID) -> None:
    response = client.table("invites").delete().eq("id", str(invite_id)).execute()
    if not response.data:
        raise InviteNotFound("Invite not found")


async def accept_invite(settings: Settings, token: str, user_id: str) -> InviteAccepted:
    result = privileged.accept_invite(create_service_client(settings), token, user_id)
    if result.get("status") in {"gone", "expired", "accepted"}:
        raise InviteGone("Invite is expired, revoked, or already accepted")
    return InviteAccepted(hunt_id=result["hunt_id"])
