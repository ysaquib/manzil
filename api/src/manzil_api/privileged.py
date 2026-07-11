"""Auditable home for the three privileged Phase 2 operations.

The seam is established in P2-2; invite acceptance/email and ownership transfer
are added by their owning tasks. Ordinary API mutations must not use it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from manzil_api.invites.exceptions import InviteEmailFailed
from supabase import Client


def accept_invite(service_client: Client, token: str, user_id: str) -> dict[str, Any]:
    response = service_client.rpc(
        "accept_hunt_invite", {"p_token": token, "p_user_id": user_id}
    ).execute()
    return response.data


def send_invite_email(service_client: Client, email: str, token: str, frontend_url: str) -> None:
    try:
        service_client.auth.admin.invite_user_by_email(
            email, {"redirect_to": f"{frontend_url.rstrip('/')}/invite/{token}"}
        )
    except Exception as exc:
        raise InviteEmailFailed("Supabase could not send the invite email") from exc


def transfer_ownership(
    service_client: Client, hunt_id: UUID, new_owner_id: UUID
) -> dict[str, Any]:
    """Move the 'owner' role atomically via the service-role RPC.

    Returns the RPC status jsonb (`{"status": "ok" | "not_member"}`) so the
    service layer can map `not_member` to a 404-shaped API error.
    """
    response = service_client.rpc(
        "transfer_hunt_ownership",
        {"p_hunt_id": str(hunt_id), "p_new_owner_id": str(new_owner_id)},
    ).execute()
    return response.data
