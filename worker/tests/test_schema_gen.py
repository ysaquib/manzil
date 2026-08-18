"""P0-8: dynamic extraction schema from criteria_catalog (DESIGN §10.2 P1, §8.2)."""

from __future__ import annotations

import pytest
from manzil_shared.catalog import CATALOG, SCOPED_UNIT_CLAIM_KEYS
from manzil_worker.stages.schema_gen import (
    build_extraction_schema,
    extractable_entries,
    field_model,
)
from pydantic import ValidationError
from worker_helpers import extraction_payload, field_payload, maple_extraction

EXPECTED_KEYS = {
    "patio_balcony",
    "private_entry",
    "in_unit_laundry",
    "pets_policy",
    "parking",
    "cooling",
    "dishwasher",
    "walk_in_closets",
    "pantry",
    "disposal",
    "fireplace",
    "ceiling_fans",
    "stainless_steel_appliances",
    "flooring_materials",
    "is_renovated",
    "min_lease_months",
    "year_built",
    "pool",
    "fitness_center",
    "clubhouse",
    "emergency_maintenance",
    "maintenance_on_site",
    "management_on_site",
    "online_payments",
    "online_maintenance_requests",
    "package_handling",
    "smoking_policy",
    "property_types",
    "internet_readiness",
}


def test_extractable_set_is_page_text_only() -> None:
    """Tool-dependent criteria and pipeline-composed values never reach the
    extraction schema — extraction stages get zero tools (§16)."""
    keys = {e.key for e in extractable_entries()}
    assert keys == EXPECTED_KEYS
    assert "all_in_monthly" not in keys  # composed (§9.5), never extracted
    assert "grocery_proximity" not in keys  # requires maps tool
    assert "location_safety" not in keys  # requires web search
    assert "kitchen_quality" not in keys  # vision criterion (P3-7), not page text


def test_schema_has_one_field_per_criterion_plus_floor_plans() -> None:
    schema = build_extraction_schema()
    assert set(schema.model_fields) == EXPECTED_KEYS | {
        "floor_plans",
        "property_identity",
        "pet_costs",
        "utilities",
        "mandatory_fees",  # §9.5 P3-9
        "heating",  # §9.5 P3-9
        "one_time_fees",  # §9.5 §20 2026-07-18
        "property_contact",  # P3-21 §20 2026-07-27
    }


def test_floor_plan_values_derive_from_floor_plans_and_legacy_top_level_is_ignored() -> None:
    schema = build_extraction_schema()
    assert "unit_types" not in schema.model_fields
    assert "beds" not in schema.model_fields
    assert "baths" not in schema.model_fields
    assert "sqft" not in schema.model_fields
    assert "security_deposit" not in schema.model_fields
    assert "availability_date" not in schema.model_fields

    parsed = schema.model_validate(
        extraction_payload(
            beds=field_payload(1, "Legacy generalized claim"),
            baths=field_payload(1, "Legacy generalized claim"),
            sqft=field_payload(500, "Legacy generalized claim"),
            security_deposit=field_payload(100, "Legacy generalized claim"),
            availability_date=field_payload("2026-08-01", "Legacy generalized claim"),
            unit_types=field_payload(["apartment"], "Legacy generalized claim"),
            floor_plans=[
                {
                    "response_key": "a1",
                    "beds": 2,
                    "baths": 1,
                    "sqft_min": 700,
                    "deposit": 500,
                    "availability_date": "2026-09-01",
                    "unit_types": ["loft"],
                }
            ],
        )
    )

    assert parsed.floor_plans[0].beds == 2
    assert parsed.floor_plans[0].baths == 1
    assert parsed.floor_plans[0].sqft_min == 700
    assert parsed.floor_plans[0].deposit == 500
    assert parsed.floor_plans[0].availability_date == "2026-09-01"
    assert parsed.floor_plans[0].unit_types == ["loft"]


