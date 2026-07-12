from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from manzil_api import privileged
from manzil_api.config import Settings
from manzil_api.database import create_service_client
from manzil_api.invitation_links.exceptions import (
    InvitationLinkDeleted,
    InvitationLinkExhausted,
    InvitationLinkExpired,
    InvitationLinkNotFound,
)
from manzil_api.invitation_links.schemas import (
    InvitationLinkCreate,
    InvitationLinkJoined,
    InvitationLinkPatch,
    InvitationLinkResponse,
)
from supabase import Client


def _response(row: dict[str, Any], frontend_url: str) -> InvitationLinkResponse:
    joins = sorted(row.get("invitation_link_joins") or [], key=lambda join: join["joined_at"])
    use_count = len(joins)
    now = datetime.now(UTC)
    expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
    if expires_at <= now:
        link_status = "expired"
    elif row["max_uses"] is not None and use_count >= row["max_uses"]:
        link_status = "exhausted"
    else:
        link_status = "active"
    return InvitationLinkResponse(
        **row,
        use_count=use_count,
        status=link_status,
        link=f"{frontend_url.rstrip('/')}/join/{row['token']}",
        joins=joins,
    )


async def create_invitation_link(
    client: Client,
    settings: Settings,
    hunt_id: UUID,
    user_id: str,
    body: InvitationLinkCreate,
) -> InvitationLinkResponse:
    expires_at = body.expires_at or datetime.now(UTC) + timedelta(days=7)
    response = (
        client.table("invitation_links")
        .insert(
            {
                "hunt_id": str(hunt_id),
                "token": secrets.token_urlsafe(24),
                "created_by": user_id,
                "name": body.name,
                "max_uses": body.max_uses,
                "expires_at": expires_at.isoformat(),
            }
        )
        .execute()
    )
    row = {**response.data[0], "invitation_link_joins": []}
    return _response(row, settings.frontend_url)


async def list_invitation_links(
    client: Client, frontend_url: str, hunt_id: UUID
) -> list[InvitationLinkResponse]:
    response = (
        client.table("invitation_links")
        .select("*, invitation_link_joins(user_id,display_name,joined_at)")
        .eq("hunt_id", str(hunt_id))
        .is_("deleted_at", "null")
        .order("created_at", desc=True)
        .execute()
    )
    return [_response(row, frontend_url) for row in response.data or []]


async def patch_invitation_link(
    client: Client,
    frontend_url: str,
    invitation_link_id: UUID,
    body: InvitationLinkPatch,
) -> InvitationLinkResponse:
    changes: dict[str, Any] = {}
    if "name" in body.model_fields_set:
        changes["name"] = body.name
    if "max_uses" in body.model_fields_set:
        changes["max_uses"] = body.max_uses
    if "expires_at" in body.model_fields_set:
        changes["expires_at"] = body.expires_at.isoformat() if body.expires_at else None
    response = (
        client.table("invitation_links")
        .update(changes)
        .eq("id", str(invitation_link_id))
        .is_("deleted_at", "null")
        .execute()
    )
    if not response.data:
        raise InvitationLinkNotFound("Invitation Link not found")
    row = response.data[0]
    joins = (
        client.table("invitation_link_joins")
        .select("user_id,display_name,joined_at")
        .eq("invitation_link_id", str(invitation_link_id))
        .execute()
    )
    row["invitation_link_joins"] = joins.data or []
    return _response(row, frontend_url)


async def delete_invitation_link(client: Client, invitation_link_id: UUID, user_id: str) -> None:
    response = (
        client.table("invitation_links")
        .update({"deleted_at": datetime.now(UTC).isoformat(), "deleted_by": user_id})
        .eq("id", str(invitation_link_id))
        .is_("deleted_at", "null")
        .execute()
    )
    if not response.data:
        raise InvitationLinkNotFound("Invitation Link not found")


async def join_invitation_link(
    settings: Settings, token: str, user_id: str
) -> InvitationLinkJoined:
    result = privileged.join_invitation_link(create_service_client(settings), token, user_id)
    status = result.get("status")
    if status == "not_found":
        raise InvitationLinkNotFound("Invitation Link not found")
    if status == "deleted":
        raise InvitationLinkDeleted("This Invitation Link was deleted")
    if status == "expired":
        raise InvitationLinkExpired("This Invitation Link has expired")
    if status == "exhausted":
        raise InvitationLinkExhausted("This Invitation Link has reached its use limit")
    return InvitationLinkJoined(hunt_id=result["hunt_id"])
