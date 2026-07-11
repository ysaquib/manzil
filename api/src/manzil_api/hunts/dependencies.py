"""Hunts dependency chain (Phase 1 plan §1.3, §4.1).

`valid_hunt_id` resolves + 404s the path hunt; `require_owner` is the Phase 1
ownership stand-in for DESIGN §4.2's role matrix — it checks
`current_user.id == hunt.owner_id`. Shaped so P2-1/P2-2 replace only the body
(`require_role(min=...)`), never the routers that depend on it.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from manzil_shared.models import HuntRole

from manzil_api.dependencies import CurrentUser, get_user_client
from manzil_api.hunts import service
from manzil_api.hunts.exceptions import HuntNotFound, InsufficientRole, NotHuntMember
from supabase import Client

Hunt = dict[str, Any]


async def valid_hunt_id(
    hunt_id: UUID,
    client: Annotated[Client, Depends(get_user_client)],
) -> Hunt:
    hunt = await service.get_hunt_row(client, hunt_id)
    if hunt is None:
        raise HuntNotFound(f"Hunt {hunt_id} not found")
    return hunt


ValidHunt = Annotated[Hunt, Depends(valid_hunt_id)]


_ROLE_RANK = {HuntRole.MEMBER: 1, HuntRole.CURATOR: 2, HuntRole.OWNER: 3}


def require_role(minimum: HuntRole):  # type: ignore[no-untyped-def]
    async def dependency(
        hunt: ValidHunt,
        user: CurrentUser,
        client: Annotated[Client, Depends(get_user_client)],
    ) -> Hunt:
        response = (
            client.table("hunt_members")
            .select("role")
            .eq("hunt_id", hunt["id"])
            .eq("user_id", user.id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            raise NotHuntMember("Hunt not found")
        role = HuntRole(rows[0]["role"])
        if _ROLE_RANK[role] < _ROLE_RANK[minimum]:
            raise InsufficientRole(f"This action requires the {minimum.value} role")
        return hunt

    return dependency


require_member = require_role(HuntRole.MEMBER)
require_curator = require_role(HuntRole.CURATOR)
require_owner = require_role(HuntRole.OWNER)


OwnedHunt = Annotated[Hunt, Depends(require_owner)]
MemberHunt = Annotated[Hunt, Depends(require_member)]
CuratedHunt = Annotated[Hunt, Depends(require_curator)]