def test_pet_costs_and_utilities_are_optional_and_default_none() -> None:
    """Both §9.5 blocks are non-catalog and optional — a payload without them
    validates to None, so recorded fixtures and stored RunState snapshots that
    predate them keep validating."""
    schema = build_extraction_schema()
    parsed = schema.model_validate(extraction_payload())
    assert parsed.pet_costs is None
    assert parsed.utilities is None


def test_pet_costs_block_validates() -> None:
    schema = build_extraction_schema()
    payload = extraction_payload(
        pet_costs={
            "cat_rent_monthly": 20.0,
            "dog_rent_monthly": 35.0,
            "pet_rent_monthly": None,
            "evidence_quote": "Cat rent $20, dog rent $35",
        }
    )
    parsed = schema.model_validate(payload)
    assert parsed.pet_costs.cat_rent_monthly == 20.0
    assert parsed.pet_costs.dog_rent_monthly == 35.0
    assert parsed.pet_costs.pet_rent_monthly is None


def test_utilities_included_list_validates_and_rejects_unknown_kind() -> None:
    schema = build_extraction_schema()
    ok = extraction_payload(
        utilities={"included": ["water", "sewer"], "evidence_quote": "Water and sewer included"}
    )
    parsed = schema.model_validate(ok)
    assert parsed.utilities.included == ["water", "sewer"]

    empty = extraction_payload(utilities={"included": [], "evidence_quote": None})
    assert schema.model_validate(empty).utilities.included == []

    bad = extraction_payload(utilities={"included": ["moonlight"]})
    with pytest.raises(ValidationError, match="utilities"):
        schema.model_validate(bad)


def test_property_identity_is_optional_and_defaults_none() -> None:
    """Identity is a non-catalog block like floor_plans; absent from the payload it
    validates to None so recorded LLM fixtures and stored RunState snapshots that
    predate it keep validating (DESIGN §20 2026-07-10)."""
    schema = build_extraction_schema()
    parsed = schema.model_validate(extraction_payload())
    assert parsed.property_identity is None


def test_property_identity_full_block_validates() -> None:
    schema = build_extraction_schema()
    payload = extraction_payload(
        property_identity={
            "name": "Maple Court Apartments",
            "address": "120 Maple Court Dr, Detroit, MI 48187",
            "official_url": None,
        }
    )
    parsed = schema.model_validate(payload)
    assert parsed.property_identity.name == "Maple Court Apartments"
    assert parsed.property_identity.address == "120 Maple Court Dr, Detroit, MI 48187"
    assert parsed.property_identity.official_url is None


def test_property_identity_matches_floor_plan_extra_policy() -> None:
    """PropertyIdentityIn mirrors FloorPlanIn's config — extra keys are ignored,
    not rejected. Don't invent stricter validation than the sibling block."""
    schema = build_extraction_schema()
    payload = extraction_payload(
        property_identity={"name": "Maple Court Apartments", "place_id": "ChIJdeadbeef"}
    )
    parsed = schema.model_validate(payload)
    assert parsed.property_identity.name == "Maple Court Apartments"
    assert not hasattr(parsed.property_identity, "place_id")


def test_every_criterion_field_is_value_confidence_evidence() -> None:
    schema = build_extraction_schema()
    parsed = schema.model_validate(extraction_payload())
    for key in EXPECTED_KEYS:
        field = getattr(parsed, key)
        if key in SCOPED_UNIT_CLAIM_KEYS:
            assert field == []
        else:
            assert set(type(field).model_fields) == {"value", "confidence", "evidence_quote"}


def test_full_realistic_payload_validates() -> None:
    schema = build_extraction_schema()
    parsed = schema.model_validate(maple_extraction())
    assert parsed.floor_plans[0].plan_name == "The Maple"
    assert parsed.floor_plans[0].beds == 2


def test_missing_criterion_field_is_a_schema_violation() -> None:
    payload = extraction_payload()
    del payload["pets_policy"]
    with pytest.raises(ValidationError, match="pets_policy"):
        build_extraction_schema().model_validate(payload)


