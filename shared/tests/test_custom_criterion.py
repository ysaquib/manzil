"""P3-10 versioned custom Criterion contract."""

from __future__ import annotations

from uuid import uuid4

import pytest
from manzil_shared.models import CustomCriterionDef, RefreshClass
from pydantic import ValidationError


def _definition(**overrides):  # type: ignore[no-untyped-def]
    value = {
        "key": f"custom:{uuid4()}",
        "label": "Quiet hours",
        "description": "Whether quiet hours are stated.",
        "fact_scope": "property",
        "value_schema": {"type": "boolean"},
        "requires_tool": None,
        "refresh_class": "listing_details",
        "routing_confirmed": True,
    }
    value.update(overrides)
    return value


def test_controlled_enum_is_trimmed_and_keeps_distinct_values() -> None:
    custom = CustomCriterionDef.model_validate(
        _definition(value_schema={"type": "string", "enum": [" yes ", "no"]})
    )
    assert custom.value_schema == {"type": "string", "enum": ["yes", "no"]}


def test_controlled_enum_rejects_duplicates_after_trimming() -> None:
    with pytest.raises(ValidationError, match="2-20 value string enum"):
        CustomCriterionDef.model_validate(
            _definition(value_schema={"type": "string", "enum": ["yes", " yes "]})
        )


def test_maps_route_is_property_only_and_derives_location_refresh() -> None:
    CustomCriterionDef.model_validate(_definition(requires_tool="maps", refresh_class="location"))
    with pytest.raises(ValidationError, match="Property-scoped"):
        CustomCriterionDef.model_validate(
            _definition(
                requires_tool="maps",
                refresh_class="location",
                fact_scope="floor_plan",
            )
        )


def test_deferred_routes_cannot_be_confirmed() -> None:
    with pytest.raises(ValidationError, match="deferred"):
        CustomCriterionDef.model_validate(_definition(requires_tool="vision"))


def test_maps_route_modifiers_round_trip() -> None:
    custom = CustomCriterionDef.model_validate(
        _definition(
            requires_tool="maps",
            refresh_class="location",
            route_modifiers={"avoid_highways": True, "avoid_tolls": False, "avoid_ferries": True},
        )
    )
    assert custom.route_modifiers is not None
    assert custom.route_modifiers.avoid_highways is True
    assert custom.route_modifiers.avoid_ferries is True


def _manual(**overrides):  # type: ignore[no-untyped-def]
    return _definition(acquisition="manual", refresh_class="manual", **overrides)


def test_definitions_default_to_the_extracted_acquisition() -> None:
    custom = CustomCriterionDef.model_validate(_definition())
    assert custom.acquisition == "extracted"
    assert custom.is_manual is False


def test_manual_criterion_needs_no_producer_and_no_refetch() -> None:
    custom = CustomCriterionDef.model_validate(_manual())
    assert custom.is_manual is True
    assert custom.requires_tool is None
    assert custom.refresh_class is RefreshClass.MANUAL


def test_manual_criterion_may_be_floor_plan_scoped() -> None:
    custom = CustomCriterionDef.model_validate(_manual(fact_scope="floor_plan"))
    assert custom.fact_scope == "floor_plan"


def test_manual_criterion_rejects_a_tool_route() -> None:
    with pytest.raises(ValidationError, match="cannot require a tool"):
        CustomCriterionDef.model_validate(_manual(requires_tool="maps"))


def test_manual_criterion_rejects_a_producer_refresh_class() -> None:
    with pytest.raises(ValidationError, match="must be 'manual'"):
        CustomCriterionDef.model_validate(
            _definition(acquisition="manual", refresh_class="listing_details")
        )


def test_manual_criterion_rejects_route_modifiers() -> None:
    with pytest.raises(ValidationError, match="route modifiers"):
        CustomCriterionDef.model_validate(_manual(route_modifiers={"avoid_tolls": True}))


def test_manual_refresh_class_requires_the_manual_acquisition() -> None:
    with pytest.raises(ValidationError, match="requires acquisition 'manual'"):
        CustomCriterionDef.model_validate(_definition(refresh_class="manual"))


def test_manual_criterion_still_requires_a_confirmed_route() -> None:
    with pytest.raises(ValidationError, match="human-confirmed"):
        CustomCriterionDef.model_validate(_manual(routing_confirmed=False))
