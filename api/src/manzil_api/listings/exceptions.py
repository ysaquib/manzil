"""Listings module exceptions."""

from __future__ import annotations

from fastapi import status

from manzil_api.exceptions import ManzilAPIError


class ListingNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "listing_not_found"


class ListingNotArchived(ManzilAPIError):
    status_code = status.HTTP_409_CONFLICT
    code = "listing_not_archived"


class ListingConfirmationMismatch(ManzilAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "listing_confirmation_mismatch"


class ListingHasActiveJobs(ManzilAPIError):
    status_code = status.HTTP_409_CONFLICT
    code = "listing_has_active_jobs"
