"""Rubric service — validate options vs catalog value_schema (jsonschema), write
rows, bump `hunts.rubric_version`, enqueue a hunt-level rescore job (P1-5)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import jsonschema
from manzil_shared.catalog import CATALOG
from manzil_shared.models import MatchOp, RubricOption

from manzil_api.jobs.enqueue import enqueue_rescore
from manzil_api.rubric.exceptions import InvalidRubricOption
from manzil_api.rubric.schemas import RubricCriterionOut, RubricPut
from supabase import Client

_CATALOG_BY_KEY = {entry.key: entry for entry in CATALOG}


def _derive_is_bonus(options: list[RubricOption], unknown_delta: float) -> bool:
    """A pure bonus can never dock points or fire a dealbreaker Gate."""
    return bool(options) and unknown_delta >= 0 and all(
        option.delta >= 0 and option.dealbreaker_set_score is None for option in options
    )


def _validate_option(catalog_key: str, option: RubricOption) -> None:
    entry = _CATALOG_BY_KEY.get(catalog_key)
    if entry is None:
        raise InvalidRubricOption(f"Unknown catalog key: {catalog_key}")
    # Threshold/range ops carry composite match values — only scalar matches are
    # validated against value_schema (DESIGN §9.2; RANGE/LT/GT are not page values).
    if option.match.op not in (MatchOp.EQ, MatchOp.IN, MatchOp.BOOL):
        return
    try:
        jsonschema.validate(instance=option.match.value, schema=entry.value_schema)
    except jsonschema.ValidationError as error:
        raise InvalidRubricOption(
            f"Option value for {catalog_key} invalid: {error.message}"
        ) from error


def _row_to_out(row: dict[str, Any]) -> RubricCriterionOut:
    options = [RubricOption.model_validate(o) for o in row["options"]]
    nn = row.get("non_negotiable")
    return RubricCriterionOut(
        id=row["id"],
        hunt_id=row["hunt_id"],
        catalog_key=row.get("catalog_key"),
        custom_def=row.get("custom_def"),
        enabled=row["enabled"],
        options=options,
        unknown_delta=float(row["unknown_delta"]),
        non_negotiable=nn,
        is_bonus=row["is_bonus"],
        position=row["position"],
    )


async def get_rubric(client: Client, hunt_id: UUID) -> list[RubricCriterionOut]:
    response = (
        client.table("rubric_criteria")
        .select("*")
        .eq("hunt_id", str(hunt_id))
        .eq("enabled", True)
        .order("position")
        .execute()
    )
    return [_row_to_out(row) for row in response.data or []]


async def put_rubric(client: Client, hunt_id: UUID, body: RubricPut) -> list[RubricCriterionOut]:
    for crit in body.criteria:
        if crit.catalog_key is None and crit.custom_def is None:
            raise InvalidRubricOption("Each criterion needs catalog_key or custom_def")
        if crit.catalog_key is not None and crit.custom_def is not None:
            raise InvalidRubricOption("Criterion cannot have both catalog_key and custom_def")
        if crit.catalog_key is not None:
            for option in crit.options:
                _validate_option(crit.catalog_key, option)

    client.table("rubric_criteria").delete().eq("hunt_id", str(hunt_id)).execute()

    rows: list[dict[str, Any]] = []
    for crit in body.criteria:
        is_bonus = _derive_is_bonus(crit.options, crit.unknown_delta)
        row = {
            "hunt_id": str(hunt_id),
            "catalog_key": crit.catalog_key,
            "custom_def": crit.custom_def,
            "enabled": crit.enabled,
            "options": [o.model_dump(mode="json") for o in crit.options],
            "unknown_delta": crit.unknown_delta,
            "non_negotiable": crit.non_negotiable.model_dump(mode="json")
            if crit.non_negotiable
            else None,
            "is_bonus": is_bonus,
            "position": crit.position,
        }
        rows.append(row)

    if rows:
        client.table("rubric_criteria").insert(rows).execute()

    hunt = client.table("hunts").select("rubric_version").eq("id", str(hunt_id)).execute()
    current = (hunt.data or [{}])[0].get("rubric_version", 0)
    client.table("hunts").update({"rubric_version": current + 1}).eq("id", str(hunt_id)).execute()

    await enqueue_rescore(client, hunt_id)
    return await get_rubric(client, hunt_id)