def test_unknown_extra_field_is_forbidden() -> None:
    payload = extraction_payload()
    payload["swimming_pool"] = field_payload(True)
    with pytest.raises(ValidationError, match="swimming_pool"):
        build_extraction_schema().model_validate(payload)


def test_enum_and_bounds_are_enforced() -> None:
    schema = build_extraction_schema()
    bad_enum = extraction_payload(parking=field_payload("valet"))
    with pytest.raises(ValidationError, match="parking"):
        schema.model_validate(bad_enum)
    out_of_bounds = extraction_payload(year_built=field_payload(1600))
    with pytest.raises(ValidationError, match="year_built"):
        schema.model_validate(out_of_bounds)


def test_array_schema_enforces_item_vocabulary_and_uniqueness() -> None:
    schema = build_extraction_schema()
    parsed = schema.model_validate(
        extraction_payload(property_types=field_payload(["apartment", "loft"]))
    )
    assert parsed.property_types.value == ["apartment", "loft"]

    with pytest.raises(ValidationError, match="property_types"):
        schema.model_validate(extraction_payload(property_types=field_payload(["castle"])))
    with pytest.raises(ValidationError, match="unique"):
        schema.model_validate(
            extraction_payload(property_types=field_payload(["apartment", "apartment"]))
        )


def test_floor_plan_unit_types_use_the_same_controlled_vocabulary() -> None:
    payload = extraction_payload(
        floor_plans=[{"response_key": "loft-a", "plan_name": "Loft A", "unit_types": ["loft"]}]
    )
    parsed = build_extraction_schema().model_validate(payload)
    assert parsed.floor_plans[0].unit_types == ["loft"]

    payload["floor_plans"][0]["unit_types"] = ["castle"]
    with pytest.raises(ValidationError, match="floor_plans"):
        build_extraction_schema().model_validate(payload)

    payload["floor_plans"][0]["unit_types"] = ["loft", "loft"]
    with pytest.raises(ValidationError, match="unique"):
        build_extraction_schema().model_validate(payload)


def test_extraction_hints_ride_in_field_descriptions() -> None:
    """Hints reach the model inside the (cached) tool schema, not via prompts."""
    beds = next(e for e in CATALOG if e.key == "beds")
    description = field_model(beds).model_fields["value"].description
    assert description is not None
    assert "a studio is 0" in description


def test_availability_date_hint_states_explicit_date_precedence() -> None:
    """Available Now must not override an explicit Property/Floor Plan date."""
    avail = next(e for e in CATALOG if e.key == "availability_date")
    description = field_model(avail).model_fields["value"].description
    assert description is not None
    assert "available_now" in description
    assert "explicit" in description.casefold()
    assert "EMBEDDED DATA" in description

    floor_plans_desc = build_extraction_schema().model_fields["floor_plans"].description
    assert floor_plans_desc is not None
    assert "available_now" in floor_plans_desc
    assert "explicit" in floor_plans_desc.casefold()
    assert "EMBEDDED DATA" in floor_plans_desc


def test_stringified_field_object_is_coerced() -> None:
    """Some models emit a nested field as a JSON string instead of an object
    (observed on year_built with haiku); the schema parses it back rather
    than failing the whole extraction."""
    import json

    schema = build_extraction_schema()
    stringified = json.dumps(field_payload(1995, quote="Built in 1995"))
    parsed = schema.model_validate(extraction_payload(year_built=stringified))
    assert parsed.year_built.value == 1995
    assert parsed.year_built.confidence == "high"


def test_non_json_string_field_is_still_rejected() -> None:
    """The coercion only rescues a stringified object — real garbage still fails
    loudly rather than being swallowed."""
    schema = build_extraction_schema()
    with pytest.raises(ValidationError, match="year_built"):
        schema.model_validate(extraction_payload(year_built="not json at all"))


def test_malformed_stringified_field_is_rejected_not_swallowed() -> None:
    """The exact haiku failure from the first bench run: a hand-built string
    with unescaped quotes inside the evidence. No parser can salvage it — it
    must fail loudly so the corrective retry (and prompt rule 8) handle it."""
    malformed = (
        '{\n  "value": 1995,\n  "confidence": "high",\n  "evidence_quote": "built":"1995"\n}'
    )
    with pytest.raises(ValidationError, match="year_built"):
        build_extraction_schema().model_validate(extraction_payload(year_built=malformed))


