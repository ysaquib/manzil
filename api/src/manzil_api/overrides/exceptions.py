"""Override domain errors."""

from fastapi import status

from manzil_api.exceptions import ManzilAPIError


class InvalidOverrideTarget(ManzilAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_override_target"


class InvalidOverrideValue(ManzilAPIError):
    """A manual custom Criterion's Override value fails its `value_schema`, or
    the Override's target scope disagrees with the Criterion's `fact_scope`."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_override_value"
