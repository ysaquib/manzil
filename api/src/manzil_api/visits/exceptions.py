from fastapi import status

from manzil_api.exceptions import ManzilAPIError


class VisitNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "visit_not_found"


class VisitUnitNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "visit_unit_not_found"


class PropertyNotInHunt(ManzilAPIError):
    # A Visit is only meaningful against a Property this Hunt holds — the whole
    # point is checking what the agent says against what Extraction found.
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "property_not_in_hunt"


class FloorPlanNotOnProperty(ManzilAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "floor_plan_not_on_property"


class InvalidVisitTransition(ManzilAPIError):
    # e.g. ending a tour that never started, or starting a cancelled one.
    status_code = status.HTTP_409_CONFLICT
    code = "invalid_visit_transition"


class CannotCancelVisit(ManzilAPIError):
    # Cancel/reinstate narrows to the creator or the Owner (DESIGN §4.2).
    status_code = status.HTTP_403_FORBIDDEN
    code = "cannot_cancel_visit"


class CannotDeleteVisit(ManzilAPIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "cannot_delete_visit"


class TooManyVisitUnits(ManzilAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "too_many_visit_units"


class DuplicateVisitUnitLabel(ManzilAPIError):
    status_code = status.HTTP_409_CONFLICT
    code = "duplicate_visit_unit_label"


class UnknownChecklistItem(ManzilAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "unknown_checklist_item"


class ChecklistScopeMismatch(ManzilAPIError):
    # The item's own scope decides whether an answer carries a unit; a mismatch
    # is the mis-filed answer the scope design exists to prevent, so it is
    # refused rather than coerced (DESIGN §9.7).
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "checklist_scope_mismatch"


class VisitUnitNotOnVisit(ManzilAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "visit_unit_not_on_visit"


class ChecklistValueNotAllowed(ManzilAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "checklist_value_not_allowed"


class VisitDefectNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "visit_defect_not_found"


class FeeProposalNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "fee_proposal_not_found"


class FeeProposalAlreadyDecided(ManzilAPIError):
    # A decided proposal is a record, not a queue item. Re-deciding one would
    # either double-write the cost or silently reverse somebody's judgement.
    status_code = status.HTTP_409_CONFLICT
    code = "fee_proposal_already_decided"


class ListingNotVisitedProperty(ManzilAPIError):
    # A Visit may only offer figures to a Listing of the Property it toured.
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "listing_not_visited_property"


class UnknownFeeProposalTarget(ManzilAPIError):
    # `fee_slot` must name a real slot and `override` a cost criterion; a typo
    # would otherwise create a fee line nothing renders.
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "unknown_fee_proposal_target"
