from fastapi import status

from manzil_api.exceptions import ManzilAPIError


class CommentNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "comment_not_found"


class NotCommentAuthor(ManzilAPIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "not_comment_author"


class InvalidUnitGroup(ManzilAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_unit_group"


class CannotEditMemberColor(ManzilAPIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "cannot_edit_member_color"


class CannotChangeOwnRole(ManzilAPIError):
    # Self-service may not touch its own role; promotion/demotion is an Owner act,
    # and moving the Owner role is transfer's job.
    status_code = status.HTTP_403_FORBIDDEN
    code = "cannot_change_own_role"


class CannotEditMember(ManzilAPIError):
    # Caller lacks the Owner role required to change another member's role.
    status_code = status.HTTP_403_FORBIDDEN
    code = "cannot_edit_member"


class MemberNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "member_not_found"


class CannotRemoveOwner(ManzilAPIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "cannot_remove_owner"


class TransferTargetNotMember(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "transfer_target_not_member"


class OwnerCannotLeaveHunt(ManzilAPIError):
    # Not a permission problem — the Owner has every permission. The Hunt is in
    # a state where leaving is incoherent, and transferring ownership fixes it.
    status_code = status.HTTP_409_CONFLICT
    code = "owner_cannot_leave_hunt"


class LastMemberCannotLeaveHunt(ManzilAPIError):
    # A Hunt with nobody in it is readable by no one, including the leaver.
    # Archiving is the action that means "I am done with this Hunt".
    status_code = status.HTTP_409_CONFLICT
    code = "last_member_cannot_leave_hunt"
