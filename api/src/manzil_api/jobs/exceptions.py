"""Jobs module exceptions."""

from __future__ import annotations

from fastapi import status

from manzil_api.exceptions import ManzilAPIError


class JobNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "job_not_found"


class JobNotCancellable(ManzilAPIError):
    status_code = status.HTTP_409_CONFLICT
    code = "job_not_cancellable"


class JobNotRetryable(ManzilAPIError):
    status_code = status.HTTP_409_CONFLICT
    code = "job_not_retryable"
