"""Criteria catalog seed — the active rent criteria from DESIGN.md §8.2.

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
    ConflictPolicy,
    CriterionCategory,
    CriterionDomain,
    EscalationPolicy,
    FactScope,
    MatchOp,
    OptionMatch,
    RefreshClass,
    RequiresTool,
    RubricOption,
)


def _opt(op: MatchOp, value: Any, delta: float) -> RubricOption:
    return RubricOption(match=OptionMatch(op=op, value=value), delta=delta)


PROPERTY_TYPE_VALUES = (
    "apartment",
    "condo",
    "townhome",
    "duplex",
    "single_family",
    "loft",
    "other",
)


def _controlled_set_schema(values: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string", "enum": list(values)},
        "minItems": 1,
        "uniqueItems": True,
    }


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
        extraction_hint=(
            "Which pets the policy allows, ignoring breed and weight limits."
            "If a fee is mentioned for a pet, then we can consider it a pet policy criterion."
        ),
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
        extraction_hint=(
            "Earliest stated move-in date for the unit, as an ISO date "
            "(YYYY-MM-DD). Search prose and [EMBEDDED DATA]. If the target "
            "Property/Floor Plan has an explicit availability date, emit the "
            "earliest explicit ISO date even when the UI also says 'Available "
            "Now', 'Now', or 'Immediately'. Emit the literal sentinel "
            "available_now only when that target has immediate wording and no "
            "explicit availability date — never invent a calendar date. Ignore "
            "similar/nearby Properties, page update timestamps, promotions, "
            "and unrelated dates. Property-level availability is the earliest "
            "relevant date across the target Property's plans. The pipeline "
            "rewrites available_now to the run date (live) or corpus "
            "saved_at date (bench)."
        ),
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
            "enum": ["garage", "carport", "covered", "dedicated_lot", "street_only", "none"],
        },
        default_options=[
            _opt(MatchOp.EQ, "garage", 0.5),
            _opt(MatchOp.EQ, "carport", 0.25),
            _opt(MatchOp.EQ, "covered", 0.25),
            _opt(MatchOp.EQ, "dedicated_lot", 0.0),
            _opt(MatchOp.EQ, "street_only", -0.5),
            _opt(MatchOp.EQ, "none", -1.0),
        ],
        extraction_hint=(
            "Best parking included or available with the unit: garage, carport, covered, "
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
        # Letter grades matching public crime-grade conventions (§20 2026-07-18):
        # human overrides today and the P3-17 module output tomorrow share one
        # vocabulary. Banded default deltas — the 13 grades collapse to 5 tiers.
        value_schema={
            "type": "string",
            "enum": [
                "A+",
                "A",
                "A-",
                "B+",
                "B",
                "B-",
                "C+",
                "C",
                "C-",
                "D+",
                "D",
                "D-",
                "F",
            ],
        },
        default_options=[
            *(_opt(MatchOp.EQ, grade, 0.5) for grade in ("A+", "A", "A-")),
            *(_opt(MatchOp.EQ, grade, 0.25) for grade in ("B+", "B", "B-")),
            *(_opt(MatchOp.EQ, grade, 0.0) for grade in ("C+", "C", "C-")),
            *(_opt(MatchOp.EQ, grade, -0.5) for grade in ("D+", "D", "D-")),
            _opt(MatchOp.EQ, "F", -1.0),
        ],
        extraction_hint=(
            "Letter-grade location safety (A+ through F). Placeholder in v1: no "
            "pipeline stage emits it — the value arrives via human override until "
            "the dedicated safety module (DESIGN §18, P3-17) lands. Inherently "
            "low-confidence by design (DESIGN R8) — frame as such, never as fact."
        ),
        requires_tool=RequiresTool.WEB_SEARCH,
        refresh_class=RefreshClass.REVIEWS,
    ),
    # P3-SC3: first Property tranche. Preference conveniences use the
    # available-sources-only / verified-positive defaults; a Hunt Gate upgrades
    # acquisition to decision-relevant at reconciliation time (DESIGN §9.2).
    CatalogEntry(
        key="pool",
        label="Pool",
        category=CriterionCategory.PROPERTY,
        domain=CriterionDomain.RENT,
        fact_scope=FactScope.PROPERTY,
        value_schema={
            "type": "string",
            "enum": ["indoor", "outdoor", "indoor_and_outdoor", "unspecified", "none"],
        },
        default_options=[
            _opt(MatchOp.EQ, "indoor_and_outdoor", 0.5),
            _opt(MatchOp.IN, ["indoor", "outdoor"], 0.25),
            _opt(MatchOp.EQ, "unspecified", 0.25),
            _opt(MatchOp.EQ, "none", 0.0),
        ],
        extraction_hint=(
            "Shared Property pool facilities only: indoor, outdoor, both, unspecified type, "
            "or explicitly none. Do not infer private-unit pools."
        ),
        refresh_class=RefreshClass.LISTING_DETAILS,
        escalation_policy=EscalationPolicy.AVAILABLE_SOURCES_ONLY,
        conflict_policy=ConflictPolicy.VERIFIED_POSITIVE_PREFERRED,
    ),
    CatalogEntry(
        key="fitness_center",
        label="Fitness center or gym",
        category=CriterionCategory.PROPERTY,
        domain=CriterionDomain.RENT,
        fact_scope=FactScope.PROPERTY,
        value_schema={"type": "boolean"},
        default_options=[
            _opt(MatchOp.BOOL, True, 0.5),
            _opt(MatchOp.BOOL, False, 0.0),
        ],
        extraction_hint="True only for an on-site resident fitness center or gym.",
        refresh_class=RefreshClass.LISTING_DETAILS,
        escalation_policy=EscalationPolicy.AVAILABLE_SOURCES_ONLY,
        conflict_policy=ConflictPolicy.VERIFIED_POSITIVE_PREFERRED,
    ),
    CatalogEntry(
        key="clubhouse",
        label="Clubhouse",
        category=CriterionCategory.PROPERTY,
        domain=CriterionDomain.RENT,
        fact_scope=FactScope.PROPERTY,
        value_schema={"type": "boolean"},
        default_options=[
            _opt(MatchOp.BOOL, True, 0.25),
            _opt(MatchOp.BOOL, False, 0.0),
        ],
        extraction_hint="True only when the Property advertises a resident clubhouse.",
        refresh_class=RefreshClass.LISTING_DETAILS,
        escalation_policy=EscalationPolicy.AVAILABLE_SOURCES_ONLY,
        conflict_policy=ConflictPolicy.VERIFIED_POSITIVE_PREFERRED,
    ),
    CatalogEntry(
        key="emergency_maintenance",
        label="Emergency maintenance",
        category=CriterionCategory.PROPERTY,
        domain=CriterionDomain.RENT,
        fact_scope=FactScope.PROPERTY,
        value_schema={
            "type": "string",
            "enum": ["emergency_service", "24_hour_emergency", "none"],
        },
        default_options=[
            _opt(MatchOp.EQ, "24_hour_emergency", 0.5),
            _opt(MatchOp.EQ, "emergency_service", 0.25),
            _opt(MatchOp.EQ, "none", 0.0),
        ],
        extraction_hint=(
            "24_hour_emergency only when 24-hour emergency maintenance is explicit; "
            "emergency_service for emergency maintenance without a 24-hour promise; none only "
            "when explicitly unavailable."
        ),
        refresh_class=RefreshClass.LISTING_DETAILS,
        escalation_policy=EscalationPolicy.AVAILABLE_SOURCES_ONLY,
        conflict_policy=ConflictPolicy.VERIFIED_POSITIVE_PREFERRED,
    ),
    CatalogEntry(
        key="maintenance_on_site",
        label="Maintenance on site",
        category=CriterionCategory.PROPERTY,
        domain=CriterionDomain.RENT,
        fact_scope=FactScope.PROPERTY,
        value_schema={"type": "boolean"},
        default_options=[
            _opt(MatchOp.BOOL, True, 0.25),
            _opt(MatchOp.BOOL, False, 0.0),
        ],
        extraction_hint="True only when on-site maintenance staff or service is advertised.",
        refresh_class=RefreshClass.LISTING_DETAILS,
        escalation_policy=EscalationPolicy.AVAILABLE_SOURCES_ONLY,
        conflict_policy=ConflictPolicy.VERIFIED_POSITIVE_PREFERRED,
    ),
    CatalogEntry(
        key="management_on_site",
        label="Management on site",
        category=CriterionCategory.PROPERTY,
        domain=CriterionDomain.RENT,
        fact_scope=FactScope.PROPERTY,
        value_schema={"type": "boolean"},
        default_options=[
            _opt(MatchOp.BOOL, True, 0.25),
            _opt(MatchOp.BOOL, False, 0.0),
        ],
        extraction_hint="True only when on-site Property management is advertised.",
        refresh_class=RefreshClass.LISTING_DETAILS,
        escalation_policy=EscalationPolicy.AVAILABLE_SOURCES_ONLY,
        conflict_policy=ConflictPolicy.VERIFIED_POSITIVE_PREFERRED,
    ),
    CatalogEntry(
        key="online_payments",
        label="Online payments",
        category=CriterionCategory.PROPERTY,
        domain=CriterionDomain.RENT,
        fact_scope=FactScope.PROPERTY,
        value_schema={"type": "boolean"},
        default_options=[
            _opt(MatchOp.BOOL, True, 0.25),
            _opt(MatchOp.BOOL, False, 0.0),
        ],
        extraction_hint=(
            "True only when online rent payments are explicit. A generic resident portal alone "
            "is display evidence and does not prove this capability."
        ),
        refresh_class=RefreshClass.LISTING_DETAILS,
        escalation_policy=EscalationPolicy.AVAILABLE_SOURCES_ONLY,
        conflict_policy=ConflictPolicy.VERIFIED_POSITIVE_PREFERRED,
    ),
    CatalogEntry(
        key="online_maintenance_requests",
        label="Online maintenance requests",
        category=CriterionCategory.PROPERTY,
        domain=CriterionDomain.RENT,
        fact_scope=FactScope.PROPERTY,
        value_schema={"type": "boolean"},
        default_options=[
            _opt(MatchOp.BOOL, True, 0.25),
            _opt(MatchOp.BOOL, False, 0.0),
        ],
        extraction_hint=(
            "True only when residents can submit maintenance requests online. A generic resident "
            "portal alone is display evidence and does not prove this capability."
        ),
        refresh_class=RefreshClass.LISTING_DETAILS,
        escalation_policy=EscalationPolicy.AVAILABLE_SOURCES_ONLY,
        conflict_policy=ConflictPolicy.VERIFIED_POSITIVE_PREFERRED,
    ),
    CatalogEntry(
        key="package_handling",
        label="Package handling",
        category=CriterionCategory.PROPERTY,
        domain=CriterionDomain.RENT,
        fact_scope=FactScope.PROPERTY,
        value_schema={
            "type": "string",
            "enum": ["locker", "secured_room", "office", "unsecured_area", "none"],
        },
        default_options=[
            _opt(MatchOp.EQ, "locker", 0.5),
            _opt(MatchOp.EQ, "secured_room", 0.25),
            _opt(MatchOp.EQ, "office", 0.1),
            _opt(MatchOp.EQ, "unsecured_area", 0.0),
            _opt(MatchOp.EQ, "none", 0.0),
        ],
        extraction_hint=(
            "How resident packages are handled: dedicated locker, secured room, office receipt, "
            "unsecured area, or explicitly none."
        ),
        refresh_class=RefreshClass.LISTING_DETAILS,
        escalation_policy=EscalationPolicy.AVAILABLE_SOURCES_ONLY,
        conflict_policy=ConflictPolicy.VERIFIED_POSITIVE_PREFERRED,
    ),
    CatalogEntry(
        key="smoking_policy",
        label="Smoking policy",
        category=CriterionCategory.PROPERTY,
        domain=CriterionDomain.RENT,
        fact_scope=FactScope.PROPERTY,
        value_schema={
            "type": "string",
            "enum": ["smoke_free_property", "designated_areas_only", "permitted"],
        },
        default_options=[
            _opt(MatchOp.EQ, "smoke_free_property", 0.5),
            _opt(MatchOp.EQ, "designated_areas_only", 0.0),
            _opt(MatchOp.EQ, "permitted", -0.5),
        ],
        extraction_hint=(
            "Property-wide smoking policy: fully smoke-free, permitted only in designated areas, "
            "or generally permitted. Silence is unknown."
        ),
        refresh_class=RefreshClass.LISTING_DETAILS,
        escalation_policy=EscalationPolicy.DECISION_RELEVANT,
        conflict_policy=ConflictPolicy.STANDARD_LADDER,
    ),
    CatalogEntry(
        key="property_types",
        label="Property types",
        category=CriterionCategory.PROPERTY,
        domain=CriterionDomain.RENT,
        fact_scope=FactScope.PROPERTY,
        value_schema=_controlled_set_schema(PROPERTY_TYPE_VALUES),
        default_options=[
            _opt(MatchOp.CONTAINS_ANY, list(PROPERTY_TYPE_VALUES), 0.0),
        ],
        extraction_hint=(
            "Every explicitly advertised Property type from the controlled vocabulary. Preserve "
            "multiple types; do not infer from architecture or a Floor Plan name."
        ),
        refresh_class=RefreshClass.LISTING_DETAILS,
    ),
    CatalogEntry(
        key="unit_types",
        label="Unit types",
        category=CriterionCategory.UNIT,
        domain=CriterionDomain.RENT,
        fact_scope=FactScope.FLOOR_PLAN,
        value_schema=_controlled_set_schema(PROPERTY_TYPE_VALUES),
        default_options=[
            _opt(MatchOp.CONTAINS_ANY, list(PROPERTY_TYPE_VALUES), 0.0),
        ],
        extraction_hint=(
            "Every explicitly advertised type for the Floor Plan. Usually one value; preserve "
            "multiple types for a genuinely hybrid offering and do not infer from architecture."
        ),
        refresh_class=RefreshClass.LISTING_DETAILS,
    ),
    CatalogEntry(
        key="internet_readiness",
        label="Internet readiness advertised",
        category=CriterionCategory.PROPERTY,
        domain=CriterionDomain.RENT,
        fact_scope=FactScope.PROPERTY,
        value_schema={"type": "boolean"},
        default_options=[
            _opt(MatchOp.BOOL, True, 0.25),
            _opt(MatchOp.BOOL, False, 0.0),
        ],
        extraction_hint=(
            "True only when the Source advertises general internet, high-speed internet, or fiber "
            "readiness for the Property. This does not verify provider serviceability, speed, "
            "Floor Plan coverage, or inclusion in rent; silence is unknown."
        ),
        refresh_class=RefreshClass.LISTING_DETAILS,
        escalation_policy=EscalationPolicy.AVAILABLE_SOURCES_ONLY,
        conflict_policy=ConflictPolicy.VERIFIED_POSITIVE_PREFERRED,
    ),
)

# P3-SC2 establishes scope as Catalog truth before P3-SC3/P3-SC4 expand the
# catalog and extraction prompt. These assignments do not yet teach EXTRACT
# exact Floor Plan association; page-level unit claims are persisted as
# unit_scope_unspecified until P3-SC4.
_FLOOR_PLAN_KEYS = frozenset(
    {
        "beds",
        "baths",
        "sqft",
        "patio_balcony",
        "private_entry",
        "security_deposit",
        "availability_date",
        "kitchen_quality",
        "flooring_quality",
        "cooling",
        "dishwasher",
        "unit_types",
    }
)
_MIXED_KEYS = frozenset({"in_unit_laundry", "parking", "min_lease_months"})
for _entry in CATALOG:
    if _entry.key == "all_in_monthly":
        _entry.fact_scope = FactScope.COMPOSED
    elif _entry.key in _FLOOR_PLAN_KEYS:
        _entry.fact_scope = FactScope.FLOOR_PLAN
    elif _entry.key in _MIXED_KEYS:
        _entry.fact_scope = FactScope.MIXED
    else:
        _entry.fact_scope = FactScope.PROPERTY


# --- seed.sql generation ---

_COLUMNS = (
    "key",
    "label",
    "category",
    "domain",
    "fact_scope",
    "value_schema",
    "claim_value_schema",
    "default_options",
    "extraction_hint",
    "requires_tool",
    "refresh_class",
    "escalation_policy",
    "conflict_policy",
)
_JSONB_COLUMNS = frozenset({"value_schema", "claim_value_schema", "default_options"})


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


def generate_catalog_upsert_sql(catalog: tuple[CatalogEntry, ...]) -> str:
    rows = ",\n".join(
        "  (" + ", ".join(_sql_value(col, entry) for col in _COLUMNS) + ")" for entry in catalog
    )
    updates = ",\n".join(f"  {col} = excluded.{col}" for col in _COLUMNS[1:])
    return (
        f"insert into criteria_catalog\n  ({', '.join(_COLUMNS)})\nvalues\n"
        f"{rows}\n"
        f"on conflict (key) do update set\n{updates};\n"
    )


def generate_seed_sql(catalog: tuple[CatalogEntry, ...] = CATALOG) -> str:
    return (
        "-- Generated from shared/src/manzil_shared/catalog.py — never edit by hand.\n"
        "-- Regenerate: uv run --package manzil-shared python -m manzil_shared.catalog\n"
        "\n" + generate_catalog_upsert_sql(catalog)
    )


def generate_catalog_sync_sql(*keys: str) -> str:
    """Hosted-database upsert for a named Catalog tranche (IMPLEMENTATION §8)."""
    selected = tuple(entry for entry in CATALOG if entry.key in keys)
    missing = set(keys) - {entry.key for entry in selected}
    if missing:
        raise KeyError(f"unknown catalog keys: {sorted(missing)}")
    return (
        "-- Generated Catalog sync from shared/src/manzil_shared/catalog.py.\n"
        "-- P3-SC3 first Property/Unit type tranche; idempotent on hosted and local databases.\n\n"
        + generate_catalog_upsert_sql(selected)
    )


def write_seed_sql() -> Path:
    """Regenerate supabase/seed.sql in the repo root (runbook, IMPLEMENTATION.md §8)."""
    repo_root = Path(__file__).resolve().parents[3]
    out = repo_root / "supabase" / "seed.sql"
    out.write_text(generate_seed_sql())
    return out


if __name__ == "__main__":
    print(f"wrote {write_seed_sql()}")
