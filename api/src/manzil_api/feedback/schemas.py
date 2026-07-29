"""Feedback submission contract (P3-16, DESIGN §20 v3.27).

Only the four fields a person actually types or the page can honestly report are
accepted from the client. Identity is never client-supplied — the router sets
`user_id` from the verified bearer token — and the context fields are clamped
here so an oversized `route` or `user_agent` fails as a 422 rather than as a
database check-constraint violation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, field_validator

FeedbackCategory = Literal["bug", "feature", "confusing", "wrong_data", "other"]

MAX_BODY = 4000
MAX_ROUTE = 500
MAX_USER_AGENT = 500
MAX_APP_VERSION = 100


class FeedbackCreate(BaseModel):
    category: FeedbackCategory
    body: str
    # The path the reporter was on, Drawer query params included. Validated to a
    # site-relative path: an absolute URL would let a report attribute itself to
    # somewhere it did not come from, and the origin adds nothing we don't know.
    route: str | None = None
    hunt_id: UUID | None = None
    app_version: str | None = None

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= MAX_BODY:
            raise ValueError(f"body must be 1..{MAX_BODY} non-blank characters")
        return value

    @field_validator("route")
    @classmethod
    def validate_route(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("route must be a site-relative path beginning with '/'")
        return value[:MAX_ROUTE]

    @field_validator("app_version")
    @classmethod
    def validate_app_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value[:MAX_APP_VERSION] or None


class FeedbackResponse(BaseModel):
    """Deliberately thin: the submitter cannot read feedback rows back, so the
    response confirms receipt rather than echoing stored content."""

    id: UUID
    created_at: datetime
