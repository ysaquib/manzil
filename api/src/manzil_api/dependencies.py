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
from uuid import UUID

import asyncpg
import jwt
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
    is_demo: bool = False
    demo_generation: int | None = None


class NotAuthenticated(ManzilAPIError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "not_authenticated"


class DemoReadOnly(ManzilAPIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "demo_read_only"


DEMO_CLAIM = "manzil_demo"
DEMO_GEN_CLAIM = "manzil_demo_gen"


def demo_issuer(settings: Settings) -> str:
    """The `iss` our demo tokens carry, matching GoTrue's own for this project.

    Minted by `manzil_api.demo.service` and required by the verifier below, so
    it lives here -- the one module both sides already share.
    """
    return f"{settings.supabase_url.rstrip('/')}/auth/v1"


def _decode_demo_token(settings: Settings, token: str) -> tuple[str, int] | None:
    """Return the demo principal's id if this is one of our demo tokens.

    Demo tokens are minted by `POST /v1/demo/session` for a subject that has no
    `auth.users` row (DESIGN §20 v3.55), which is precisely why GoTrue answers
    `user_not_found` for it -- so `auth.get_user()` cannot be the check here and
    the signature is verified locally instead.

    Returning None means "not a demo token", and the caller falls through to the
    ordinary GoTrue path. It never means "valid": a token that carries the demo
    claim but fails verification raises.

    The accepted profile is pinned to exactly what we emit (R2 M7). Signature,
    audience and expiry are the load-bearing checks, but a token that reaches
    PostgREST with a non-UUID subject or a role other than `authenticated`
    behaves in ways this API never intended, and rejecting it here is clearer
    than discovering it downstream in a cast error. Generation is deliberately
    *not* checked here: only the database knows the current value, and RLS is
    the boundary -- the API just refuses a token that carries no generation at
    all, since we have never minted one.
    """
    if not settings.supabase_jwt_secret:
        return None
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return None
    if not unverified.get(DEMO_CLAIM):
        return None
    try:
        claims = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            issuer=demo_issuer(settings),
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise NotAuthenticated("Invalid or expired demo token") from exc

    if claims.get("role") != "authenticated":
        raise NotAuthenticated("Invalid or expired demo token")
    if not isinstance(claims.get(DEMO_GEN_CLAIM), int):
        raise NotAuthenticated("Invalid or expired demo token")
    try:
        subject = UUID(str(claims.get("sub")))
    except (TypeError, ValueError) as exc:
        raise NotAuthenticated("Invalid or expired demo token") from exc
    return str(subject), int(claims[DEMO_GEN_CLAIM])


async def get_current_user(
    settings: SettingsDep,
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> UserContext:
    """Verify the bearer token and return the caller.

    Phase 1 uses `auth.get_user(token)` for simplicity (plan §1.2); revisit for
    latency with local JWT-secret verification if it ever matters.

    Demo tokens are the one exception, and not for convenience: their subject
    deliberately has no account, so there is nothing for GoTrue to return.
    """
    from manzil_api.database import create_anon_client

    token = creds.credentials

    demo_identity = _decode_demo_token(settings, token)
    if demo_identity is not None:
        demo_subject, generation = demo_identity
        return UserContext(
            id=demo_subject,
            email=None,
            access_token=token,
            is_demo=True,
            demo_generation=generation,
        )

    client = create_anon_client(settings)
    try:
        response = client.auth.get_user(token)
    except Exception as exc:  # supabase raises on an invalid/expired token
        raise NotAuthenticated("Invalid or expired token") from exc
    if response is None or response.user is None:
        raise NotAuthenticated("Invalid or expired token")
    return UserContext(id=response.user.id, email=response.user.email, access_token=token)


CurrentUser = Annotated[UserContext, Depends(get_current_user)]

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def require_not_demo(
    request: Request,
    settings: SettingsDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))],
) -> None:
    """Refuse unsafe methods from a demo principal (DM-5, DESIGN §16).

    Explicitly **not** the security boundary -- the database is, and it refuses
    these writes whether or not this runs. What this buys is a clean, catchable
    `403 demo_read_only` instead of a raw SQLSTATE surfacing through a route,
    and it stops demo traffic before any expensive validation or fan-out.

    It reads the token directly rather than depending on `get_current_user`, so
    it can be registered app-wide without forcing authentication onto the
    unauthenticated demo and health routes.
    """
    if request.method in _SAFE_METHODS or creds is None:
        return
    try:
        identity = _decode_demo_token(settings, creds.credentials)
    except NotAuthenticated:
        return  # a bad token is get_current_user's business, not ours
    if identity is not None:
        raise DemoReadOnly("Demo mode is read-only. Nothing you change here is saved.")


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
