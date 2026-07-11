from fastapi import status

from manzil_api.exceptions import ManzilAPIError


class InviteNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "invite_not_found"


class InviteGone(ManzilAPIError):
    status_code = status.HTTP_410_GONE
    code = "invite_gone"


class InviteEmailFailed(ManzilAPIError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "invite_email_failed"
