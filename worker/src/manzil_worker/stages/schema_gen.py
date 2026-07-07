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

from typing import Annotated, Any, Literal

from manzil_shared.catalog import CATALOG
from manzil_shared.models import CatalogEntry, Confidence
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, create_model

from manzil_worker.state import FloorPlanIn

# Composed by the pipeline, never extracted from the page (§9.5).
COMPOSED_KEYS = frozenset({"all_in_monthly"})


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
        case unknown:
            raise ValueError(f"unsupported value_schema type: {unknown!r}")


def _bounds(value_schema: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if "minimum" in value_schema:
        kwargs["ge"] = value_schema["minimum"]
    if "maximum" in value_schema:
        kwargs["le"] = value_schema["maximum"]
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
        __config__=ConfigDict(extra="forbid"),
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
    plus the page's floor plans. Every criterion field is required — omitting
    a field is a schema violation, unknown is expressed as value null +
    confidence not_found."""
    fields: dict[str, Any] = {
        entry.key: (field_model(entry), ...) for entry in extractable_entries(catalog)
    }
    fields["floor_plans"] = (
        list[FloorPlanIn],
        Field(
            default_factory=list,
            description="Every distinct floor plan / unit type advertised on the page, "
            "with its rent range, sqft range, deposit, and earliest availability "
            "(ISO date). Empty if the page lists a single unit without named plans — "
            "then put its figures in a single unnamed plan.",
        ),
    )
    return create_model(
        "ListingExtraction",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )
