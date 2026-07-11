from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class InviteCreate(BaseModel):
    email: str | None = None
    role: Literal["member", "curator"] = "member"


class InviteResponse(BaseModel):
    id: UUID
    hunt_id: UUID
    email: str | None
    role_granted: str
    expires_at: datetime
    link: str


class InviteAccepted(BaseModel):
    hunt_id: UUID
