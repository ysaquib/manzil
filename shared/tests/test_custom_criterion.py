"""P3-10 versioned custom Criterion contract."""

from __future__ import annotations

from uuid import uuid4

import pytest
from manzil_shared.models import CustomCriterionDef
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
    CustomCriterionDef.model_validate(
        _definition(requires_tool="maps", refresh_class="location")
    )
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
        CustomCriterionDef.model_validate(
            _definition(requires_tool="vision")
        )


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
