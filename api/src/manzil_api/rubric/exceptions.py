"""Rubric module exceptions."""

from __future__ import annotations

from fastapi import status

from manzil_api.exceptions import ManzilAPIError


class InvalidRubricOption(ManzilAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_rubric_option"
