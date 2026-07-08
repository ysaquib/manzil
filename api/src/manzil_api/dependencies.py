"""App-wide FastAPI dependencies (Phase 1 plan §1.2, §4.1).

`get_current_user` verifies the bearer JWT and yields a `UserContext`;
`get_user_client` builds the request-scoped, caller-authenticated supabase-py
client every mutation flows through; `get_db_pool` hands the in-process worker
loop's asyncpg pool to the rare route that needs raw SQL. Domain-specific
resource/auth dependencies (`valid_hunt_id`, `require_owner`, …) chain off
these inside each package's `dependencies.py`.
"""

from __future__ import annotations

from typing import Annotated

import asyncpg
from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from manzil_api.config import Settings, get_settings
from manzil_api.database import create_user_client
from manzil_api.exceptions import ManzilAPIError
from supabase import Client

_bearer = HTTPBearer(auto_error=True)

SettingsDep = Annotated[Settings, Depends(get_settings)]


class UserContext(BaseModel):
    """The authenticated caller, resolved from the Supabase-issued JWT."""

    id: str
    email: str | None = None
    access_token: str


class NotAuthenticated(ManzilAPIError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "not_authenticated"


async def get_current_user(
    settings: SettingsDep,
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> UserContext:
    """Verify the bearer token via Supabase Auth and return the caller.

    Phase 1 uses `auth.get_user(token)` for simplicity (plan §1.2); revisit for
    latency with local JWT-secret verification if it ever matters.
    """
    from manzil_api.database import create_anon_client

    token = creds.credentials
    client = create_anon_client(settings)
    try:
        response = client.auth.get_user(token)
    except Exception as exc:  # supabase raises on an invalid/expired token
        raise NotAuthenticated("Invalid or expired token") from exc
    if response is None or response.user is None:
        raise NotAuthenticated("Invalid or expired token")
    return UserContext(id=response.user.id, email=response.user.email, access_token=token)


CurrentUser = Annotated[UserContext, Depends(get_current_user)]


def get_user_client(settings: SettingsDep, user: CurrentUser) -> Client:
    """Request-scoped supabase-py client carrying the caller's JWT (plan §1.2)."""
    return create_user_client(settings, user.access_token)


UserClient = Annotated[Client, Depends(get_user_client)]


def get_db_pool(request: Request) -> asyncpg.Pool:
    """The in-process worker loop's asyncpg pool, created by the lifespan."""
    pool: asyncpg.Pool | None = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise ManzilAPIError("Database pool is not available")
    return pool


DbPool = Annotated[asyncpg.Pool, Depends(get_db_pool)]
