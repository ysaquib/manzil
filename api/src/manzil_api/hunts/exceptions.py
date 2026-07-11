"""Hunts module exceptions (Phase 1 plan §1.4)."""

from __future__ import annotations

from fastapi import status

from manzil_api.exceptions import ManzilAPIError


class HuntNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "hunt_not_found"


class NotHuntOwner(ManzilAPIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "not_hunt_owner"


class NotHuntMember(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "hunt_not_found"


class InsufficientRole(ManzilAPIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "insufficient_role"


class InvalidHuntSettings(ManzilAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_hunt_settings"
