"""Visit routes (DESIGN §9.7, VC-1).

Mutations only. Browsing reads go direct-Supabase per `frontend/AGENTS.md`'s
two-client split — they are continuously rendered and need Realtime anyway — so
there is no GET here; each mutation returns the affected resource.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from manzil_api.dependencies import CurrentUser, UserClient
from manzil_api.hunts.dependencies import WritableMemberHunt
from manzil_api.visits import service
from manzil_api.visits.dependencies import ValidVisit
from manzil_api.visits.schemas import (
    VisitCreate,
    VisitCustomItemCreate,
    VisitCustomItemResponse,
    VisitDefectCreate,
    VisitDefectPatch,
    VisitDefectResponse,
    VisitEntryBatch,
    VisitEntryResponse,
    VisitFeeProposalCreate,
    VisitFeeProposalDecision,
    VisitFeeProposalResponse,
    VisitPatch,
    VisitResponse,
    VisitUnitInput,
    VisitUnitPatch,
    VisitUnitResponse,
)

router = APIRouter(tags=["visits"])


@router.post(
    "/hunts/{hunt_id}/visits",
    response_model=VisitResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_visit(
    hunt: WritableMemberHunt,
    body: VisitCreate,
    user: CurrentUser,
    client: UserClient,
) -> VisitResponse:
    """Any member may create a Visit (DESIGN §4.2)."""
    return await service.create_visit(client, hunt, user.id, body)


@router.patch("/visits/{visit_id}", response_model=VisitResponse)
async def patch_visit(
    visit: ValidVisit,
    body: VisitPatch,
    user: CurrentUser,
    client: UserClient,
) -> VisitResponse:
    """Start, end, cancel, reinstate or reschedule.

    Any member starts or ends; cancel and reinstate narrow to the creator or the
    Hunt Owner, enforced here and by the `visits_enforce_update_rules` trigger.
    """
    return await service.patch_visit(client, visit, user.id, body)


@router.delete("/visits/{visit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_visit(visit: ValidVisit, user: CurrentUser, client: UserClient) -> None:
    await service.delete_visit(client, visit, user.id)


@router.post(
    "/visits/{visit_id}/units",
    response_model=VisitUnitResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_visit_unit(
    visit: ValidVisit,
    body: VisitUnitInput,
    user: CurrentUser,
    client: UserClient,
) -> VisitUnitResponse:
    return await service.add_unit(client, visit, user.id, body)


@router.patch("/visits/{visit_id}/units/{unit_id}", response_model=VisitUnitResponse)
async def patch_visit_unit(
    visit: ValidVisit,
    unit_id: UUID,
    body: VisitUnitPatch,
    client: UserClient,
) -> VisitUnitResponse:
    return await service.patch_unit(client, visit, unit_id, body)


@router.delete(
    "/visits/{visit_id}/units/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_visit_unit(visit: ValidVisit, unit_id: UUID, client: UserClient) -> None:
    await service.delete_unit(client, visit, unit_id)


@router.put("/visits/{visit_id}/entries", response_model=list[VisitEntryResponse])
async def save_visit_entries(
    visit: ValidVisit,
    body: VisitEntryBatch,
    user: CurrentUser,
    client: UserClient,
) -> list[VisitEntryResponse]:
    """Append a batch of answers; returns the resulting **current** values.

    The only write path for answers, and the shape the offline queue flushes.
    Append-only, so clearing an answer means sending a null `value`. Scope comes
    from the item, not the caller: a property item carrying a `visit_unit_id` is
    a 422, never silently re-filed (DESIGN §9.7).
    """
    return await service.save_entries(client, visit, user.id, body)


@router.post(
    "/visits/{visit_id}/defects",
    response_model=VisitDefectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_visit_defect(
    visit: ValidVisit,
    body: VisitDefectCreate,
    user: CurrentUser,
    client: UserClient,
) -> VisitDefectResponse:
    """Log a problem found on the tour.

    Most defects are not created here: marking a Check as a problem promotes one
    automatically (DESIGN §9.7). This is the path for something the checklist
    never asked about.
    """
    return await service.create_defect(client, visit, user.id, body)


@router.patch("/visits/{visit_id}/defects/{defect_id}", response_model=VisitDefectResponse)
async def patch_visit_defect(
    visit: ValidVisit,
    defect_id: UUID,
    body: VisitDefectPatch,
    client: UserClient,
) -> VisitDefectResponse:
    return await service.patch_defect(client, visit, defect_id, body)


@router.delete(
    "/visits/{visit_id}/defects/{defect_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_visit_defect(visit: ValidVisit, defect_id: UUID, client: UserClient) -> None:
    """Soft delete. The Check that promoted it keeps its answer — that a test
    failed and what the problem was are two separate records."""
    await service.delete_defect(client, visit, defect_id)


@router.post(
    "/visits/{visit_id}/custom-items",
    response_model=VisitCustomItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_custom_item(
    visit: ValidVisit,
    body: VisitCustomItemCreate,
    user: CurrentUser,
    client: UserClient,
) -> VisitCustomItemResponse:
    """Per-Visit additions, always rendered as custom (DESIGN §9.7)."""
    return await service.create_custom_item(client, visit, user.id, body)


@router.post(
    "/visits/{visit_id}/fee-proposals",
    response_model=VisitFeeProposalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_fee_proposal(
    visit: ValidVisit,
    body: VisitFeeProposalCreate,
    user: CurrentUser,
    client: UserClient,
) -> VisitFeeProposalResponse:
    """Offer a figure confirmed on the tour to one of the Property's Listings.

    Nothing on the Listing changes here — this is the offer (DESIGN §9.7). Any
    member may make one; deciding is the privileged half.
    """
    return await service.create_fee_proposal(client, visit, user.id, body)


@router.post(
    "/visits/{visit_id}/fee-proposals/{proposal_id}/decision",
    response_model=VisitFeeProposalResponse,
)
async def decide_fee_proposal(
    visit: ValidVisit,
    proposal_id: UUID,
    body: VisitFeeProposalDecision,
    user: CurrentUser,
    client: UserClient,
) -> VisitFeeProposalResponse:
    """Accept or reject an offer.

    Accepting performs the **ordinary** cost write — a `fee_checklist` upsert or
    an `overrides` insert — so the result is indistinguishable from a human
    typing it into the drawer. Rejecting records the decision and leaves the
    Visit's own figure alone. Permission is the Override permission (§4.2),
    enforced by RLS and by the delegated writer.
    """
    return await service.decide_fee_proposal(client, visit, proposal_id, user.id, body.action)


@router.delete(
    "/visits/{visit_id}/fee-proposals/{proposal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def withdraw_fee_proposal(
    visit: ValidVisit,
    proposal_id: UUID,
    client: UserClient,
) -> None:
    """Take back an offer nobody has decided yet. RLS restricts it to its author."""
    await service.withdraw_fee_proposal(client, visit, proposal_id)
