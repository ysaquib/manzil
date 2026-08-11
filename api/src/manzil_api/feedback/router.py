"""Feedback submission route (P3-16, DESIGN §20 v3.27).

One POST. Everything that identifies the reporter is taken from the verified
bearer token or the request itself, never from the body: a client can describe
its own bug, not attribute one to somebody else.

The insert runs through the caller's own client, so the `feedback_self_insert`
policy — and the rate-limit trigger behind it — is what actually admits the row.
`returning="minimal"` is required, not an optimization: the table has no SELECT
policy at all, so asking PostgREST to echo the inserted row would fail for the
very caller allowed to write it. The identifiers in the response are therefore
generated here and written explicitly rather than read back.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Request, status
from postgrest.exceptions import APIError

from manzil_api.build_info import feedback_build_context
from manzil_api.dependencies import CurrentUser, SettingsDep, UserClient
from manzil_api.exceptions import ManzilAPIError
from manzil_api.feedback.schemas import MAX_USER_AGENT, FeedbackCreate, FeedbackResponse

router = APIRouter(tags=["feedback"])

# Raised by private.enforce_feedback_rate_limit(); 53400 is
# configuration_limit_exceeded, chosen so it cannot be confused with the 42501
# permission failure an RLS rejection produces.
RATE_LIMIT_SQLSTATE = "53400"


class FeedbackRateLimited(ManzilAPIError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "feedback_rate_limited"


class HuntNotVisible(ManzilAPIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "hunt_not_visible"


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit product feedback",
)
async def create_feedback(
    body: FeedbackCreate,
    request: Request,
    user: CurrentUser,
    client: UserClient,
    settings: SettingsDep,
) -> FeedbackResponse:
    # A report may name only a Hunt the caller can actually see. The read runs
    # under the caller's own RLS, so a Hunt they are not a member of comes back
    # empty regardless of what the body claimed.
    if body.hunt_id is not None:
        visible = (
            client.table("hunts").select("id").eq("id", str(body.hunt_id)).limit(1).execute().data
            or []
        )
        if not visible:
            raise HuntNotVisible("You are not a member of that hunt")

    feedback_id = uuid4()
    created_at = datetime.now(UTC)
    user_agent = (request.headers.get("user-agent") or "")[:MAX_USER_AGENT] or None

    payload = {
        "id": str(feedback_id),
        "user_id": user.id,
        "category": body.category,
        "body": body.body,
        "route": body.route,
        "hunt_id": str(body.hunt_id) if body.hunt_id else None,
        "app_version": feedback_build_context(body.app_version, settings.environment),
        "user_agent": user_agent,
        "created_at": created_at.isoformat(),
    }

    try:
        client.table("feedback").insert(payload, returning="minimal").execute()
    except APIError as exc:
        if exc.code == RATE_LIMIT_SQLSTATE:
            raise FeedbackRateLimited(
                "You've sent a lot of feedback in the last hour — try again shortly."
            ) from exc
        raise

    return FeedbackResponse(id=feedback_id, created_at=created_at)
