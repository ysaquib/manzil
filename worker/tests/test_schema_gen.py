"""P0-8: dynamic extraction schema from criteria_catalog (DESIGN §10.2 P1, §8.2)."""

from __future__ import annotations

import pytest
from conftest import extraction_payload, field_payload, maple_extraction
from manzil_shared.catalog import CATALOG
from manzil_worker.stages.schema_gen import (
    build_extraction_schema,
    extractable_entries,
    field_model,
)
from pydantic import ValidationError

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
    assert set(schema.model_fields) == EXPECTED_KEYS | {"floor_plans"}


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


def test_null_value_needs_no_evidence_but_keeps_confidence() -> None:
    schema = build_extraction_schema()
    parsed = schema.model_validate(extraction_payload())
    assert parsed.dishwasher.value is None
    assert parsed.dishwasher.confidence == "not_found"
