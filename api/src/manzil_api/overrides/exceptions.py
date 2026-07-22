"""Override domain errors."""

from fastapi import status

from manzil_api.exceptions import ManzilAPIError


class InvalidOverrideTarget(ManzilAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_override_target"
