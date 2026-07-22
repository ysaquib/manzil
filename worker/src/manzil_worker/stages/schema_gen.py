"""Dynamic extraction schema (P0-8, DESIGN §10.2 P1, §8.2).

Generated at runtime from `criteria_catalog` via dynamic Pydantic model
creation — the catalog is the single source of truth and the schema is never
hand-maintained. Every criterion field is `{value, confidence,
evidence_quote}`; the catalog's label + extraction_hint ride along as the
field description, so hints reach the model inside the (cached) tool schema
rather than being duplicated into prompts.

Included fields: catalog entries extractable from page text — `requires_tool`
None and not pipeline-composed (`all_in_monthly` is composed per §9.5, its
hint says "never extracted directly"). Tool-dependent criteria (maps,
web-search) enter at ENRICH/CUSTOM_MATCH (Phase 3); extraction stages get
zero tools (§16).
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from manzil_shared.catalog import CATALOG
from manzil_shared.models import CatalogEntry, Confidence
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    create_model,
    model_validator,
)

from manzil_worker.state import (
    FloorPlanIn,
    HeatingIn,
    MandatoryFeesIn,
    OneTimeFeesIn,
    PetCostsIn,
    PropertyIdentityIn,
    UtilitiesIn,
)

# Composed by the pipeline, never extracted from the page (§9.5).
COMPOSED_KEYS = frozenset({"all_in_monthly"})


def _maybe_decode_container(data: Any) -> Any:
    """A JSON *string* whose content is an object/array -> the parsed container;
    everything else (including malformed pseudo-JSON — a model hand-building a
    string can botch inner quoting, which no parser can salvage) passes through
    for the real validator to reject."""
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            return data
        return parsed if isinstance(parsed, (dict, list)) else data
    return data


def _parse_stringified_field(cls: type[BaseModel], data: Any) -> Any:
    """Some models emit a nested `{value, confidence, evidence_quote}` field as a
    JSON *string* instead of an object (seen on date fields with haiku). Parse it
    back into a dict so a well-formed-but-stringified field validates instead of
    failing the whole extraction."""
    return _maybe_decode_container(data)


def _normalize_top_level(cls: type[BaseModel], data: Any) -> Any:
    """Normalize provider-shaped equivalents of the pinned extraction contract.

    Besides JSON-encoded containers, Gemini tool calls have been observed to
    emit a criterion wrapper itself as null for an unknown fact and to pad a
    floor_plans array with null. Both have one unambiguous semantic form in
    Manzil: the canonical not_found wrapper and no Floor Plan, respectively.
    Missing criterion keys still fail validation; this only normalizes values
    the model explicitly emitted.
    """
    if isinstance(data, dict):
        normalized = {key: _maybe_decode_container(value) for key, value in data.items()}
        criterion_keys = {entry.key for entry in extractable_entries()}
        for key in criterion_keys & normalized.keys():
            if normalized[key] is None:
                normalized[key] = {
                    "value": None,
                    "confidence": "not_found",
                    "evidence_quote": None,
                }
        if isinstance(normalized.get("floor_plans"), list):
            normalized["floor_plans"] = [
                plan for plan in normalized["floor_plans"] if plan is not None
            ]
        return normalized
    return data


def extractable_entries(catalog: tuple[CatalogEntry, ...] = CATALOG) -> list[CatalogEntry]:
    return [e for e in catalog if e.requires_tool is None and e.key not in COMPOSED_KEYS]


def _value_type(value_schema: dict[str, Any]) -> Any:
    """JSON-schema fragment -> python annotation for the `value` field."""
    enum = value_schema.get("enum")
    if enum:
        return Literal[tuple(enum)]
    match value_schema.get("type"):
        case "integer":
            return int
        case "number":
            return float
        case "boolean":
            return bool
        case "string":
            return str
        case "object":
            return dict[str, Any]
        case "array":
            item_type = _value_type(value_schema.get("items", {}))
            array_type = list[item_type]
            if value_schema.get("uniqueItems"):
                return Annotated[array_type, AfterValidator(_require_unique_items)]
            return array_type
        case unknown:
            raise ValueError(f"unsupported value_schema type: {unknown!r}")


def _require_unique_items(value: list[Any]) -> list[Any]:
    """Enforce JSON Schema `uniqueItems` at runtime, not only in tool JSON."""
    try:
        if len(value) != len(set(value)):
            raise ValueError("array items must be unique")
    except TypeError as error:
        raise ValueError("array items must be hashable") from error
    return value


def _bounds(value_schema: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if "minimum" in value_schema:
        kwargs["ge"] = value_schema["minimum"]
    if "maximum" in value_schema:
        kwargs["le"] = value_schema["maximum"]
    if "minItems" in value_schema:
        kwargs["min_length"] = value_schema["minItems"]
    if "maxItems" in value_schema:
        kwargs["max_length"] = value_schema["maxItems"]
    if value_schema.get("uniqueItems"):
        kwargs["json_schema_extra"] = {"uniqueItems": True}
    return kwargs


def value_adapter(entry: CatalogEntry) -> TypeAdapter[Any]:
    """Validator for a bare criterion value (no confidence/evidence wrapper) —
    used by the bench label loader (P0-11) so hand-labeled ground truth obeys
    the same catalog `value_schema` the extraction schema is generated from."""
    ann = Annotated[_value_type(entry.value_schema), Field(**_bounds(entry.value_schema))]
    return TypeAdapter(ann)


def field_model(entry: CatalogEntry) -> type[BaseModel]:
    """`{value, confidence, evidence_quote}` for one criterion. `value` is None
    when the page doesn't state it — the model must still emit the field."""
    value_ann = _value_type(entry.value_schema)
    description = f"{entry.label}. {entry.extraction_hint}"
    value_field = (
        Annotated[value_ann, Field(**_bounds(entry.value_schema))] | None,
        Field(default=None, description=description),
    )
    return create_model(
        f"Extracted_{entry.key}",
        __doc__=(
            f"{entry.label}: emit as a JSON object with keys value, confidence, "
            "evidence_quote — NEVER as a JSON-encoded string."
        ),
        __config__=ConfigDict(extra="forbid"),
        __validators__={
            "_parse_stringified_field": model_validator(mode="before")(_parse_stringified_field)
        },
        value=value_field,
        confidence=(
            Confidence,
            Field(description="not_found when the page does not state this."),
        ),
        evidence_quote=(
            str | None,
            Field(
                default=None,
                description="Verbatim quote from the page supporting the value. "
                "Required for any non-null value; must appear in the page text.",
            ),
        ),
    )


