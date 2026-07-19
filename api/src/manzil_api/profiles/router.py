from __future__ import annotations

from fastapi import APIRouter

from manzil_api.dependencies import CurrentUser, UserClient
from manzil_api.profiles.schemas import ProfileResponse, ProfileUpsert

router = APIRouter(tags=["profile"])


@router.get("/profile", response_model=ProfileResponse | None)
async def get_profile(user: CurrentUser, client: UserClient) -> ProfileResponse | None:
    rows = (
        client.table("user_profiles").select("*").eq("user_id", user.id).limit(1).execute().data
        or []
    )
    return ProfileResponse.model_validate(rows[0]) if rows else None


@router.put("/profile", response_model=ProfileResponse)
async def put_profile(
    body: ProfileUpsert, user: CurrentUser, client: UserClient
) -> ProfileResponse:
    payload: dict[str, object] = {
        "user_id": user.id,
        "default_display_name": body.default_display_name,
    }
    # Only touch the color when the caller sent it — onboarding's name-only
    # PUT must not clear a previously chosen default.
    if "default_color" in body.model_fields_set:
        payload["default_color"] = body.default_color
    row = (
        client.table("user_profiles")
        .upsert(payload, on_conflict="user_id")
        .execute()
        .data[0]
    )
    return ProfileResponse.model_validate(row)
