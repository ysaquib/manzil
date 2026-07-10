"""P0-8: dynamic extraction schema from criteria_catalog (DESIGN §10.2 P1, §8.2)."""

from __future__ import annotations

import pytest
from manzil_shared.catalog import CATALOG
from manzil_worker.stages.schema_gen import (
    build_extraction_schema,
    extractable_entries,
    field_model,
)
from pydantic import ValidationError
from worker_helpers import extraction_payload, field_payload, maple_extraction

EXPECTED_KEYS = {
    "beds",
    "baths",
    "sqft",
    "patio_balcony",
    "private_entry",
    "in_unit_laundry",
    "pets_policy",
    "security_deposit",
    "availability_date",
    "parking",
    "cooling",
    "dishwasher",
    "min_lease_months",
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
    assert set(schema.model_fields) == EXPECTED_KEYS | {"floor_plans", "property_identity"}


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
        assert set(type(field).model_fields) == {"value", "confidence", "evidence_quote"}


def test_full_realistic_payload_validates() -> None:
    schema = build_extraction_schema()
    parsed = schema.model_validate(maple_extraction())
    assert parsed.beds.value == 2
    assert parsed.floor_plans[0].plan_name == "The Maple"


def test_missing_criterion_field_is_a_schema_violation() -> None:
    payload = extraction_payload()
    del payload["beds"]
    with pytest.raises(ValidationError, match="beds"):
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
    out_of_bounds = extraction_payload(beds=field_payload(7))  # catalog max is 5
    with pytest.raises(ValidationError, match="beds"):
        schema.model_validate(out_of_bounds)


def test_extraction_hints_ride_in_field_descriptions() -> None:
    """Hints reach the model inside the (cached) tool schema, not via prompts."""
    beds = next(e for e in CATALOG if e.key == "beds")
    description = field_model(beds).model_fields["value"].description
    assert description is not None
    assert "a studio is 0" in description


def test_stringified_field_object_is_coerced() -> None:
    """Some models emit a nested field as a JSON string instead of an object
    (observed on availability_date with haiku); the schema parses it back rather
    than failing the whole extraction."""
    import json

    schema = build_extraction_schema()
    stringified = json.dumps(field_payload("2026-07-02", quote="Available July 2"))
    parsed = schema.model_validate(extraction_payload(availability_date=stringified))
    assert parsed.availability_date.value == "2026-07-02"
    assert parsed.availability_date.confidence == "high"


def test_non_json_string_field_is_still_rejected() -> None:
    """The coercion only rescues a stringified object — real garbage still fails
    loudly rather than being swallowed."""
    schema = build_extraction_schema()
    with pytest.raises(ValidationError, match="availability_date"):
        schema.model_validate(extraction_payload(availability_date="not json at all"))


def test_malformed_stringified_field_is_rejected_not_swallowed() -> None:
    """The exact haiku failure from the first bench run: a hand-built string
    with unescaped quotes inside the evidence. No parser can salvage it — it
    must fail loudly so the corrective retry (and prompt rule 8) handle it."""
    malformed = (
        '{\n  "value": "2026-07-02",\n  "confidence": "high",\n'
        '  "evidence_quote": "dateAvailable":"2026-07-02T00:00:00.000Z"\n}'
    )
    with pytest.raises(ValidationError, match="availability_date"):
        build_extraction_schema().model_validate(extraction_payload(availability_date=malformed))


def test_stringified_floor_plans_array_is_coerced() -> None:
    """The same rescue for the top-level list: floor_plans emitted as a JSON
    string of an array parses instead of failing the extraction."""
    import json

    plans = json.dumps([{"plan_name": "A1", "beds": 1, "rent_min": 1443.0}])
    parsed = build_extraction_schema().model_validate(extraction_payload(floor_plans=plans))
    assert parsed.floor_plans[0].plan_name == "A1"
    assert parsed.floor_plans[0].rent_min == 1443.0


def test_object_not_string_instruction_rides_in_the_tool_schema() -> None:
    """The anti-stringification nudge must reach the model inside the (cached)
    tool schema, not just the prompt."""
    schema = build_extraction_schema().model_json_schema()
    beds_ref = schema["properties"]["beds"]["$ref"].rsplit("/", 1)[-1]
    description = schema["$defs"][beds_ref]["description"]
    assert "NEVER as a JSON-encoded string" in description


def test_null_value_needs_no_evidence_but_keeps_confidence() -> None:
    schema = build_extraction_schema()
    parsed = schema.model_validate(extraction_payload())
    assert parsed.dishwasher.value is None
    assert parsed.dishwasher.confidence == "not_found"
