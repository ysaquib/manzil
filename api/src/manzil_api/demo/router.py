"""Public Demo Mode endpoints (DM-5, DESIGN §16).

`POST /v1/demo/session` is the only unauthenticated public route in this app, so
its ceiling is enforced in the database rather than in process memory: Render
runs more than one instance and restarts reset a counter. `issue_demo_session`
checks the kill switch and both ceilings and records the attempt in a single
statement, so two instances racing cannot both pass.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from manzil_api.config import Settings, get_settings
from manzil_api.database import create_service_client
from manzil_api.demo import service
from manzil_api.exceptions import ManzilAPIError

router = APIRouter(prefix="/demo", tags=["demo"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


class DemoUnavailable(ManzilAPIError):
    # 404 rather than 403: a disabled demo should not be discoverable, and the
    # response must not distinguish "off" from "never existed".
    status_code = status.HTTP_404_NOT_FOUND
    code = "demo_unavailable"


class DemoRateLimited(ManzilAPIError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "demo_rate_limited"


class DemoConfigResponse(BaseModel):
    enabled: bool


class DemoSessionResponse(BaseModel):
    access_token: str
    expires_in: int
    hunt_id: str | None = None


def _settings_row(settings: Settings) -> dict:
    client = create_service_client(settings)
    rows = client.table("site_settings").select("demo_enabled, demo_hunt_id").execute()
    return (rows.data or [{}])[0]


@router.get(
    "/config",
    response_model=DemoConfigResponse,
    summary="Whether the public demo is currently offered",
)
async def demo_config(settings: SettingsDep) -> DemoConfigResponse:
    if not settings.supabase_jwt_secret:
        # No signing secret means this deployment cannot mint demo tokens at
        # all. Report the demo as off rather than advertising a button that
        # would fail.
        return DemoConfigResponse(enabled=False)
    row = _settings_row(settings)
    return DemoConfigResponse(enabled=bool(row.get("demo_enabled")))


@router.post(
    "/session",
    response_model=DemoSessionResponse,
    summary="Mint a short-lived, read-only demo token",
)
async def create_demo_session(
    request: Request, settings: SettingsDep
) -> DemoSessionResponse:
    if not settings.supabase_jwt_secret:
        raise DemoUnavailable("The demo is not available.")

    client = create_service_client(settings)
    result = client.rpc(
        "issue_demo_session",
        {
            "p_client_key": service.client_key(settings, request),
            "p_user_agent": request.headers.get("user-agent"),
        },
    ).execute()
    outcome = result.data or {}

    status_value = outcome.get("status")
    if status_value == "rate_limited":
        raise DemoRateLimited(
            "The demo is busy right now. Please try again shortly."
        )
    if status_value != "issued":
        raise DemoUnavailable("The demo is not available.")

    session = service.mint_token(settings, str(outcome["user_id"]))
    return DemoSessionResponse(
        access_token=session.access_token,
        expires_in=session.expires_in,
        hunt_id=outcome.get("hunt_id"),
    )
