from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from manzil_api import privileged
from manzil_api.config import Settings
from manzil_api.database import create_service_client
from manzil_api.invites.exceptions import InviteGone, InviteNotFound
from manzil_api.invites.schemas import InviteAccepted, InviteCreate, InviteResponse
from supabase import Client

MEMBER_COLOR_TOKENS = ("dusk", "clay", "moss", "ochre", "brick", "olive", "stone", "plum")


def _response(row: dict[str, Any], frontend_url: str) -> InviteResponse:
    return InviteResponse(**row, link=f"{frontend_url.rstrip('/')}/invite/{row['token']}")


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
    privileged.send_invite_email(
        create_service_client(settings), body.email, token, settings.frontend_url
    )
    return _response(row, settings.frontend_url)


async def list_invites(client: Client, frontend_url: str, hunt_id: UUID) -> list[InviteResponse]:
    response = (
        client.table("invites")
        .select("*")
        .eq("hunt_id", str(hunt_id))
        .is_("accepted_by", "null")
        .gt("expires_at", datetime.now(UTC).isoformat())
        .execute()
    )
    return [_response(row, frontend_url) for row in response.data or []]


async def revoke_invite(client: Client, invite_id: UUID) -> None:
    response = client.table("invites").delete().eq("id", str(invite_id)).execute()
    if not response.data:
        raise InviteNotFound("Invite not found")


async def accept_invite(settings: Settings, token: str, user_id: str) -> InviteAccepted:
    result = privileged.accept_invite(create_service_client(settings), token, user_id)
    if result.get("status") in {"gone", "expired", "accepted"}:
        raise InviteGone("Invite is expired, revoked, or already accepted")
    return InviteAccepted(hunt_id=result["hunt_id"])
