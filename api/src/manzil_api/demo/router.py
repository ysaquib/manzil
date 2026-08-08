"""Public Demo Mode endpoints (DM-5, DESIGN §16).

`POST /v1/demo/session` and `GET /v1/demo/config` are the only unauthenticated
public routes in this app, so the issuance ceiling is enforced in the database
rather than in process memory: Render runs more than one instance and restarts
reset a counter. `issue_demo_session` takes an advisory transaction lock, then
checks the kill switch and both ceilings and records the attempt -- being
*called* as one statement would not have serialized its internal reads and
writes, which is what the previous version of this sentence got wrong (R2 C2).

Both routes are edge-rate-limited in front of the API
(`docs/production-deployment-render-supabase.md` §7.0.1). The database limiter
is defence in depth; it is not the first packet sink.
"""

from __future__ import annotations

import time
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from manzil_api.config import Settings, get_settings
from manzil_api.database import create_service_client
from manzil_api.demo import service
from manzil_api.exceptions import ManzilAPIError

router = APIRouter(prefix="/demo", tags=["demo"])

SettingsDep = Annotated[Settings, Depends(get_settings)]

# `/demo/config` is unauthenticated and polled by every visitor's first paint,
# and it used to hit the database on every request (R2 M2). One boolean, cached
# for a few seconds, turns a DoS amplifier back into a cheap answer. The window
# is short enough that flipping the kill switch is still visible promptly, and
# the switch is not enforced here anyway -- RLS is.
#
# The cache is **per worker process** (R2 R9). With more than one Render
# instance, or more than one worker in an instance, each holds its own copy and
# expires it on its own clock, so the observable staleness after a toggle is up
# to `_CONFIG_TTL_SECONDS` regardless of how many processes the admin's request
# happened to reach. That is fine and is not a security property: this endpoint
# decides whether the "Try the demo" button renders. Access is decided by RLS,
# which is not cached anywhere.
_CONFIG_TTL_SECONDS = 15.0
_config_cache: tuple[float, bool] | None = None


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
    rows = client.table("site_settings").select("demo_enabled").execute()
    return (rows.data or [{}])[0]


def reset_config_cache() -> None:
    """Drop **this process's** cached availability flag.

    Called by the admin toggle, which reaches exactly one worker -- so the other
    processes keep serving their own cached answer until it expires (R2 R9). It
    is a nicety for the operator who just flipped the switch, not a global
    invalidation, and nothing depends on it being one.
    """
    global _config_cache
    _config_cache = None


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

    global _config_cache
    now = time.monotonic()
    if _config_cache is not None and now < _config_cache[0]:
        return DemoConfigResponse(enabled=_config_cache[1])

    # supabase-py is synchronous; calling it straight from an `async def`
    # handler blocks the event loop, so a slow upstream on this public route
    # would stall every other request in the process (R2 M1).
    row = await anyio.to_thread.run_sync(_settings_row, settings)
    enabled = bool(row.get("demo_enabled"))
    _config_cache = (now + _CONFIG_TTL_SECONDS, enabled)
    return DemoConfigResponse(enabled=enabled)


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

    key = service.client_key(settings, request)

    def _issue() -> dict:
        client = create_service_client(settings)
        return client.rpc(
            "issue_demo_session", {"p_client_key": key}
        ).execute().data or {}

    # Off the event loop, for the same reason as `/demo/config` above: this is
    # the endpoint an attacker gets to call without credentials.
    outcome = await anyio.to_thread.run_sync(_issue)

    status_value = outcome.get("status")
    if status_value == "rate_limited":
        raise DemoRateLimited(
            "The demo is busy right now. Please try again shortly."
        )
    if status_value != "issued":
        raise DemoUnavailable("The demo is not available.")

    generation = outcome.get("generation")
    if not isinstance(generation, int):
        # The RPC always returns it on an `issued` result. A token without one
        # would be refused by `private.demo_identity()` anyway; failing here
        # gives the visitor an honest 404 instead of a session that reads
        # nothing.
        raise DemoUnavailable("The demo is not available.")

    session = service.mint_token(settings, str(outcome["user_id"]), generation)
    return DemoSessionResponse(
        access_token=session.access_token,
        expires_in=session.expires_in,
        hunt_id=outcome.get("hunt_id"),
    )
