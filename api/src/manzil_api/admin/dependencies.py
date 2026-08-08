"""Site Admin gating and the audit writer (AD-1, DESIGN §20 v3.39).

Two things live here, and they are deliberately coupled: nothing reaches an
admin route without passing `require_site_admin`, and nothing mutates through
one without `AdminAudit.record` running before the response is returned.

**Why the check hits the database rather than a JWT claim.** The plan sketched
mirroring the flag into app-metadata so the router could gate without a round
trip. That is faster and wrong: a claim is fixed at sign-in, so a *revoked*
admin keeps their access until the token expires — precisely the case where
being slow to notice is unacceptable. `site_admins` is a single indexed
primary-key lookup; correctness wins a round trip it can afford.
"""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

import asyncpg
from fastapi import Depends, Request, status

from manzil_api.dependencies import CurrentUser, DbPool, UserContext
from manzil_api.exceptions import ManzilAPIError


class NotSiteAdmin(ManzilAPIError):
    """404-shaped would be tidier, but this is an operator tool behind a link
    only admins are shown; a plain 403 is honest and easier to debug."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "not_site_admin"


async def require_site_admin(user: CurrentUser, pool: DbPool) -> UserContext:
    is_admin = await pool.fetchval(
        "select exists (select 1 from site_admins where user_id = $1)", UUID(user.id)
    )
    if not is_admin:
        raise NotSiteAdmin("This endpoint requires site administrator access")
    return user


AdminUser = Annotated[UserContext, Depends(require_site_admin)]


class AdminAudit:
    """Writes one `admin_audit_log` row per mutation.

    Injected rather than called as a free function so a route cannot silently
    forget the pool or the acting admin — it has to ask for the dependency, and
    once it has it, recording is one call.
    """

    def __init__(self, pool: asyncpg.Pool, admin: UserContext, request: Request) -> None:
        self._pool = pool
        self._admin = admin
        self._request = request

    async def record(
        self,
        action: str,
        *,
        target_type: str | None = None,
        target_id: UUID | str | None = None,
        target_label: str | None = None,
        hunt_id: UUID | str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        via_ghost_view: bool = False,
        conn: asyncpg.Connection | None = None,
    ) -> None:
        """Append one audit entry.

        `conn` writes the entry on a caller-supplied connection instead of the
        pool, so an action and its audit record can commit or fail together.
        `PATCH /admin/demo` uses it: enabling the public demo without an audit
        entry would change the system's exposure with no record of who did it
        (R2 H4).
        """
        await (conn or self._pool).execute(
            """
            insert into admin_audit_log (
                admin_user_id, action, target_type, target_id, target_label,
                hunt_id, before, after, via_ghost_view, request_id
            )
            values ($1, $2, $3, $4::uuid, $5, $6::uuid, $7::jsonb, $8::jsonb, $9, $10)
            """,
            UUID(self._admin.id),
            action,
            target_type,
            str(target_id) if target_id is not None else None,
            target_label,
            str(hunt_id) if hunt_id is not None else None,
            json.dumps(before) if before is not None else None,
            json.dumps(after) if after is not None else None,
            via_ghost_view,
            self._request.headers.get("x-request-id"),
        )


def get_admin_audit(request: Request, admin: AdminUser, pool: DbPool) -> AdminAudit:
    return AdminAudit(pool, admin, request)


Audit = Annotated[AdminAudit, Depends(get_admin_audit)]
