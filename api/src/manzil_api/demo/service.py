"""Demo session minting (DM-5, DESIGN §16).

The demo principal is a UUID with **no** `auth.users` row (§20 v3.55). That is
the whole point: GoTrue answers `user_not_found` for every operation on it, so
the shared public identity cannot have its password changed, its email rebound,
MFA enrolled against it, or every visitor signed out of it. Two weaker shapes
were tested against a live stack and both failed -- a real account with a
self-minted sessionless token, and the same account banned. GoTrue honoured
`PUT /auth/v1/user` in both cases.

So the token is minted here, signed with the project JWT secret, and PostgREST
and Realtime accept it on signature alone.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass

import jwt
from fastapi import Request

from manzil_api.config import Settings
from manzil_api.dependencies import DEMO_CLAIM


@dataclass(frozen=True)
class DemoSession:
    access_token: str
    expires_in: int
    hunt_id: str | None


def client_key(settings: Settings, request: Request) -> str | None:
    """A stable, non-reversible key for the caller, or None.

    No IP address is stored anywhere. `X-Forwarded-For` is caller-controlled, so
    the trusted hop count is configuration rather than a guess from the header's
    length -- on Render `request.client.host` is the proxy, and a naive "take
    the first entry" read is trivially spoofed into unlimited issuance.

    Without a configured salt this returns None, and only the global ceiling
    applies. That is deliberate: a guessable key is worse than no key, because
    it lets a caller impersonate someone else's quota.
    """
    if not settings.demo_client_key_salt:
        return None

    hops = settings.demo_trusted_proxy_hops
    address: str | None = request.client.host if request.client else None
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(chain) >= hops:
            address = chain[-hops]
    if not address:
        return None

    digest = hmac.new(
        settings.demo_client_key_salt.encode(), address.encode(), hashlib.sha256
    ).hexdigest()
    return digest[:32]


def mint_token(settings: Settings, subject: str) -> DemoSession:
    ttl = max(60, settings.demo_session_ttl_seconds)
    now = int(time.time())
    claims = {
        "sub": subject,
        "aud": "authenticated",
        "role": "authenticated",
        "iat": now,
        "exp": now + ttl,
        # Distinguishes our token from a GoTrue one so `get_current_user` knows
        # to verify it locally. Not a privilege: RLS keys on the subject.
        DEMO_CLAIM: True,
        # Per-visit identifier, for correlating abuse in the issuance log
        # without recording anything about the visitor.
        "demo_session": str(uuid.uuid4()),
    }
    token = jwt.encode(claims, settings.supabase_jwt_secret, algorithm="HS256")
    return DemoSession(access_token=token, expires_in=ttl, hunt_id=None)
