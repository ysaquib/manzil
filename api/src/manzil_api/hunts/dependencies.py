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

from manzil_api.dependencies import CurrentUser, get_user_client
from manzil_api.hunts import service
from manzil_api.hunts.exceptions import HuntNotFound, NotHuntOwner
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


async def require_owner(hunt: ValidHunt, user: CurrentUser) -> Hunt:
    if hunt.get("owner_id") != user.id:
        raise NotHuntOwner("Only the hunt owner may perform this action")
    return hunt


OwnedHunt = Annotated[Hunt, Depends(require_owner)]
