"""App-wide response shapes (Phase 1 plan §1.4).

Domain request/response models live in each package's `schemas.py`; only the
cross-cutting error envelope lives here.
"""

from __future__ import annotations

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """The one error shape every failure returns, mapped by the global handler."""

    detail: str
    code: str  # machine-readable, e.g. "hunt_not_found", "invalid_rubric_option"