def build_extraction_schema(
    catalog: tuple[CatalogEntry, ...] = CATALOG,
) -> type[BaseModel]:
    """The forced-tool schema for EXTRACT: one field per extractable criterion,
    plus the page's floor plans and the property's own identity. Every criterion
    field is required — omitting a field is a schema violation, unknown is
    expressed as value null + confidence not_found. The non-catalog blocks
    (floor_plans, property_identity) are optional so recorded fixtures and stored
    RunState snapshots that predate them keep validating."""
    fields: dict[str, Any] = {
        entry.key: (field_model(entry), ...) for entry in extractable_entries(catalog)
    }
    fields["property_identity"] = (
        PropertyIdentityIn | None,
        Field(
            default=None,
            description="The property/complex itself as stated on the page: its name, "
            "full street address, and official website URL when the page names one. "
            "Copy from the page; null for anything not stated — never invent.",
        ),
    )
    fields["floor_plans"] = (
        list[FloorPlanIn],
        Field(
            default_factory=list,
            description="Every distinct floor plan / unit type advertised on the page, "
            "with its controlled unit_types, rent range, sqft range, deposit, and "
            "earliest availability "
            "as an ISO date (YYYY-MM-DD). Search prose and [EMBEDDED DATA] for "
            "that plan: if it has an explicit availability date, emit the "
            "earliest explicit ISO date even when the UI also says 'Available "
            "Now', 'Now', or 'Immediately'. Emit the literal sentinel "
            "available_now only when that plan has immediate wording and no "
            "explicit availability date (the pipeline rewrites it to the run "
            "date / corpus saved_at). Ignore similar/nearby Properties and "
            "unrelated dates. Empty if the page lists a single unit without "
            "named plans — then put its figures in a single unnamed plan.",
        ),
    )
    fields["pet_costs"] = (
        PetCostsIn | None,
        Field(
            default=None,
            description="Monthly per-pet rent as stated on the page. Numbers only, no "
            "currency symbols. Fill cat_rent_monthly / dog_rent_monthly ONLY when the "
            "page distinguishes cat rent from dog rent; fill pet_rent_monthly ONLY when "
            "the page states a single per-pet figure without distinguishing species. "
            "Null any field the page does not state — never invent. Null the whole block "
            "if the page says nothing about pet rent.",
        ),
    )
    fields["utilities"] = (
        UtilitiesIn | None,
        Field(
            default=None,
            description="Utilities the listing states are INCLUDED in rent. Set `included` "
            "to the list of included utilities; an empty list if the page states none are "
            "included; null the block if the page says nothing about utilities. Never invent.",
        ),
    )
    fields["mandatory_fees"] = (
        MandatoryFeesIn | None,
        Field(
            default=None,
            description="Mandatory RECURRING MONTHLY fees every resident must pay, as "
            "stated on the page: water/sewer or utility billing fees, valet trash, "
            "mandatory parking, required insurance or liability programs. Numbers only, "
            "monthly amounts. EXCLUDE one-time fees (admin, application, deposits), "
            "optional add-ons, and pet rent (its own block). Null the whole block if the "
            "page states no such fees. Never invent.",
        ),
    )
    fields["one_time_fees"] = (
        OneTimeFeesIn | None,
        Field(
            default=None,
            description="ONE-TIME move-in fees as stated on the page: application fees, "
            "admin/administrative fees, one-time pet deposits or pet fees, and other "
            "single-payment move-in charges. Numbers only. For each fee set `basis`: "
            "'per_person' when charged per applicant/occupant, 'per_application' when one "
            "charge covers the whole application, 'per_pet' when charged per animal, else "
            "'flat'. Set `refundable` only when the page says refundable or non-refundable. "
            "EXCLUDE security deposits (floor-plan field), recurring monthly fees (their "
            "own block), and optional add-ons. Null the whole block if the page states no "
            "such fees. Never invent.",
        ),
    )
    fields["heating"] = (
        HeatingIn | None,
        Field(
            default=None,
            description="The unit's heating fuel when the page states it: 'gas' (gas "
            "heat/furnace) or 'electric' (electric heat/baseboard/heat pump). Null the "
            "block when the page does not state the heating type. Never guess from "
            "region or building age.",
        ),
    )
    return create_model(
        "ListingExtraction",
        __config__=ConfigDict(extra="forbid"),
        __validators__={
            "_normalize_top_level": model_validator(mode="before")(_normalize_top_level)
        },
        **fields,
    )
