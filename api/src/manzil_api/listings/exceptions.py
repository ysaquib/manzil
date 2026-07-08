"""Listings module exceptions."""

from __future__ import annotations

from fastapi import status

from manzil_api.exceptions import ManzilAPIError


class ListingNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "listing_not_found"
