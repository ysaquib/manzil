"""Visit lifecycle and unit management (DESIGN §9.7, VC-1).

Every write here mirrors an RLS policy or the `visits_enforce_update_rules`
trigger — the database is the boundary, this layer exists to turn a denial into
a useful status code instead of a bare 403 from PostgREST.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from manzil_shared.models import ValueState
from postgrest.exceptions import APIError

from manzil_api.fees.schemas import FeeEntryUpsert
from manzil_api.fees.service import upsert_fee
from manzil_api.overrides.schemas import OverrideCreate
from manzil_api.overrides.service import create_override
from manzil_api.visits.exceptions import (
    CannotCancelVisit,
    ChecklistScopeMismatch,
    ChecklistValueNotAllowed,
    DuplicateVisitUnitLabel,
    FeeProposalAlreadyDecided,
    FeeProposalNotFound,
    FloorPlanNotOnProperty,
    InvalidVisitTransition,
    ListingNotVisitedProperty,
    PropertyNotInHunt,
    TooManyVisitUnits,
    UnknownChecklistItem,
    VisitDefectNotFound,
    VisitUnitNotFound,
    VisitUnitNotOnVisit,
)
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
    VisitFeeProposalResponse,
    VisitPatch,
    VisitResponse,
    VisitUnitInput,
    VisitUnitPatch,
    VisitUnitResponse,
)
from manzil_api.visits.template import TEMPLATE_VERSION
from supabase import Client

MAX_UNITS_PER_VISIT = 40

Visit = dict[str, Any]


# ---------------------------------------------------------------------------
# Reads (used by the routes' own responses; browsing reads go direct-Supabase)
# ---------------------------------------------------------------------------


def get_visit_row(client: Client, visit_id: UUID) -> Visit | None:
    rows = client.table("visits").select("*").eq("id", str(visit_id)).limit(1).execute().data or []
    return rows[0] if rows else None


def _units(client: Client, visit_id: str) -> list[VisitUnitResponse]:
    rows = (
        client.table("visit_units")
        .select("*")
        .eq("visit_id", visit_id)
        .order("display_order")
        .order("created_at")
        .execute()
        .data
        or []
    )
    return [VisitUnitResponse.model_validate(row) for row in rows]


def _visit_response(client: Client, visit: Visit) -> VisitResponse:
    return VisitResponse.model_validate({**visit, "units": _units(client, visit["id"])})


def caller_may_cancel(client: Client, visit: Visit, user_id: str) -> bool:
    """Cancel, reinstate and delete narrow to the creator or the Hunt Owner.

    Mirrors the delete policy and the update trigger; kept in one place so the
    two call sites cannot drift.
    """
    if visit["created_by"] == user_id:
        return True
    rows = (
        client.table("hunt_members")
        .select("role")
        .eq("hunt_id", visit["hunt_id"])
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return bool(rows) and rows[0]["role"] == "owner"


# ---------------------------------------------------------------------------
# Unit shape resolution
# ---------------------------------------------------------------------------


def _resolve_unit_shape(
    client: Client, property_id: str, unit: VisitUnitInput
) -> tuple[int, Decimal, str | None]:
    """Turn a unit input into concrete `(beds, baths, floor_plan_id)`.

    A Floor Plan supplies beds/baths so the Unit Group key matches the listing's
    own grouping exactly; a described unit carries what the member typed. The
    Floor Plan must belong to this Visit's Property — RLS enforces it too, but a
    422 naming the problem beats a policy denial.
    """
    if unit.floor_plan_id is None:
        assert unit.beds is not None and unit.baths is not None  # guarded in the schema
        return unit.beds, unit.baths, None

    rows = (
        client.table("floor_plans")
        .select("id,property_id,beds,baths")
        .eq("id", str(unit.floor_plan_id))
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows or rows[0]["property_id"] != property_id:
        raise FloorPlanNotOnProperty(
            f"Floor Plan {unit.floor_plan_id} does not belong to this Visit's Property"
        )
    plan = rows[0]
    # An explicitly typed shape still wins: a member correcting a listing's wrong
    # bed count on site is exactly the kind of knowledge a tour produces.
    beds = unit.beds if unit.beds is not None else int(plan["beds"])
    baths = unit.baths if unit.baths is not None else Decimal(str(plan["baths"]))
    return beds, baths, str(unit.floor_plan_id)


def _unit_payload(
    client: Client, visit_id: str, property_id: str, unit: VisitUnitInput, user_id: str
) -> dict[str, Any]:
    beds, baths, floor_plan_id = _resolve_unit_shape(client, property_id, unit)
    return {
        "visit_id": visit_id,
        "label": unit.label,
        "floor_plan_id": floor_plan_id,
        "beds": beds,
        "baths": float(baths),
        "display_order": unit.display_order,
        "created_by": user_id,
    }


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


async def create_visit(
    client: Client, hunt: dict[str, Any], user_id: str, body: VisitCreate
) -> VisitResponse:
    listing = (
        client.table("hunt_listings")
        .select("id")
        .eq("hunt_id", hunt["id"])
        .eq("property_id", str(body.property_id))
        .limit(1)
        .execute()
        .data
        or []
    )
    if not listing:
        raise PropertyNotInHunt(
            "That Property is not in this Hunt. Add the listing first so the "
            "visit has facts to check against."
        )

    inserted = (
        client.table("visits")
        .insert(
            {
                "hunt_id": hunt["id"],
                "property_id": str(body.property_id),
                "created_by": user_id,
                "scheduled_for": body.scheduled_for.isoformat() if body.scheduled_for else None,
                "prefilled_from": str(body.prefilled_from) if body.prefilled_from else None,
                "template_version": TEMPLATE_VERSION,
            }
        )
        .execute()
        .data
    )
    visit = inserted[0]

    if body.units:
        payload = [
            _unit_payload(client, visit["id"], str(body.property_id), unit, user_id)
            for unit in body.units
        ]
        client.table("visit_units").insert(payload).execute()

    return _visit_response(client, visit)


async def patch_visit(
    client: Client, visit: Visit, user_id: str, body: VisitPatch
) -> VisitResponse:
    """Apply a lifecycle transition.

    Timestamps come from the server clock, never the client's: a phone with a
    skewed clock must not be able to record a tour that started tomorrow.
    """
    now = datetime.now(UTC).isoformat()
    patch: dict[str, Any] = {}

    if body.action == "start":
        if visit["cancelled_at"] is not None:
            raise InvalidVisitTransition("This visit is cancelled. Reinstate it before starting.")
        if visit["started_at"] is None:
            patch["started_at"] = now
    elif body.action == "end":
        if visit["cancelled_at"] is not None:
            raise InvalidVisitTransition("This visit is cancelled.")
        if visit["started_at"] is None:
            raise InvalidVisitTransition("This visit has not started, so it cannot be ended.")
        patch["ended_at"] = now
    elif body.action == "reopen":
        # A tour is written on a phone and read on a desktop, and the desktop is
        # where the typo gets fixed and the half-heard answer finally gets
        # typed. Freezing the record at End would make the most reflective
        # moment read-only, so ending is a state rather than a seal.
        #
        # Deliberately an explicit action, not silent editability of a completed
        # Visit: it moves the derived state back to in-progress, which every
        # surface already understands and Realtime already broadcasts, instead
        # of adding a third editability rule for the trigger, the API and the UI
        # to keep in step. Nothing is lost either way — entries are append-only
        # and timestamped, so a later edit is visibly later.
        if visit["cancelled_at"] is not None:
            raise InvalidVisitTransition("This visit is cancelled. Reinstate it before reopening.")
        if visit["ended_at"] is None:
            raise InvalidVisitTransition("This visit has not ended, so there is nothing to reopen.")
        # VC-9: `ended_at` is never cleared. The tour ended when it ended — that
        # is a fact about a real afternoon, and nulling it to move the derived
        # state was destroying it to record something else entirely. Only the
        # most recent reopen is kept; a second one replaces it.
        patch["reopened_at"] = now
    elif body.action == "cancel":
        if not caller_may_cancel(client, visit, user_id):
            raise CannotCancelVisit("Only the visit's creator or the Hunt Owner can cancel it.")
        patch["cancelled_at"] = now
        patch["cancel_reason"] = body.cancel_reason
    elif body.action == "reinstate":
        if not caller_may_cancel(client, visit, user_id):
            raise CannotCancelVisit("Only the visit's creator or the Hunt Owner can reinstate it.")
        if visit["cancelled_at"] is None:
            raise InvalidVisitTransition("This visit is not cancelled.")
        patch["cancelled_at"] = None
        patch["cancel_reason"] = None

    if "scheduled_for" in body.model_fields_set:
        patch["scheduled_for"] = body.scheduled_for.isoformat() if body.scheduled_for else None

    if not patch:
        return _visit_response(client, visit)

    updated = client.table("visits").update(patch).eq("id", visit["id"]).execute().data
    # RLS or the trigger refusing leaves no row; surface it as the permission
    # failure it is rather than a 500 on an empty list.
    if not updated:
        raise CannotCancelVisit("That change was refused.")
    return _visit_response(client, updated[0])


async def delete_visit(client: Client, visit: Visit, user_id: str) -> None:
    if not caller_may_cancel(client, visit, user_id):
        from manzil_api.visits.exceptions import CannotDeleteVisit

        raise CannotDeleteVisit("Only the visit's creator or the Hunt Owner can delete it.")
    client.table("visits").delete().eq("id", visit["id"]).execute()


async def add_unit(
    client: Client, visit: Visit, user_id: str, unit: VisitUnitInput
) -> VisitUnitResponse:
    existing = (
        client.table("visit_units").select("label").eq("visit_id", visit["id"]).execute().data or []
    )
    if len(existing) >= MAX_UNITS_PER_VISIT:
        raise TooManyVisitUnits(f"A visit carries at most {MAX_UNITS_PER_VISIT} units.")
    if unit.label.casefold() in {row["label"].casefold() for row in existing}:
        raise DuplicateVisitUnitLabel(f"This visit already has a unit called {unit.label!r}.")

    payload = _unit_payload(client, visit["id"], visit["property_id"], unit, user_id)
    inserted = client.table("visit_units").insert(payload).execute().data
    return VisitUnitResponse.model_validate(inserted[0])


async def patch_unit(
    client: Client, visit: Visit, unit_id: UUID, body: VisitUnitPatch
) -> VisitUnitResponse:
    rows = (
        client.table("visit_units")
        .select("*")
        .eq("id", str(unit_id))
        .eq("visit_id", visit["id"])
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise VisitUnitNotFound(f"Visit unit {unit_id} not found on this visit")

    patch: dict[str, Any] = {}
    if body.label is not None:
        clash = (
            client.table("visit_units")
            .select("id,label")
            .eq("visit_id", visit["id"])
            .neq("id", str(unit_id))
            .execute()
            .data
            or []
        )
        if body.label.casefold() in {row["label"].casefold() for row in clash}:
            raise DuplicateVisitUnitLabel(f"This visit already has a unit called {body.label!r}.")
        patch["label"] = body.label
    if body.display_order is not None:
        patch["display_order"] = body.display_order

    updated = client.table("visit_units").update(patch).eq("id", str(unit_id)).execute().data
    return VisitUnitResponse.model_validate(updated[0])


async def delete_unit(client: Client, visit: Visit, unit_id: UUID) -> None:
    deleted = (
        client.table("visit_units")
        .delete()
        .eq("id", str(unit_id))
        .eq("visit_id", visit["id"])
        .execute()
        .data
    )
    if not deleted:
        raise VisitUnitNotFound(f"Visit unit {unit_id} not found on this visit")


# ---------------------------------------------------------------------------
# Entries (VC-3)
# ---------------------------------------------------------------------------


def _item_shapes(client: Client, visit: Visit) -> dict[tuple[str, bool], dict[str, str]]:
    """`(item_key, is_custom)` → its declared `kind` and `scope`.

    Resolved against the Visit's **frozen** `template_version`, so a later
    template edit never changes what an existing Visit's answers mean.
    """
    template = (
        client.table("visit_template_items")
        .select("key,kind,scope")
        .eq("version", visit["template_version"])
        .execute()
        .data
        or []
    )
    custom = (
        client.table("visit_custom_items")
        .select("id,kind,scope")
        .eq("visit_id", visit["id"])
        .execute()
        .data
        or []
    )
    shapes: dict[tuple[str, bool], dict[str, str]] = {
        (row["key"], False): {"kind": row["kind"], "scope": row["scope"]} for row in template
    }
    shapes.update(
        {(row["id"], True): {"kind": row["kind"], "scope": row["scope"]} for row in custom}
    )
    return shapes


def _item_labels(client: Client, visit: Visit) -> dict[tuple[str, bool], str]:
    template = (
        client.table("visit_template_items")
        .select("key,label")
        .eq("version", visit["template_version"])
        .execute()
        .data
        or []
    )
    custom = (
        client.table("visit_custom_items")
        .select("id,label")
        .eq("visit_id", visit["id"])
        .execute()
        .data
        or []
    )
    labels: dict[tuple[str, bool], str] = {(row["key"], False): row["label"] for row in template}
    labels.update({(row["id"], True): row["label"] for row in custom})
    return labels


def _promote_failed_checks(
    client: Client,
    visit: Visit,
    user_id: str,
    body: VisitEntryBatch,
    shapes: dict[tuple[str, bool], dict[str, str]],
) -> None:
    """A Check marked as a problem becomes a Defect (DESIGN §9.7).

    This is the whole reason the defect log is usable: the source document's
    defect table is one nobody transcribes into mid-tour, so it fills itself.

    **Once-only per (visit, item, unit), including rows since deleted.** Toggling
    a Check off and on must not resurrect a defect somebody deliberately removed,
    and must never create a second copy — a partial unique index enforces that,
    and the conflict is swallowed here rather than surfacing as a 500.
    """
    failed = [
        entry
        for entry in body.entries
        if entry.value == "problem"
        and shapes.get((entry.item_key, entry.is_custom), {}).get("kind") == "check"
    ]
    if not failed:
        return

    labels = _item_labels(client, visit)
    for entry in failed:
        title = labels.get((entry.item_key, entry.is_custom), entry.item_key)
        try:
            client.table("visit_defects").insert(
                {
                    "visit_id": visit["id"],
                    "visit_unit_id": str(entry.visit_unit_id) if entry.visit_unit_id else None,
                    "from_item_key": entry.item_key,
                    "title": title,
                    # The member's note on the check travels with it — that note
                    # is usually the description of the problem.
                    "note": entry.note,
                    "created_by": user_id,
                }
            ).execute()
        except APIError as error:
            # 23505: this check already promoted once. That is the contract, not
            # a failure — the answer still saved.
            if getattr(error, "code", None) != "23505":
                raise


async def save_entries(
    client: Client, visit: Visit, user_id: str, body: VisitEntryBatch
) -> list[VisitEntryResponse]:
    """Append a batch of answers and return the resulting current values.

    Append-only: nothing is updated in place, so clearing an answer means
    sending a null `value`, which lands as that identity's tombstone.
    """
    shapes = _item_shapes(client, visit)
    unit_ids = {
        row["id"]
        for row in (
            client.table("visit_units").select("id").eq("visit_id", visit["id"]).execute().data
            or []
        )
    }

    payload: list[dict[str, Any]] = []
    for entry in body.entries:
        shape = shapes.get((entry.item_key, entry.is_custom))
        if shape is None:
            raise UnknownChecklistItem(
                f"{entry.item_key!r} is not an item on this visit's checklist"
            )
        kind, scope = shape["kind"], shape["scope"]
        unit_id = str(entry.visit_unit_id) if entry.visit_unit_id else None

        if scope == "unit" and unit_id is None:
            raise ChecklistScopeMismatch(
                f"{entry.item_key!r} is answered per unit, so it needs a visit_unit_id"
            )
        if scope == "property" and unit_id is not None:
            raise ChecklistScopeMismatch(
                f"{entry.item_key!r} is answered once for the property, "
                "so it must not carry a visit_unit_id"
            )
        if unit_id is not None and unit_id not in unit_ids:
            raise VisitUnitNotOnVisit(f"Unit {unit_id} is not on this visit")
        if kind == "question" and entry.value is not None:
            # A Question's answer is its text — the typed answer *is* the
            # checkmark (DESIGN §9.7), so a separate value would be a second,
            # contradictory source of "was this asked".
            raise ChecklistValueNotAllowed(
                f"{entry.item_key!r} is a question: send answer_text, not value"
            )

        payload.append(
            {
                "visit_id": visit["id"],
                "item_key": entry.item_key,
                "is_custom": entry.is_custom,
                "visit_unit_id": unit_id,
                # An Impression is keyed to its author; shared kinds are not.
                "owner_user_id": user_id if kind == "impression" else None,
                "author_user_id": user_id,
                "value": entry.value,
                "answer_text": entry.answer_text,
                "note": entry.note,
                "prev_entry_id": str(entry.prev_entry_id) if entry.prev_entry_id else None,
            }
        )

    client.table("visit_entries").insert(payload).execute()
    _promote_failed_checks(client, visit, user_id, body, shapes)

    # Return current values rather than the inserted rows: for an identity that
    # another member has since written, the caller needs what is now true.
    identities = {(row["item_key"], row["visit_unit_id"], row["owner_user_id"]) for row in payload}
    current = (
        client.table("current_visit_entries")
        .select("*")
        .eq("visit_id", visit["id"])
        .in_("item_key", sorted({row["item_key"] for row in payload}))
        .execute()
        .data
        or []
    )
    return [
        VisitEntryResponse.model_validate(row)
        for row in current
        if (row["item_key"], row["visit_unit_id"], row["owner_user_id"]) in identities
    ]


async def create_defect(
    client: Client, visit: Visit, user_id: str, body: VisitDefectCreate
) -> VisitDefectResponse:
    if body.visit_unit_id is not None:
        units = (
            client.table("visit_units")
            .select("id")
            .eq("visit_id", visit["id"])
            .eq("id", str(body.visit_unit_id))
            .execute()
            .data
            or []
        )
        if not units:
            raise VisitUnitNotOnVisit(f"Unit {body.visit_unit_id} is not on this visit")

    inserted = (
        client.table("visit_defects")
        .insert(
            {
                "visit_id": visit["id"],
                "visit_unit_id": str(body.visit_unit_id) if body.visit_unit_id else None,
                "title": body.title,
                "note": body.note,
                "severity": body.severity,
                "promised_in_writing": body.promised_in_writing,
                "resolution": body.resolution,
                "created_by": user_id,
            }
        )
        .execute()
        .data
    )
    return VisitDefectResponse.model_validate(inserted[0])


async def patch_defect(
    client: Client, visit: Visit, defect_id: UUID, body: VisitDefectPatch
) -> VisitDefectResponse:
    patch = body.model_dump(exclude_unset=True)
    updated = (
        client.table("visit_defects")
        .update(patch)
        .eq("id", str(defect_id))
        .eq("visit_id", visit["id"])
        .is_("deleted_at", "null")
        .execute()
        .data
    )
    if not updated:
        raise VisitDefectNotFound(f"Defect {defect_id} not found on this visit")
    return VisitDefectResponse.model_validate(updated[0])


async def delete_defect(client: Client, visit: Visit, defect_id: UUID) -> None:
    """Soft delete.

    The Check that promoted this defect keeps its answer: the two are separate
    records of separate things — that a test failed, and what the problem was.
    """
    deleted = (
        client.table("visit_defects")
        .update({"deleted_at": datetime.now(UTC).isoformat()})
        .eq("id", str(defect_id))
        .eq("visit_id", visit["id"])
        .is_("deleted_at", "null")
        .execute()
        .data
    )
    if not deleted:
        raise VisitDefectNotFound(f"Defect {defect_id} not found on this visit")


async def create_custom_item(
    client: Client, visit: Visit, user_id: str, body: VisitCustomItemCreate
) -> VisitCustomItemResponse:
    inserted = (
        client.table("visit_custom_items")
        .insert(
            {
                "visit_id": visit["id"],
                "section_key": body.section_key,
                "kind": body.kind,
                "scope": body.scope,
                "label": body.label,
                "created_by": user_id,
            }
        )
        .execute()
        .data
    )
    return VisitCustomItemResponse.model_validate(inserted[0])


# ---------------------------------------------------------------------------
# Fee Proposals (VC-7)
# ---------------------------------------------------------------------------


def _proposal_response(row: dict[str, Any]) -> VisitFeeProposalResponse:
    return VisitFeeProposalResponse.model_validate(row)


async def create_fee_proposal(
    client: Client,
    visit: dict[str, Any],
    user_id: str,
    body: VisitFeeProposalCreate,
) -> VisitFeeProposalResponse:
    """Offer a confirmed figure to a Listing.

    Any member may offer one — whoever walked the unit is who heard the number.
    Deciding is the privileged half.

    Re-confirming the same destination **updates the standing offer** rather
    than stacking a second one: two live offers for one fee slot would ask the
    reader the same question twice with different numbers, and the database
    carries a partial unique index saying so.
    """
    listing = (
        client.table("hunt_listings")
        .select("property_id")
        .eq("id", str(body.hunt_listing_id))
        .maybe_single()
        .execute()
    )
    row = listing.data if listing else None
    if row is None or row["property_id"] != visit["property_id"]:
        # RLS may also hide a Listing in another Hunt; either way the caller is
        # pointing this Visit at something it did not tour.
        raise ListingNotVisitedProperty(
            "A Visit may only propose figures to a Listing of the Property it toured"
        )

    payload = {
        "visit_id": visit["id"],
        "visit_unit_id": str(body.visit_unit_id) if body.visit_unit_id else None,
        "hunt_listing_id": str(body.hunt_listing_id),
        "target": body.target,
        "target_key": body.target_key,
        "amount": body.amount,
        "note": body.note,
        "created_by": user_id,
    }
    existing = (
        client.table("visit_fee_proposals")
        .select("id")
        .eq("visit_id", visit["id"])
        .eq("hunt_listing_id", str(body.hunt_listing_id))
        .eq("target", body.target)
        .eq("target_key", body.target_key)
        .eq("status", "pending")
        .execute()
        .data
    )
    if existing:
        updated = (
            client.table("visit_fee_proposals")
            .update(
                {
                    "amount": body.amount,
                    "note": body.note,
                    "visit_unit_id": payload["visit_unit_id"],
                }
            )
            .eq("id", existing[0]["id"])
            .execute()
            .data
        )
        return _proposal_response(updated[0])

    try:
        created = client.table("visit_fee_proposals").insert(payload).execute().data
    except APIError as error:
        if error.code == "23514":
            raise VisitUnitNotOnVisit("That unit does not belong to this Visit") from error
        raise
    return _proposal_response(created[0])


async def decide_fee_proposal(
    client: Client,
    visit: dict[str, Any],
    proposal_id: UUID,
    user_id: str,
    action: str,
) -> VisitFeeProposalResponse:
    """Accept or reject an offer.

    **Accepting delegates to the ordinary cost writers** — `fees.upsert_fee` or
    `overrides.create_override` — rather than writing the destination table
    here. That is the whole design: the resulting row is indistinguishable from
    one a human typed into the drawer, so provenance markers, rescore enqueueing
    and the Member-owns-their-own-Listing permission all keep working unchanged
    instead of being reimplemented and drifting.

    **Rejecting writes only the decision.** The Visit's own record of what the
    agent said is untouched — that a figure was quoted and that it was declined
    are two separate facts (R7).
    """
    found = (
        client.table("visit_fee_proposals")
        .select("*")
        .eq("id", str(proposal_id))
        .eq("visit_id", visit["id"])
        .maybe_single()
        .execute()
    )
    proposal = found.data if found else None
    if proposal is None:
        raise FeeProposalNotFound("No such Fee Proposal on this Visit")
    if proposal["status"] != "pending":
        raise FeeProposalAlreadyDecided(f"This proposal was already {proposal['status']}")

    if action == "accept":
        await _apply_fee_proposal(client, visit, proposal, user_id)

    decided = (
        client.table("visit_fee_proposals")
        .update(
            {
                "status": "accepted" if action == "accept" else "rejected",
                "decided_by": user_id,
                "decided_at": datetime.now(UTC).isoformat(),
            }
        )
        .eq("id", str(proposal_id))
        # Only a pending row may be decided: two people tapping ✓ at once must
        # not both write the cost.
        .eq("status", "pending")
        .execute()
        .data
    )
    if not decided:
        raise FeeProposalAlreadyDecided("This proposal was decided by someone else")
    return _proposal_response(decided[0])


async def _apply_fee_proposal(
    client: Client,
    visit: dict[str, Any],
    proposal: dict[str, Any],
    user_id: str,
) -> None:
    """Perform the ordinary human write the proposal was offering."""
    hunt_listing_id = UUID(proposal["hunt_listing_id"])
    hunt_id = UUID(visit["hunt_id"])
    amount = float(proposal["amount"])

    if proposal["target"] == "fee_slot":
        await upsert_fee(
            client,
            hunt_listing_id=hunt_listing_id,
            hunt_id=hunt_id,
            user_id=user_id,
            fee_slot=proposal["target_key"],
            body=FeeEntryUpsert(
                amount=amount,
                # `manual`, deliberately: the accepted figure must be
                # indistinguishable from one a human typed into the drawer,
                # because that is exactly what it is — a person confirmed it on
                # site and a person chose to accept it. Minting a separate
                # "from a visit" provenance would fork every downstream marker.
                value_state=ValueState.MANUAL,
            ),
        )
        return

    # Scope has to match what the drawer would have written for the same edit,
    # or accepting would quietly have a broader effect than typing it by hand.
    # §9.6: a quoted rent corrects **the plan you were standing in**, not every
    # layout at the Property — and a Visit usually knows which, because the unit
    # points at its Floor Plan. A described unit that matched no advertised plan
    # has none, and then Property scope is the honest fallback, exactly as the
    # drawer does when no plan is in view. `all_in_monthly` stays Property-wide.
    plan_id: str | None = None
    if proposal["target_key"] == "base_rent" and proposal["visit_unit_id"]:
        unit = (
            client.table("visit_units")
            .select("floor_plan_id")
            .eq("id", proposal["visit_unit_id"])
            .maybe_single()
            .execute()
        )
        plan_id = (unit.data or {}).get("floor_plan_id") if unit else None

    scope: dict[str, Any] = (
        {
            "target_scope": "floor_plan",
            "floor_plan_id": plan_id,
            "applicability": "specific_floor_plans",
        }
        if plan_id
        else {}
    )

    await create_override(
        client,
        hunt_listing_id=hunt_listing_id,
        hunt_id=hunt_id,
        user_id=user_id,
        body=OverrideCreate(
            criterion_key=proposal["target_key"],
            value=amount,
            note=proposal["note"] or "Confirmed on a Visit",
            **scope,
        ),
    )


async def withdraw_fee_proposal(
    client: Client,
    visit: dict[str, Any],
    proposal_id: UUID,
) -> None:
    """Take back an offer nobody has acted on. RLS restricts this to its author."""
    deleted = (
        client.table("visit_fee_proposals")
        .delete()
        .eq("id", str(proposal_id))
        .eq("visit_id", visit["id"])
        .execute()
        .data
    )
    if not deleted:
        raise FeeProposalNotFound("No such pending Fee Proposal on this Visit")
