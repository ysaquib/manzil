"""Overrides service — append-only insert with attribution, then enqueue one
hunt-level rescore job (rescore-on-mutation, plan §1.7)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import jsonschema
from manzil_shared.models import CustomCriterionDef
from pydantic import ValidationError

from manzil_api.hunts.exceptions import InsufficientRole
from manzil_api.jobs.enqueue import enqueue_rescore
from manzil_api.overrides.exceptions import InvalidOverrideTarget, InvalidOverrideValue
from manzil_api.overrides.schemas import OverrideCreate, OverrideResponse
from supabase import Client


def _row_to_response(row: dict[str, Any]) -> OverrideResponse:
    return OverrideResponse.model_validate(row)


def _find_manual_custom_def(
    client: Client, hunt_id: UUID, criterion_key: str
) -> CustomCriterionDef | None:
    """A manual custom Criterion has no producer, so its Override is the only
    input path — look up the hunt's Rubric row to validate against it."""
    if not criterion_key.startswith("custom:"):
        return None
    rows = (
        client.table("rubric_criteria")
        .select("custom_def")
        .eq("hunt_id", str(hunt_id))
        .eq("custom_def->>key", criterion_key)
        .execute()
        .data
        or []
    )
    for row in rows:
        try:
            custom = CustomCriterionDef.model_validate(row["custom_def"])
        except ValidationError:
            # A stored definition this build cannot parse is a Rubric problem,
            # not an Override problem. Refusing the write here would break an
            # unrelated Criterion's Override for a row nobody is touching.
            continue
        if custom.is_manual:
            return custom
    return None


def _validate_manual_override(custom: CustomCriterionDef, body: OverrideCreate) -> None:
    expected_scope = "floor_plan" if custom.fact_scope == "floor_plan" else "property"
    if body.target_scope != expected_scope:
        raise InvalidOverrideValue(
            f"{custom.label} is {custom.fact_scope}-scoped; the Override must target "
            f"{expected_scope}, not {body.target_scope}"
        )
    if body.value is None:
        # A null Override is the §9.6 tombstone that reverts to unknown — the
        # only way to un-answer a manual Criterion. It is not a value to check.
        return
    try:
        jsonschema.validate(instance=body.value, schema=custom.value_schema)
    except jsonschema.ValidationError as error:
        raise InvalidOverrideValue(
            f"Override value for {custom.label} invalid: {error.message}"
        ) from error


async def create_override(
    client: Client,
    *,
    hunt_listing_id: UUID,
    hunt_id: UUID,
    user_id: str,
    body: OverrideCreate,
    authorized_admin: bool = False,
) -> OverrideResponse:
    listing = (
        client.table("hunt_listings")
        .select("added_by,property_id")
        .eq("id", str(hunt_listing_id))
        .single()
        .execute()
        .data
    )
    role = None
    if not authorized_admin:
        role = (
            client.table("hunt_members")
            .select("role")
            .eq("hunt_id", str(hunt_id))
            .eq("user_id", user_id)
            .single()
            .execute()
            .data["role"]
        )
    if not authorized_admin and role == "member" and listing["added_by"] != user_id:
        raise InsufficientRole("Members may Override only their own Listings")
    if body.floor_plan_id is not None:
        floor_plan_response = (
            client.table("floor_plans")
            .select("id")
            .eq("id", str(body.floor_plan_id))
            .eq("property_id", listing["property_id"])
            .maybe_single()
            .execute()
        )
        floor_plan = floor_plan_response.data if floor_plan_response is not None else None
        if floor_plan is None:
            raise InvalidOverrideTarget("Floor Plan does not belong to the Listing's Property")
    manual_def = _find_manual_custom_def(client, hunt_id, body.criterion_key)
    if manual_def is not None:
        _validate_manual_override(manual_def, body)
    response = (
        client.table("overrides")
        .insert(
            {
                "hunt_listing_id": str(hunt_listing_id),
                "criterion_key": body.criterion_key,
                "target_scope": body.target_scope,
                "floor_plan_id": str(body.floor_plan_id) if body.floor_plan_id else None,
                "applicability": body.applicability,
                "value": body.value,
                "user_id": user_id,
                "note": body.note,
            }
        )
        .execute()
    )
    row = (response.data or [None])[0]
    if row is None:
        raise RuntimeError("override insert returned no row")
    await enqueue_rescore(client, hunt_id)
    return _row_to_response(row)
