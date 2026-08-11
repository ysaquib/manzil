"""Rubric service — validate options vs catalog value_schema (jsonschema), write
rows, bump `hunts.rubric_version`, enqueue a hunt-level rescore job (P1-5)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import jsonschema
from manzil_shared.catalog import CATALOG
from manzil_shared.models import CustomCriterionDef, MatchOp, RequiresTool, RubricOption
from manzil_worker.llm.client import RunContext, run_context
from manzil_worker.llm.client import call_structured as llm_call_structured
from pydantic import BaseModel, Field

from manzil_api.jobs.enqueue import enqueue_rescore
from manzil_api.rubric.exceptions import InvalidRubricOption, RoutingUnavailable
from manzil_api.rubric.schemas import (
    CustomRoutingRequest,
    CustomRoutingResponse,
    RubricCriterionOut,
    RubricPut,
)
from supabase import Client


@dataclass(frozen=True)
class RubricSaveResult:
    criteria: list[RubricCriterionOut]
    backfill_count: int


_CATALOG_BY_KEY = {entry.key: entry for entry in CATALOG}


def _derive_is_bonus(options: list[RubricOption], unknown_delta: float) -> bool:
    """A pure bonus can never dock points or fire a dealbreaker Gate."""
    return (
        bool(options)
        and unknown_delta >= 0
        and all(option.delta >= 0 and option.dealbreaker_set_score is None for option in options)
    )


def _validate_option_schema(label: str, schema: dict[str, Any], option: RubricOption) -> None:
    schema_type = schema.get("type")
    op = option.match.op
    array_ops = (MatchOp.CONTAINS_ANY, MatchOp.CONTAINS_ALL)
    if schema_type == "array":
        if op not in array_ops:
            raise InvalidRubricOption(
                f"Option operator for {label} invalid: array criteria use "
                "contains_any or contains_all"
            )
        instance = option.match.value
    else:
        if op in array_ops:
            raise InvalidRubricOption(
                f"Option operator for {label} invalid: {op.value} requires an array criterion"
            )
        if (
            schema_type == "string"
            and schema.get("format") == "date"
            and op
            not in (
                MatchOp.LT,
                MatchOp.GT,
                MatchOp.RANGE,
            )
        ):
            raise InvalidRubricOption(
                f"Option operator for {label} invalid: date criteria use before, after, or between"
            )
        if op is MatchOp.IN:
            values = option.match.value
            if not isinstance(values, list) or not values:
                raise InvalidRubricOption(
                    f"Option value for {label} invalid: in requires a non-empty array"
                )
            try:
                for value in values:
                    jsonschema.validate(instance=value, schema=schema)
            except jsonschema.ValidationError as error:
                raise InvalidRubricOption(
                    f"Option value for {label} invalid: {error.message}"
                ) from error
            return
        if op is MatchOp.RANGE:
            values = option.match.value
            if not isinstance(values, list) or len(values) != 2:
                raise InvalidRubricOption(
                    f"Option value for {label} invalid: range requires exactly two values"
                )
            instances = values
        else:
            instances = [option.match.value]
        try:
            for value in instances:
                jsonschema.validate(
                    instance=value,
                    schema=schema,
                    format_checker=jsonschema.FormatChecker(),
                )
        except jsonschema.ValidationError as error:
            raise InvalidRubricOption(
                f"Option value for {label} invalid: {error.message}"
            ) from error
        if op is MatchOp.RANGE and instances[0] > instances[1]:
            raise InvalidRubricOption(f"Option value for {label} invalid: range start exceeds end")
        return
    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as error:
        raise InvalidRubricOption(f"Option value for {label} invalid: {error.message}") from error


def _validate_option(catalog_key: str, option: RubricOption) -> None:
    entry = _CATALOG_BY_KEY.get(catalog_key)
    if entry is None:
        raise InvalidRubricOption(f"Unknown catalog key: {catalog_key}")
    _validate_option_schema(catalog_key, entry.value_schema, option)


class _RoutingClassification(BaseModel):
    requires_tool: RequiresTool | None = None
    reason: str = Field(min_length=1, max_length=300)


async def classify_custom_routing(
    hunt_id: UUID,
    user_id: str,
    body: CustomRoutingRequest,
) -> CustomRoutingResponse:
    content = json.dumps(
        {"label": body.label.strip(), "description": body.description.strip()},
        sort_keys=True,
    )
    try:
        with run_context(
            RunContext(
                job_type="rubric_authoring",
                job_id=f"{hunt_id}:{user_id}",
                mode="workflow",
            )
        ):
            result = await llm_call_structured("custom_route", _RoutingClassification, content)
    except Exception as error:
        raise RoutingUnavailable("Could not classify the custom Criterion route") from error
    return CustomRoutingResponse(
        key=f"custom:{uuid4()}",
        suggested_requires_tool=result.requires_tool,
        reason=result.reason,
        supported=result.requires_tool in (None, RequiresTool.MAPS),
    )


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


async def put_rubric(
    client: Client, hunt_id: UUID, user_id: str, body: RubricPut
) -> RubricSaveResult:
    existing_rows = (
        client.table("rubric_criteria")
        .select("custom_def")
        .eq("hunt_id", str(hunt_id))
        .not_.is_("custom_def", "null")
        .execute()
        .data
        or []
    )
    existing_defs = {
        parsed.key: parsed
        for row in existing_rows
        if (parsed := CustomCriterionDef.model_validate(row["custom_def"]))
    }
    custom_keys: set[str] = set()
    custom_defs_by_key: dict[str, CustomCriterionDef] = {}
    for crit in body.criteria:
        if crit.catalog_key is None and crit.custom_def is None:
            raise InvalidRubricOption("Each criterion needs catalog_key or custom_def")
        if crit.catalog_key is not None and crit.custom_def is not None:
            raise InvalidRubricOption("Criterion cannot have both catalog_key and custom_def")
        if crit.catalog_key is not None:
            for option in crit.options:
                _validate_option(crit.catalog_key, option)
        else:
            assert crit.custom_def is not None
            custom = crit.custom_def
            if custom.key in custom_keys:
                raise InvalidRubricOption(f"Duplicate custom Criterion key: {custom.key}")
            custom_keys.add(custom.key)
            custom_defs_by_key[custom.key] = custom
            prior = existing_defs.get(custom.key)
            if prior is not None:
                semantic_fields = (
                    "description",
                    "fact_scope",
                    "value_schema",
                    "requires_tool",
                    "acquisition",
                )
                if any(
                    getattr(prior, field) != getattr(custom, field) for field in semantic_fields
                ):
                    raise InvalidRubricOption(
                        "Changing a custom Criterion's acquisition semantics requires a new key"
                    )
            for option in crit.options:
                _validate_option_schema(custom.label, custom.value_schema, option)

    client.table("rubric_criteria").delete().eq("hunt_id", str(hunt_id)).execute()

    rows: list[dict[str, Any]] = []
    for crit in body.criteria:
        is_bonus = _derive_is_bonus(crit.options, crit.unknown_delta)
        row = {
            "hunt_id": str(hunt_id),
            "catalog_key": crit.catalog_key,
            "custom_def": (
                crit.custom_def.model_dump(mode="json") if crit.custom_def is not None else None
            ),
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

    await enqueue_rescore(client, hunt_id, requested_by=user_id)
    new_keys = sorted(
        key for key in custom_keys - set(existing_defs) if not custom_defs_by_key[key].is_manual
    )
    backfill_count = 0
    if new_keys:
        listings = (
            client.table("hunt_listings")
            .select(
                "id, hunt_id, submitted_source_id, "
                "property_sources!hunt_listings_submitted_source_property_fkey(url)"
            )
            .eq("hunt_id", str(hunt_id))
            .eq("status", "active")
            .execute()
            .data
            or []
        )
        jobs = []
        for listing in listings:
            source = listing.get("property_sources") or {}
            url = source.get("url")
            if not url:
                continue
            jobs.append(
                {
                    "hunt_id": str(hunt_id),
                    "hunt_listing_id": listing["id"],
                    "type": "refresh",
                    "state": "queued",
                    "requested_by": user_id,
                    "payload": {
                        "url": url,
                        "hunt_id": str(hunt_id),
                        "listing_id": listing["id"],
                        "scope": "custom_match",
                        "custom_criterion_keys": new_keys,
                        "trigger": "rubric:custom-backfill",
                    },
                }
            )
        if jobs:
            # `minimal`: the rows are not read back, and a representation is a
            # `select *` on `jobs`, whose `payload` is withheld from members.
            client.table("jobs").insert(jobs, returning="minimal").execute()
            backfill_count = len(jobs)
    return RubricSaveResult(
        criteria=await get_rubric(client, hunt_id),
        backfill_count=backfill_count,
    )
