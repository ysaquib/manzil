from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from svix.webhooks import Webhook, WebhookVerificationError

from manzil_api.dependencies import CurrentUser, DbPool, SettingsDep, UserClient
from manzil_api.email.dispatcher import apply_resend_webhook
from manzil_api.hunts.dependencies import MemberHunt
from manzil_api.notifications.schemas import (
    AccountNotificationPreferences,
    AttentionResponse,
    HuntNotificationPreferences,
    HuntNotificationPreferenceUpdate,
)

router = APIRouter(tags=["notifications"])
EVENTS = (
    "checkpoint_waiting",
    "run_failed",
    "listing_score_changed",
    "comment_added",
    "rating_changed",
)
DEFAULTS = {
    "checkpoint_waiting": True,
    "run_failed": True,
    "listing_score_changed": False,
    "comment_added": False,
    "rating_changed": False,
}


def _account_values(rows: list[dict]) -> dict[str, bool]:
    explicit = {row["event_type"]: bool(row["enabled"]) for row in rows}
    return {event: explicit.get(event, DEFAULTS[event]) for event in EVENTS}


@router.get("/notification-preferences", response_model=AccountNotificationPreferences)
async def get_account_preferences(
    user: CurrentUser, client: UserClient
) -> AccountNotificationPreferences:
    rows = (
        client.table("user_notification_prefs")
        .select("event_type,enabled")
        .eq("user_id", user.id)
        .eq("channel", "email")
        .execute()
        .data
        or []
    )
    return AccountNotificationPreferences(email=_account_values(rows))


@router.put("/notification-preferences", response_model=AccountNotificationPreferences)
async def put_account_preferences(
    body: AccountNotificationPreferences, user: CurrentUser, client: UserClient
) -> AccountNotificationPreferences:
    rows = [
        {
            "user_id": user.id,
            "event_type": event,
            "channel": "email",
            "enabled": body.email[event],
        }
        for event in EVENTS
    ]
    client.table("user_notification_prefs").upsert(
        rows, on_conflict="user_id,event_type,channel"
    ).execute()
    return AccountNotificationPreferences(email={event: body.email[event] for event in EVENTS})


async def _hunt_preferences(
    hunt_id: UUID, user_id: str, client: UserClient
) -> HuntNotificationPreferences:
    account_rows = (
        client.table("user_notification_prefs")
        .select("event_type,enabled")
        .eq("user_id", user_id)
        .eq("channel", "email")
        .execute()
        .data
        or []
    )
    hunt_rows = (
        client.table("hunt_notification_prefs")
        .select("event_type,enabled")
        .eq("hunt_id", str(hunt_id))
        .eq("user_id", user_id)
        .eq("channel", "email")
        .execute()
        .data
        or []
    )
    account = _account_values(account_rows)
    stored = {row["event_type"]: bool(row["enabled"]) for row in hunt_rows}
    overrides = {event: stored.get(event) for event in EVENTS}
    effective = {
        event: overrides[event] if overrides[event] is not None else account[event]
        for event in EVENTS
    }
    return HuntNotificationPreferences(
        account_email=account, email_overrides=overrides, effective_email=effective
    )


@router.get("/hunts/{hunt_id}/notification-preferences", response_model=HuntNotificationPreferences)
async def get_hunt_preferences(
    hunt_id: UUID, hunt: MemberHunt, user: CurrentUser, client: UserClient
) -> HuntNotificationPreferences:
    return await _hunt_preferences(hunt_id, user.id, client)


@router.put("/hunts/{hunt_id}/notification-preferences", response_model=HuntNotificationPreferences)
async def put_hunt_preferences(
    hunt_id: UUID,
    body: HuntNotificationPreferenceUpdate,
    hunt: MemberHunt,
    user: CurrentUser,
    client: UserClient,
) -> HuntNotificationPreferences:
    client.rpc(
        "set_hunt_notification_preferences",
        {"p_hunt_id": str(hunt_id), "p_overrides": body.email_overrides},
    ).execute()
    return await _hunt_preferences(hunt_id, user.id, client)


@router.get("/hunts/{hunt_id}/attention", response_model=AttentionResponse)
async def get_attention(
    hunt_id: UUID,
    hunt: MemberHunt,
    user: CurrentUser,
    client: UserClient,
    pool: DbPool,
) -> AttentionResponse:
    if user.is_demo:
        return AttentionResponse(waiting_checkpoint_count=0)
    membership = (
        client.table("hunt_members")
        .select("role")
        .eq("hunt_id", str(hunt_id))
        .eq("user_id", user.id)
        .single()
        .execute()
        .data
    )
    if membership["role"] in ("owner", "curator"):
        count = await pool.fetchval(
            "select count(*) from jobs where hunt_id = $1 and state = 'waiting_user'", hunt_id
        )
    else:
        count = await pool.fetchval(
            """select count(*) from jobs j join hunt_listings hl on hl.id = j.hunt_listing_id
                 where j.hunt_id = $1 and j.state = 'waiting_user' and hl.added_by = $2""",
            hunt_id,
            UUID(user.id),
        )
    return AttentionResponse(waiting_checkpoint_count=count)


@router.post("/webhooks/resend", status_code=status.HTTP_204_NO_CONTENT)
async def resend_webhook(
    request: Request,
    settings: SettingsDep,
    pool: DbPool,
    svix_id: str = Header(alias="svix-id"),
    svix_timestamp: str = Header(alias="svix-timestamp"),
    svix_signature: str = Header(alias="svix-signature"),
) -> None:
    if not settings.resend_webhook_secret:
        raise HTTPException(status_code=503, detail="Email webhook is not configured")
    payload = await request.body()
    try:
        event = Webhook(settings.resend_webhook_secret).verify(
            payload,
            {
                "svix-id": svix_id,
                "svix-timestamp": svix_timestamp,
                "svix-signature": svix_signature,
            },
        )
    except WebhookVerificationError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook signature") from exc
    data = event.get("data") or {}
    created_at = datetime.fromisoformat(str(event["created_at"]).replace("Z", "+00:00"))
    await apply_resend_webhook(
        pool,
        svix_id=svix_id,
        event_type=str(event["type"]),
        provider_at=created_at,
        provider_message_id=data.get("email_id") or data.get("id"),
    )
