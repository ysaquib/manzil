"""Criteria catalog seed — the 19 v1 criteria from DESIGN.md §8.2, verbatim keys.

This module is the single source of truth for `criteria_catalog` rows:
`supabase/seed.sql` is generated FROM here (runbook, IMPLEMENTATION.md §8)
and never edited by hand. Regenerate with:

    uv run --package manzil-shared python -m manzil_shared.catalog

The `beds` entry (schema, options, hint) is pinned in DESIGN §8.2; the design
specifies value types, categories, tools, and refresh classes for the rest,
while their default option deltas and extraction hints are seed data authored
here — hunt owners edit options in the rubric anyway (§9.2).

All v1 entries are tagged domain=rent: this is the rent catalog slice; the
buy slice is specified in §18 and deliberately not seeded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from manzil_shared.models import (
    CatalogEntry,
    CriterionCategory,
    CriterionDomain,
    MatchOp,
    OptionMatch,
    RefreshClass,
    RequiresTool,
    RubricOption,
)


def _opt(op: MatchOp, value: Any, delta: float) -> RubricOption:
    return RubricOption(match=OptionMatch(op=op, value=value), delta=delta)


CATALOG: tuple[CatalogEntry, ...] = (
    # Pinned complete entry, DESIGN §8.2 — do not reshape.
    CatalogEntry(
        key="beds",
        label="Number of bedrooms",
        category=CriterionCategory.UNIT,
        domain=CriterionDomain.RENT,
        value_schema={"type": "integer", "minimum": 0, "maximum": 5},
        default_options=[
            _opt(MatchOp.EQ, 2, 0.5),
            _opt(MatchOp.EQ, 1, 0.0),
            _opt(MatchOp.EQ, 0, -0.5),
        ],
        extraction_hint="Count distinct bedrooms; a studio is 0.",
        requires_tool=None,
        refresh_class=RefreshClass.LISTING_DETAILS,
    ),
    CatalogEntry(
        key="baths",
        label="Number of bathrooms",
        category=CriterionCategory.UNIT,
        domain=CriterionDomain.RENT,
        value_schema={"type": "number", "minimum": 1, "maximum": 4, "multipleOf": 0.5},
        default_options=[
            _opt(MatchOp.GT, 1.5, 0.5),
            _opt(MatchOp.EQ, 1.5, 0.25),
            _opt(MatchOp.EQ, 1, 0.0),
        ],
        extraction_hint="Count bathrooms; a half bath (no shower/tub) counts 0.5.",
        requires_tool=None,
        refresh_class=RefreshClass.LISTING_DETAILS,
    ),
    CatalogEntry(
        key="sqft",
        label="Square footage",
        category=CriterionCategory.UNIT,
        domain=CriterionDomain.RENT,
        value_schema={"type": "integer", "minimum": 0},
        default_options=[
            _opt(MatchOp.GT, 900, 0.5),
            _opt(MatchOp.RANGE, [700, 900], 0.0),
            _opt(MatchOp.LT, 700, -0.5),
        ],
        extraction_hint="Interior area of the unit in square feet.",
        requires_tool=None,
        refresh_class=RefreshClass.LISTING_DETAILS,
    ),
    CatalogEntry(
        key="patio_balcony",
        label="Patio or balcony",
        category=CriterionCategory.UNIT,
        domain=CriterionDomain.RENT,
        value_schema={"type": "boolean"},
        default_options=[
            _opt(MatchOp.BOOL, True, 0.5),
            _opt(MatchOp.BOOL, False, 0.0),
        ],
        extraction_hint="True if the unit has a private patio or balcony.",
        requires_tool=None,
        refresh_class=RefreshClass.LISTING_DETAILS,
    ),
    CatalogEntry(
        key="private_entry",
        label="Private entrance",
        category=CriterionCategory.UNIT,
        domain=CriterionDomain.RENT,
        value_schema={"type": "boolean"},
        default_options=[
            _opt(MatchOp.BOOL, True, 0.25),
            _opt(MatchOp.BOOL, False, 0.0),
        ],
        extraction_hint=(
            "True if the unit has its own exterior entrance rather than a shared interior corridor."
        ),
        requires_tool=None,
        refresh_class=RefreshClass.LISTING_DETAILS,
    ),
    CatalogEntry(
        key="in_unit_laundry",
        label="Laundry",
        category=CriterionCategory.UNIT,
        domain=CriterionDomain.RENT,
        value_schema={"type": "string", "enum": ["in_unit", "hookups", "on_site", "none"]},
        default_options=[
            _opt(MatchOp.EQ, "in_unit", 1.0),
            _opt(MatchOp.EQ, "hookups", 0.25),
            _opt(MatchOp.EQ, "on_site", -0.5),
            _opt(MatchOp.EQ, "none", -1.0),
        ],
        extraction_hint=(
            "in_unit = washer/dryer inside the unit; hookups = connections only; "
            "on_site = shared laundry room/facilities; none otherwise."
        ),
        requires_tool=None,
        refresh_class=RefreshClass.LISTING_DETAILS,
    ),
    CatalogEntry(
        key="pets_policy",
        label="Pets policy",
        category=CriterionCategory.POLICY,
        domain=CriterionDomain.RENT,
        value_schema={
            "type": "string",
            "enum": ["cats_and_dogs", "cats_only", "dogs_only", "none"],
        },
        default_options=[
            _opt(MatchOp.EQ, "cats_and_dogs", 0.5),
            _opt(MatchOp.EQ, "cats_only", 0.25),
            _opt(MatchOp.EQ, "dogs_only", 0.0),
            _opt(MatchOp.EQ, "none", -0.5),
        ],
        extraction_hint="Which pets the policy allows, ignoring breed and weight limits.",
        requires_tool=None,
        refresh_class=RefreshClass.LISTING_DETAILS,
    ),
    CatalogEntry(
        key="all_in_monthly",
        label="All-in monthly cost",
        category=CriterionCategory.COST,
        domain=CriterionDomain.RENT,
        value_schema={"type": "number", "minimum": 0},
        default_options=[
            _opt(MatchOp.LT, 1800, 1.0),
            _opt(MatchOp.RANGE, [1800, 2000], 0.5),
            _opt(MatchOp.RANGE, [2000, 2200], 0.0),
            _opt(MatchOp.GT, 2200, -1.0),
        ],
        extraction_hint=(
            "Composed by the pipeline from rent, mandatory fees, pet costs, and "
            "utility estimates (DESIGN §9.5) — never extracted directly from the page."
        ),
        requires_tool=None,
        refresh_class=RefreshClass.PRICING,
    ),
    CatalogEntry(
        key="security_deposit",
        label="Security deposit",
        category=CriterionCategory.COST,
        domain=CriterionDomain.RENT,
        value_schema={"type": "number", "minimum": 0},
        default_options=[
            _opt(MatchOp.LT, 500, 0.25),
            _opt(MatchOp.RANGE, [500, 1000], 0.0),
            _opt(MatchOp.GT, 1000, -0.25),
        ],
        extraction_hint=(
            "Refundable security deposit in dollars; use the standard amount, not a "
            "promotional one."
        ),
        requires_tool=None,
        refresh_class=RefreshClass.PRICING,
    ),
    CatalogEntry(
        key="availability_date",
        label="Availability date",
        category=CriterionCategory.AVAILABILITY,
        domain=CriterionDomain.RENT,
        value_schema={"type": "string", "format": "date"},
        default_options=[],  # date thresholds are hunt-specific; owners set options in the rubric
        extraction_hint="Earliest stated move-in date for the unit, as an ISO date.",
        requires_tool=None,
        refresh_class=RefreshClass.PRICING,
    ),
    CatalogEntry(
        key="kitchen_quality",
        label="Kitchen quality",
        category=CriterionCategory.CONDITION,
        domain=CriterionDomain.RENT,
        value_schema={"type": "integer", "minimum": 1, "maximum": 5},
        default_options=[
            _opt(MatchOp.GT, 3, 0.5),
            _opt(MatchOp.EQ, 3, 0.0),
            _opt(MatchOp.LT, 3, -0.5),
        ],
        extraction_hint=(
            "1-5 rating assessed by VISION from listing photos against the anchored "
            "reference set (DESIGN §10.8), not from text."
        ),
        requires_tool=RequiresTool.VISION,
        refresh_class=RefreshClass.IMAGES,
    ),
    CatalogEntry(
        key="flooring_quality",
        label="Flooring quality",
        category=CriterionCategory.CONDITION,
        domain=CriterionDomain.RENT,
        value_schema={"type": "integer", "minimum": 1, "maximum": 5},
        default_options=[
            _opt(MatchOp.GT, 3, 0.5),
            _opt(MatchOp.EQ, 3, 0.0),
            _opt(MatchOp.LT, 3, -0.5),
        ],
        extraction_hint=(
            "1-5 rating of floor/carpet condition assessed by VISION from listing "
            "photos against the anchored reference set, not from text."
        ),
        requires_tool=RequiresTool.VISION,
        refresh_class=RefreshClass.IMAGES,
    ),
    CatalogEntry(
        key="parking",
        label="Parking",
        category=CriterionCategory.UNIT,
        domain=CriterionDomain.RENT,
        value_schema={
            "type": "string",
            "enum": ["garage", "carport", "dedicated_lot", "street_only", "none"],
        },
        default_options=[
            _opt(MatchOp.EQ, "garage", 0.5),
            _opt(MatchOp.EQ, "carport", 0.25),
            _opt(MatchOp.EQ, "dedicated_lot", 0.0),
            _opt(MatchOp.EQ, "street_only", -0.5),
            _opt(MatchOp.EQ, "none", -1.0),
        ],
        extraction_hint=(
            "Best parking included or available with the unit: garage, carport, "
            "dedicated_lot (assigned or off-street lot), street_only, or none."
        ),
        requires_tool=None,
        refresh_class=RefreshClass.LISTING_DETAILS,
    ),
    CatalogEntry(
        key="cooling",
        label="Cooling",
        category=CriterionCategory.UNIT,
        domain=CriterionDomain.RENT,
        value_schema={"type": "string", "enum": ["central", "window_units", "none"]},
        default_options=[
            _opt(MatchOp.EQ, "central", 0.5),
            _opt(MatchOp.EQ, "window_units", 0.0),
            _opt(MatchOp.EQ, "none", -1.0),
        ],
        extraction_hint=(
            "central = central air conditioning; window_units = window/wall units "
            "provided or explicitly permitted; none otherwise."
        ),
        requires_tool=None,
        refresh_class=RefreshClass.LISTING_DETAILS,
    ),
    CatalogEntry(
        key="dishwasher",
        label="Dishwasher",
        category=CriterionCategory.UNIT,
        domain=CriterionDomain.RENT,
        value_schema={"type": "boolean"},
        default_options=[
            _opt(MatchOp.BOOL, True, 0.25),
            _opt(MatchOp.BOOL, False, 0.0),
        ],
        extraction_hint="True if the unit includes a dishwasher.",
        requires_tool=None,
        refresh_class=RefreshClass.LISTING_DETAILS,
    ),
    CatalogEntry(
        key="min_lease_months",
        label="Minimum lease term",
        category=CriterionCategory.POLICY,
        domain=CriterionDomain.RENT,
        value_schema={"type": "integer", "minimum": 1},
        default_options=[
            _opt(MatchOp.LT, 12, 0.25),
            _opt(MatchOp.EQ, 12, 0.0),
            _opt(MatchOp.GT, 12, -0.5),
        ],
        extraction_hint=("Shortest lease term offered, in months; month-to-month is 1."),
        requires_tool=None,
        refresh_class=RefreshClass.PRICING,
    ),
    CatalogEntry(
        key="grocery_proximity",
        label="Grocery proximity",
        category=CriterionCategory.LOCATION,
        domain=CriterionDomain.RENT,
        value_schema={"type": "number", "minimum": 0},
        default_options=[
            _opt(MatchOp.LT, 10, 0.5),
            _opt(MatchOp.RANGE, [10, 20], 0.0),
            _opt(MatchOp.GT, 20, -0.5),
        ],
        extraction_hint=(
            "Minutes to the nearest full grocery store, walking or driving per the "
            "hunt setting; computed via Maps, not extracted from the page."
        ),
        requires_tool=RequiresTool.MAPS,
        refresh_class=RefreshClass.LOCATION,
    ),
    CatalogEntry(
        key="management_reviews",
        label="Management reviews",
        category=CriterionCategory.REPUTATION,
        domain=CriterionDomain.RENT,
        value_schema={
            "type": "object",
            "properties": {
                "rating": {"type": "number", "minimum": 1, "maximum": 5},
                "summary": {"type": "string"},
            },
            "required": ["rating"],
        },
        # Numeric ops evaluate against the object's "rating" field (engine semantics
        # settled in P0-3).
        default_options=[
            _opt(MatchOp.GT, 4, 0.5),
            _opt(MatchOp.RANGE, [3, 4], 0.0),
            _opt(MatchOp.LT, 3, -0.5),
        ],
        extraction_hint=(
            "Aggregate review rating (1-5) plus a short reputation summary, sourced "
            "from Places reviews."
        ),
        requires_tool=RequiresTool.MAPS,
        refresh_class=RefreshClass.REVIEWS,
    ),
    CatalogEntry(
        key="location_safety",
        label="Location safety",
        category=CriterionCategory.LOCATION,
        domain=CriterionDomain.RENT,
        value_schema={"type": "string", "enum": ["low", "medium", "high"]},
        default_options=[
            _opt(MatchOp.EQ, "high", 0.5),
            _opt(MatchOp.EQ, "medium", 0.0),
            _opt(MatchOp.EQ, "low", -1.0),
        ],
        extraction_hint=(
            "Qualitative safety level synthesized from web sources; inherently "
            "low-confidence by design (DESIGN R8) — frame as such, never as fact."
        ),
        requires_tool=RequiresTool.WEB_SEARCH,
        refresh_class=RefreshClass.REVIEWS,
    ),
)


# --- seed.sql generation ---

_COLUMNS = (
    "key",
    "label",
    "category",
    "domain",
    "value_schema",
    "default_options",
    "extraction_hint",
    "requires_tool",
    "refresh_class",
)
_JSONB_COLUMNS = frozenset({"value_schema", "default_options"})


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_value(column: str, entry: CatalogEntry) -> str:
    raw = getattr(entry, column)
    if raw is None:
        return "null"
    if column in _JSONB_COLUMNS:
        # exclude_none keeps default_options in the pinned §8.2 catalog shape
        # ({match, delta} only) instead of carrying dealbreaker_set_score nulls.
        if column == "default_options":
            raw = [o.model_dump(mode="json", exclude_none=True) for o in entry.default_options]
        return _sql_str(json.dumps(raw)) + "::jsonb"
    return _sql_str(str(raw))


def generate_seed_sql(catalog: tuple[CatalogEntry, ...] = CATALOG) -> str:
    rows = ",\n".join(
        "  (" + ", ".join(_sql_value(col, entry) for col in _COLUMNS) + ")" for entry in catalog
    )
    updates = ",\n".join(f"  {col} = excluded.{col}" for col in _COLUMNS[1:])
    return (
        "-- Generated from shared/src/manzil_shared/catalog.py — never edit by hand.\n"
        "-- Regenerate: uv run --package manzil-shared python -m manzil_shared.catalog\n"
        "\n"
        f"insert into criteria_catalog\n  ({', '.join(_COLUMNS)})\nvalues\n"
        f"{rows}\n"
        f"on conflict (key) do update set\n{updates};\n"
    )


def write_seed_sql() -> Path:
    """Regenerate supabase/seed.sql in the repo root (runbook, IMPLEMENTATION.md §8)."""
    repo_root = Path(__file__).resolve().parents[3]
    out = repo_root / "supabase" / "seed.sql"
    out.write_text(generate_seed_sql())
    return out


if __name__ == "__main__":
    print(f"wrote {write_seed_sql()}")
