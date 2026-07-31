"""Visits dependency chain (DESIGN §9.7, §4.2).

`valid_visit_id` resolves the path Visit through the caller's own client, so RLS
does the authorization: a non-member's read returns nothing and becomes a 404.
That is deliberate — "visit not found" is the right answer for a Hunt you cannot
see, since 403 would confirm the Visit exists.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends

from manzil_api.dependencies import get_user_client
from manzil_api.visits import service
from manzil_api.visits.exceptions import VisitNotFound
from supabase import Client


async def valid_visit_id(
    visit_id: UUID,
    client: Annotated[Client, Depends(get_user_client)],
) -> service.Visit:
    visit = service.get_visit_row(client, visit_id)
    if visit is None:
        raise VisitNotFound(f"Visit {visit_id} not found")
    return visit


ValidVisit = Annotated[service.Visit, Depends(valid_visit_id)]
