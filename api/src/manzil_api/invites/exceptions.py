from fastapi import status

from manzil_api.exceptions import ManzilAPIError


class InviteNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "invite_not_found"


class InviteGone(ManzilAPIError):
    status_code = status.HTTP_410_GONE
    code = "invite_gone"


class InviteDeliveryNotRetryable(ManzilAPIError):
    status_code = status.HTTP_409_CONFLICT
    code = "invite_delivery_not_retryable"