def test_stringified_floor_plans_array_is_coerced() -> None:
    """The same rescue for the top-level list: floor_plans emitted as a JSON
    string of an array parses instead of failing the extraction."""
    import json

    plans = json.dumps([{"plan_name": "A1", "beds": 1, "rent_min": 1443.0}])
    parsed = build_extraction_schema().model_validate(extraction_payload(floor_plans=plans))
    assert parsed.floor_plans[0].plan_name == "A1"
    assert parsed.floor_plans[0].rent_min == 1443.0


def test_null_criterion_wrapper_is_normalized_to_unknown() -> None:
    """Gemini emits null for the whole wrapper when the fact is unknown.
    Normalize that provider-shaped equivalent without weakening missing-key
    validation."""
    payload = extraction_payload()
    payload["parking"] = None

    parsed = build_extraction_schema().model_validate(payload)

    assert parsed.parking == []


def test_null_floor_plan_entries_are_removed() -> None:
    """Gemini 3 occasionally pads its Floor Plan array with a null item."""
    payload = extraction_payload(floor_plans=[None, {"plan_name": "A1", "beds": 1}])

    parsed = build_extraction_schema().model_validate(payload)

    assert [plan.plan_name for plan in parsed.floor_plans] == ["A1"]


def test_object_not_string_instruction_rides_in_the_tool_schema() -> None:
    """The anti-stringification nudge must reach the model inside the (cached)
    tool schema, not just the prompt."""
    schema = build_extraction_schema().model_json_schema()
    year_built_ref = schema["properties"]["year_built"]["$ref"].rsplit("/", 1)[-1]
    description = schema["$defs"][year_built_ref]["description"]
    assert "NEVER as a JSON-encoded string" in description


def test_null_value_needs_no_evidence_but_keeps_confidence() -> None:
    schema = build_extraction_schema()
    parsed = schema.model_validate(extraction_payload())
    assert parsed.dishwasher == []


def test_scoped_claim_requires_valid_source_local_target() -> None:
    schema = build_extraction_schema()
    payload = extraction_payload(
        floor_plans=[{"response_key": "a1", "plan_name": "A1"}],
        dishwasher=[
            {
                "value": True,
                "confidence": "high",
                "evidence_quote": "A1 includes dishwasher",
                "applicability": "specific_floor_plans",
                "floor_plan_refs": ["a1"],
            }
        ],
    )
    parsed = schema.model_validate(payload)
    assert parsed.dishwasher[0].floor_plan_refs == ["a1"]

    payload["dishwasher"][0]["floor_plan_refs"] = ["invented"]
    normalized = schema.model_validate(payload)
    assert normalized.dishwasher[0].floor_plan_refs == []
    assert normalized.dishwasher[0].applicability == "unit_scope_unspecified"


def test_sc6_presence_and_sc7_material_claims_share_the_scoped_contract() -> None:
    payload = extraction_payload(
        floor_plans=[{"response_key": "a1", "plan_name": "A1"}],
        fireplace=[
            {
                "value": True,
                "confidence": "high",
                "evidence_quote": "A1 includes a fireplace",
                "applicability": "specific_floor_plans",
                "floor_plan_refs": ["a1"],
            }
        ],
        flooring_materials=[
            {
                "value": ["hardwood", "tile"],
                "confidence": "high",
                "evidence_quote": "Hardwood living areas and tile bath",
                "applicability": "specific_floor_plans",
                "floor_plan_refs": ["a1"],
            }
        ],
    )
    parsed = build_extraction_schema().model_validate(payload)
    assert parsed.fireplace[0].value is True
    assert parsed.flooring_materials[0].value == ["hardwood", "tile"]

    payload["flooring_materials"][0]["value"] = ["hardwood", "marble"]
    with pytest.raises(ValidationError, match="flooring_materials"):
        build_extraction_schema().model_validate(payload)

    payload["flooring_materials"][0]["value"] = ["tile", "tile"]
    with pytest.raises(ValidationError, match="unique"):
        build_extraction_schema().model_validate(payload)


