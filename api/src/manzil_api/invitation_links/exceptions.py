from fastapi import status

from manzil_api.exceptions import ManzilAPIError


class InvitationLinkNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "invitation_link_not_found"


class InvitationLinkDeleted(ManzilAPIError):
    status_code = status.HTTP_410_GONE
    code = "invitation_link_deleted"


class InvitationLinkExpired(ManzilAPIError):
    status_code = status.HTTP_410_GONE
    code = "invitation_link_expired"


class InvitationLinkExhausted(ManzilAPIError):
    status_code = status.HTTP_410_GONE
    code = "invitation_link_exhausted"
