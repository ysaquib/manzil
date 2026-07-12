from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from manzil_api import privileged
from manzil_api.collaboration.exceptions import (
    CannotChangeOwnRole,
    CannotEditMember,
    CannotEditMemberColor,
    CannotRemoveOwner,
    CommentNotFound,
    MemberNotFound,
    NotCommentAuthor,
    TransferTargetNotMember,
)
from manzil_api.collaboration.schemas import (
    CommentCreate,
    CommentResponse,
    MemberPatch,
    MemberResponse,
    RatingResponse,
    RatingUpsert,
    TransferOwnershipResponse,
)
from manzil_api.config import Settings
from manzil_api.database import create_service_client
from supabase import Client

_ROLE_RANK = {"owner": 0, "curator": 1, "member": 2}


async def create_comment(
    client: Client, listing_id: UUID, user_id: str, body: CommentCreate
) -> CommentResponse:
    response = (
        client.table("comments")
        .insert({"hunt_listing_id": str(listing_id), "user_id": user_id, "body": body.body.strip()})
        .execute()
    )
    return CommentResponse.model_validate(response.data[0])


async def delete_comment(client: Client, comment_id: UUID, user_id: str) -> None:
    rows = client.table("comments").select("user_id").eq("id", str(comment_id)).execute().data or []
    if not rows:
        raise CommentNotFound("Comment not found")
    if rows[0]["user_id"] != user_id:
        raise NotCommentAuthor("Only the comment author may delete it")
    client.table("comments").update({"deleted_at": datetime.now(UTC).isoformat()}).eq(
        "id", str(comment_id)
    ).execute()


async def upsert_rating(
    client: Client, listing_id: UUID, user_id: str, body: RatingUpsert
) -> RatingResponse:
    response = (
        client.table("ratings")
        .upsert(
            {"hunt_listing_id": str(listing_id), "user_id": user_id, "rating": body.rating},
            on_conflict="hunt_listing_id,user_id",
        )
        .execute()
    )
    return RatingResponse.model_validate(response.data[0])


async def delete_rating(client: Client, listing_id: UUID, user_id: str) -> None:
    client.table("ratings").delete().eq("hunt_listing_id", str(listing_id)).eq(
        "user_id", user_id
    ).execute()


async def list_members(client: Client, hunt_id: UUID) -> list[MemberResponse]:
    rows = (
        client.table("hunt_members")
        .select("user_id, role, color, display_name")
        .eq("hunt_id", str(hunt_id))
        .execute()
        .data
        or []
    )
    rows.sort(key=lambda r: (_ROLE_RANK.get(r["role"], 99), (r.get("display_name") or "").lower()))
    return [MemberResponse.model_validate(row) for row in rows]


async def patch_member(
    client: Client,
    hunt_id: UUID,
    target_user_id: UUID,
    current_user_id: str,
    body: MemberPatch,
) -> MemberResponse:
    is_self = str(target_user_id) == current_user_id
    if is_self:
        # Matrix: "own color" (and display_name) — every role; never own role.
        if body.role is not None:
            raise CannotChangeOwnRole("Members may not change their own role")
        updates: dict[str, str] = {}
        if body.color is not None:
            updates["color"] = body.color
        if "display_name" in body.model_fields_set:
            updates["display_name"] = body.display_name
    else:
        # Another member's row: only the Owner may act, and only on the role.
        if body.color is not None or "display_name" in body.model_fields_set:
            raise CannotEditMemberColor("You may only edit your own color and display name")
        if _role_of(client, hunt_id, current_user_id) != "owner":
            raise CannotEditMember("Only the Owner may change another member's role")
        updates = {"role": body.role} if body.role is not None else {}

    if not updates:  # pragma: no cover - schema guarantees at least one field
        raise CannotEditMember("No editable fields supplied")

    response = (
        client.table("hunt_members")
        .update(updates)
        .eq("hunt_id", str(hunt_id))
        .eq("user_id", str(target_user_id))
        .execute()
    )
    if not response.data:
        raise MemberNotFound("Member not found")
    return MemberResponse.model_validate(response.data[0])


async def remove_member(client: Client, hunt_id: UUID, target_user_id: UUID) -> None:
    rows = (
        client.table("hunt_members")
        .select("role")
        .eq("hunt_id", str(hunt_id))
        .eq("user_id", str(target_user_id))
        .execute()
        .data
        or []
    )
    if not rows:
        raise MemberNotFound("Member not found")
    if rows[0]["role"] == "owner":
        raise CannotRemoveOwner("The Owner cannot be removed; transfer ownership first")
    client.table("hunt_members").delete().eq("hunt_id", str(hunt_id)).eq(
        "user_id", str(target_user_id)
    ).execute()


async def transfer_ownership(
    settings: Settings, hunt_id: UUID, new_owner_id: UUID
) -> TransferOwnershipResponse:
    result = privileged.transfer_ownership(
        create_service_client(settings), hunt_id, new_owner_id
    )
    if result.get("status") == "not_member":
        raise TransferTargetNotMember("The new owner must already be a member of the hunt")
    return TransferOwnershipResponse(status="ok")


def _role_of(client: Client, hunt_id: UUID, user_id: str) -> str | None:
    rows = (
        client.table("hunt_members")
        .select("role")
        .eq("hunt_id", str(hunt_id))
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0]["role"] if rows else None