def test_scoped_claim_rejects_universal_scope_with_refs() -> None:
    payload = extraction_payload(
        floor_plans=[{"response_key": "a1", "plan_name": "A1"}],
        cooling=[
            {
                "value": "central",
                "confidence": "high",
                "evidence_quote": "All homes have central air",
                "applicability": "all_units",
                "floor_plan_refs": ["a1"],
            }
        ],
    )
    with pytest.raises(ValidationError, match="only specific_floor_plans"):
        build_extraction_schema().model_validate(payload)


def test_typed_scoped_claim_accepts_distinct_values_for_same_concrete_target() -> None:
    claim = {
        "value": "in_unit",
        "confidence": "high",
        "evidence_quote": "Laundry amenities",
        "applicability": "unit_scope_unspecified",
        "floor_plan_refs": [],
    }
    payload = extraction_payload(in_unit_laundry=[claim, {**claim, "value": "on_site"}])
    parsed = build_extraction_schema().model_validate(payload)
    assert [item.value for item in parsed.in_unit_laundry] == ["in_unit", "on_site"]


def test_flooring_sets_with_distinct_scopes_can_coexist() -> None:
    payload = extraction_payload(
        flooring_materials=[
            {
                "value": ["vinyl"],
                "confidence": "high",
                "evidence_quote": "wood-style vinyl flooring",
                "applicability": "all_units",
                "floor_plan_refs": [],
            },
            {
                "value": ["hardwood", "carpet"],
                "confidence": "high",
                "evidence_quote": "Hardwood Floors … Carpet",
                "applicability": "unit_scope_unspecified",
                "floor_plan_refs": [],
            },
        ]
    )

    parsed = build_extraction_schema().model_validate(payload)

    assert [claim.value for claim in parsed.flooring_materials] == [
        ["vinyl"],
        ["hardwood", "carpet"],
    ]


def test_malformed_exact_select_wording_normalizes_without_inventing_ref() -> None:
    payload = extraction_payload(
        floor_plans=[{"response_key": "a1", "plan_name": "A1"}],
        fireplace=[
            {
                "value": True,
                "confidence": "high",
                "evidence_quote": "Fireplace (in Select Townhomes)",
                "applicability": "specific_floor_plans",
                "floor_plan_refs": [],
            }
        ],
    )

    parsed = build_extraction_schema().model_validate(payload)

    assert parsed.fireplace[0].applicability == "select_units"
    assert parsed.fireplace[0].floor_plan_refs == []


def test_typed_none_cannot_coexist_with_positive_at_same_target() -> None:
    claim = {
        "confidence": "high",
        "evidence_quote": "Parking details",
        "applicability": "all_units",
        "floor_plan_refs": [],
    }
    payload = extraction_payload(
        parking=[
            {**claim, "value": "carport"},
            {**claim, "value": "none"},
        ]
    )

    with pytest.raises(ValidationError, match="cannot coexist"):
        build_extraction_schema().model_validate(payload)


def test_laundry_positive_canonicalizes_redundant_generalized_none() -> None:
    payload = extraction_payload(
        in_unit_laundry=[
            {
                "value": "none",
                "confidence": "high",
                "evidence_quote": "In-unit laundry is not available.",
                "applicability": "all_units",
                "floor_plan_refs": [],
            },
            {
                "value": "on_site",
                "confidence": "high",
                "evidence_quote": "laundry facility located in each building",
                "applicability": "unit_scope_unspecified",
                "floor_plan_refs": [],
            },
        ]
    )

    parsed = build_extraction_schema().model_validate(payload)

    assert len(parsed.in_unit_laundry) == 1
    assert parsed.in_unit_laundry[0].value == "on_site"
    assert parsed.in_unit_laundry[0].applicability == "unit_scope_unspecified"
