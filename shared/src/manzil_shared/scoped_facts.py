"""Pure scoped-fact selection for SCORE and rescore (DESIGN §9.3).

This module is deliberately domain-blind and LLM-free. Callers supply current
resolved Extractions/current Overrides and the concrete Floor Plan being
scored; this module applies specificity and confidence only.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from manzil_shared.catalog import (
    FLOORING_MATERIAL_VALUES,
    TYPED_MULTI_CLAIM_KEYS,
    TYPED_MULTI_CLAIM_VALUES,
)
from manzil_shared.models import Confidence, TargetScope, UnitApplicability

_CONFIDENCE_RANK = {
    Confidence.NOT_FOUND: 0,
    Confidence.LOW: 1,
    Confidence.MEDIUM: 2,
    Confidence.HIGH: 3,
}


@dataclass(frozen=True)
class ScopedValue:
    criterion_key: str
    value: Any
    confidence: Confidence = Confidence.HIGH
    target_scope: TargetScope = TargetScope.PROPERTY
    floor_plan_id: UUID | None = None
    applicability: UnitApplicability | None = None
    claim_variant: str | None = None
    observed_at: datetime | None = None
    origin_key: str | None = None
    resolution_rule: str | None = None


@dataclass(frozen=True)
class ScopedOverrideValue:
    criterion_key: str
    value: Any
    target_scope: TargetScope = TargetScope.PROPERTY
    floor_plan_id: UUID | None = None
    applicability: UnitApplicability | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class EffectiveFact:
    """Internal resolved fact with enough provenance for scoring policy."""

    value: Any
    target_scope: TargetScope
    applicability: UnitApplicability | None
    origin_key: str | None
    resolution_rule: str | None
    confidence: Confidence = Confidence.HIGH
    from_override: bool = False

    @property
    def vision(self) -> bool:
        return not self.from_override and (
            bool(self.origin_key and self.origin_key.startswith("vision:"))
            or bool(self.resolution_rule and self.resolution_rule.startswith("vision_"))
        )

    @property
    def generalized_vision(self) -> bool:
        return (
            self.vision
            and self.target_scope is TargetScope.PROPERTY
            and self.applicability is UnitApplicability.UNIT_SCOPE_UNSPECIFIED
        )


def meets_confidence(confidence: Confidence, minimum: Confidence) -> bool:
    return _CONFIDENCE_RANK[confidence] >= _CONFIDENCE_RANK[minimum]


def _row_meets_confidence(
    row: ScopedValue,
    *,
    minimum: Confidence,
    vision_minimum: Confidence | None,
) -> bool:
    is_vision = bool(row.origin_key and row.origin_key.startswith("vision:")) or bool(
        row.resolution_rule and row.resolution_rule.startswith("vision_")
    )
    threshold = vision_minimum if is_vision and vision_minimum is not None else minimum
    return meets_confidence(row.confidence, threshold)


def _newest(values: Iterable[ScopedValue]) -> ScopedValue | None:
    rows = list(values)
    if not rows:
        return None
    return max(
        rows, key=lambda row: row.observed_at.timestamp() if row.observed_at else float("-inf")
    )


def _newest_override(values: Iterable[ScopedOverrideValue]) -> ScopedOverrideValue | None:
    rows = list(values)
    if not rows:
        return None
    return max(
        rows, key=lambda row: row.created_at.timestamp() if row.created_at else float("-inf")
    )


def compose_presence(
    value: Any,
    applicability: UnitApplicability | None,
    *,
    boolean_claim: bool = True,
) -> Any:
    """Compose Source claim value + applicability into a scoreable unit value.

    Boolean claims use the effective presence vocabulary. Typed presence
    claims (laundry, parking, cooling) retain their exact/all-units value, but
    a generalized positive can assert only ``advertised_unconfirmed``.
    """
    if value is None:
        return None
    if value is False or value == "none":
        return "none"
    if applicability in {
        UnitApplicability.SELECT_UNITS,
        UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
    }:
        return "advertised_unconfirmed"
    return "confirmed" if boolean_claim else value


def _as_value_set(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return [value] if isinstance(value, str) else []


def _resolve_typed_multi_value(
    *,
    criterion_key: str,
    floor_plan_id: UUID | None,
    extractions: list[ScopedValue],
    overrides: list[ScopedOverrideValue],
    minimum: Confidence,
    vision_minimum: Confidence | None,
) -> list[str] | None:
    """Compose independently scoped enum claims into one scoreable set."""
    relevant_overrides = [
        row for row in overrides if row.criterion_key == criterion_key and row.value is not None
    ]
    exact_override = _newest_override(
        row
        for row in relevant_overrides
        if row.target_scope is TargetScope.FLOOR_PLAN and row.floor_plan_id == floor_plan_id
    )
    if exact_override is not None:
        values = _as_value_set(exact_override.value)
        return values or None
    all_override = _newest_override(
        row
        for row in relevant_overrides
        if row.target_scope is TargetScope.PROPERTY
        and row.applicability is UnitApplicability.ALL_UNITS
    )
    if all_override is not None:
        values = _as_value_set(all_override.value)
        return values or None

    eligible = [
        row
        for row in extractions
        if row.criterion_key == criterion_key
        and isinstance(row.value, str)
        and _row_meets_confidence(
            row,
            minimum=minimum,
            vision_minimum=vision_minimum,
        )
    ]
    exact_values = {
        str(row.value)
        for row in eligible
        if row.target_scope is TargetScope.FLOOR_PLAN and row.floor_plan_id == floor_plan_id
    }
    all_values = {
        str(row.value)
        for row in eligible
        if row.target_scope is TargetScope.PROPERTY
        and row.applicability is UnitApplicability.ALL_UNITS
    }
    exact_positive = exact_values - {"none"}
    all_positive = all_values - {"none"}
    if "none" in exact_values:
        if exact_positive:
            return None
        return ["none"]
    if exact_positive:
        confirmed = exact_positive | all_positive
    elif "none" in all_values:
        if all_positive:
            return None
        return ["none"]
    else:
        confirmed = all_positive

    uncertain = {
        str(row.value)
        for row in eligible
        if row.target_scope is TargetScope.PROPERTY
        and row.applicability
        in {
            UnitApplicability.SELECT_UNITS,
            UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
        }
        and row.value != "none"
    }
    ordered = [value for value in TYPED_MULTI_CLAIM_VALUES[criterion_key] if value in confirmed]
    if uncertain - confirmed:
        ordered.append("advertised_unconfirmed")
    return ordered or None


def _resolve_flooring_materials(
    *,
    floor_plan_id: UUID | None,
    extractions: list[ScopedValue],
    overrides: list[ScopedOverrideValue],
    minimum: Confidence,
    vision_minimum: Confidence | None,
) -> list[str] | None:
    """Union exact and universal flooring sets; weaker scopes stay unconfirmed."""
    relevant_overrides = [row for row in overrides if row.criterion_key == "flooring_materials"]
    exact_override = _newest_override(
        row
        for row in relevant_overrides
        if row.target_scope is TargetScope.FLOOR_PLAN and row.floor_plan_id == floor_plan_id
    )
    if exact_override is not None and exact_override.value is not None:
        values = _as_value_set(exact_override.value)
        return values or None
    all_override = _newest_override(
        row
        for row in relevant_overrides
        if row.target_scope is TargetScope.PROPERTY
        and row.applicability is UnitApplicability.ALL_UNITS
    )
    if all_override is not None and all_override.value is not None:
        values = _as_value_set(all_override.value)
        return values or None

    confirmed: set[str] = set()
    for row in extractions:
        applicable = (
            row.target_scope is TargetScope.FLOOR_PLAN and row.floor_plan_id == floor_plan_id
        ) or (
            row.target_scope is TargetScope.PROPERTY
            and row.applicability is UnitApplicability.ALL_UNITS
        )
        if (
            row.criterion_key == "flooring_materials"
            and applicable
            and _row_meets_confidence(
                row,
                minimum=minimum,
                vision_minimum=vision_minimum,
            )
        ):
            confirmed.update(_as_value_set(row.value))
    ordered = [value for value in FLOORING_MATERIAL_VALUES if value in confirmed]
    return ordered or None


def resolve_effective_value(
    *,
    criterion_key: str,
    floor_plan_id: UUID | None,
    extractions: Iterable[ScopedValue],
    overrides: Iterable[ScopedOverrideValue] = (),
    min_confidence: Confidence,
    min_vision_confidence: Confidence | None = None,
    presence_like: bool = False,
    boolean_presence: bool = True,
    generalized_unknown: bool = False,
) -> Any:
    """Resolve one Criterion for one Floor Plan in DESIGN §9.3 order.

    Exact Override ▸ all-units Override ▸ exact resolved Extraction ▸ true
    Property/all-units/generalized resolved Extraction ▸ unknown. A latest null
    Override is a target-specific tombstone and falls through.
    """
    extraction_rows = list(extractions)
    override_rows = list(overrides)
    if criterion_key in TYPED_MULTI_CLAIM_KEYS:
        return _resolve_typed_multi_value(
            criterion_key=criterion_key,
            floor_plan_id=floor_plan_id,
            extractions=extraction_rows,
            overrides=override_rows,
            minimum=min_confidence,
            vision_minimum=min_vision_confidence,
        )
    if criterion_key == "flooring_materials":
        return _resolve_flooring_materials(
            floor_plan_id=floor_plan_id,
            extractions=extraction_rows,
            overrides=override_rows,
            minimum=min_confidence,
            vision_minimum=min_vision_confidence,
        )

    scoped_unit = presence_like or generalized_unknown
    relevant_overrides = [row for row in override_rows if row.criterion_key == criterion_key]
    exact_override = _newest_override(
        row
        for row in relevant_overrides
        if row.target_scope is TargetScope.FLOOR_PLAN and row.floor_plan_id == floor_plan_id
    )
    if exact_override is not None and exact_override.value is not None:
        return exact_override.value
    all_override = _newest_override(
        row
        for row in relevant_overrides
        if row.target_scope is TargetScope.PROPERTY
        and row.applicability is UnitApplicability.ALL_UNITS
    )
    if all_override is not None and all_override.value is not None:
        return all_override.value
    if not scoped_unit:
        property_override = _newest_override(
            row
            for row in relevant_overrides
            if row.target_scope is TargetScope.PROPERTY and row.applicability is None
        )
        if property_override is not None and property_override.value is not None:
            return property_override.value

    eligible = [
        row
        for row in extraction_rows
        if row.criterion_key == criterion_key
        and row.value is not None
        and _row_meets_confidence(
            row,
            minimum=min_confidence,
            vision_minimum=min_vision_confidence,
        )
    ]
    exact = _newest(
        row
        for row in eligible
        if row.target_scope is TargetScope.FLOOR_PLAN and row.floor_plan_id == floor_plan_id
    )
    if exact is not None:
        return (
            compose_presence(
                exact.value,
                exact.applicability,
                boolean_claim=boolean_presence,
            )
            if presence_like
            else exact.value
        )

    # A true Property fact is distinct from generalized unit evidence. It is
    # still a valid effective value for every plan because its subject is the
    # Property, not because a unit association was inferred.
    if not scoped_unit:
        property_fact = _newest(
            row
            for row in eligible
            if row.target_scope is TargetScope.PROPERTY and row.applicability is None
        )
        if property_fact is not None:
            return property_fact.value

    for applicability in (
        UnitApplicability.ALL_UNITS,
        UnitApplicability.SELECT_UNITS,
        UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
    ):
        generalized = _newest(
            row
            for row in eligible
            if row.target_scope is TargetScope.PROPERTY and row.applicability is applicability
        )
        if generalized is not None:
            if generalized_unknown and applicability is not UnitApplicability.ALL_UNITS:
                return None
            return (
                compose_presence(
                    generalized.value,
                    generalized.applicability,
                    boolean_claim=boolean_presence,
                )
                if presence_like
                else generalized.value
            )
    return None


def resolve_effective_values(
    *,
    criterion_keys: Iterable[str],
    floor_plan_id: UUID | None,
    extractions: Iterable[ScopedValue],
    overrides: Iterable[ScopedOverrideValue] = (),
    min_confidence: Confidence,
    min_vision_confidence: Confidence | None = None,
    presence_like_keys: frozenset[str] = frozenset(),
    boolean_presence_keys: frozenset[str] = frozenset(),
    generalized_unknown_keys: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    extraction_rows = list(extractions)
    override_rows = list(overrides)
    values: dict[str, Any] = {}
    for key in criterion_keys:
        value = resolve_effective_value(
            criterion_key=key,
            floor_plan_id=floor_plan_id,
            extractions=extraction_rows,
            overrides=override_rows,
            min_confidence=min_confidence,
            min_vision_confidence=min_vision_confidence,
            presence_like=key in presence_like_keys,
            boolean_presence=key in boolean_presence_keys,
            generalized_unknown=key in generalized_unknown_keys,
        )
        if value is not None:
            values[key] = value
    return values


def resolve_effective_fact(
    *,
    criterion_key: str,
    floor_plan_id: UUID | None,
    extractions: Iterable[ScopedValue],
    overrides: Iterable[ScopedOverrideValue] = (),
    min_confidence: Confidence,
    min_vision_confidence: Confidence | None = None,
    presence_like: bool = False,
    boolean_presence: bool = True,
    generalized_unknown: bool = False,
) -> EffectiveFact | None:
    """Provenance-carrying companion to the value-only compatibility wrapper."""
    scoped_unit = presence_like or generalized_unknown
    extraction_rows = list(extractions)
    override_rows = list(overrides)
    value = resolve_effective_value(
        criterion_key=criterion_key,
        floor_plan_id=floor_plan_id,
        extractions=extraction_rows,
        overrides=override_rows,
        min_confidence=min_confidence,
        min_vision_confidence=min_vision_confidence,
        presence_like=presence_like,
        boolean_presence=boolean_presence,
        generalized_unknown=generalized_unknown,
    )
    if value is None:
        return None
    relevant_overrides = [
        row for row in override_rows if row.criterion_key == criterion_key and row.value is not None
    ]
    for candidates in (
        [
            row
            for row in relevant_overrides
            if row.target_scope is TargetScope.FLOOR_PLAN and row.floor_plan_id == floor_plan_id
        ],
        [
            row
            for row in relevant_overrides
            if row.target_scope is TargetScope.PROPERTY
            and row.applicability is UnitApplicability.ALL_UNITS
        ],
        [
            row
            for row in relevant_overrides
            if not scoped_unit
            and row.target_scope is TargetScope.PROPERTY
            and row.applicability is None
        ],
    ):
        selected_override = _newest_override(candidates)
        if selected_override is not None:
            return EffectiveFact(
                value=value,
                target_scope=selected_override.target_scope,
                applicability=selected_override.applicability,
                origin_key=None,
                resolution_rule=None,
                confidence=Confidence.HIGH,
                from_override=True,
            )
    eligible = [
        row
        for row in extraction_rows
        if row.criterion_key == criterion_key
        and row.value is not None
        and _row_meets_confidence(
            row,
            minimum=min_confidence,
            vision_minimum=min_vision_confidence,
        )
    ]
    groups = [
        [
            row
            for row in eligible
            if row.target_scope is TargetScope.FLOOR_PLAN and row.floor_plan_id == floor_plan_id
        ],
        [
            row
            for row in eligible
            if not scoped_unit
            and row.target_scope is TargetScope.PROPERTY
            and row.applicability is None
        ],
    ]
    groups.extend(
        [
            [
                row
                for row in eligible
                if row.target_scope is TargetScope.PROPERTY and row.applicability is applicability
            ]
            for applicability in (
                UnitApplicability.ALL_UNITS,
                UnitApplicability.SELECT_UNITS,
                UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
            )
        ]
    )
    for group in groups:
        selected = _newest(group)
        if selected is not None:
            return EffectiveFact(
                value=value,
                target_scope=selected.target_scope,
                applicability=selected.applicability,
                origin_key=selected.origin_key,
                resolution_rule=selected.resolution_rule,
                confidence=selected.confidence,
            )
    return None


def resolve_effective_facts(
    *,
    criterion_keys: Iterable[str],
    floor_plan_id: UUID | None,
    extractions: Iterable[ScopedValue],
    overrides: Iterable[ScopedOverrideValue] = (),
    min_confidence: Confidence,
    min_vision_confidence: Confidence | None = None,
    presence_like_keys: frozenset[str] = frozenset(),
    boolean_presence_keys: frozenset[str] = frozenset(),
    generalized_unknown_keys: frozenset[str] = frozenset(),
) -> dict[str, EffectiveFact]:
    extraction_rows = list(extractions)
    override_rows = list(overrides)
    output: dict[str, EffectiveFact] = {}
    for key in criterion_keys:
        fact = resolve_effective_fact(
            criterion_key=key,
            floor_plan_id=floor_plan_id,
            extractions=extraction_rows,
            overrides=override_rows,
            min_confidence=min_confidence,
            min_vision_confidence=min_vision_confidence,
            presence_like=key in presence_like_keys,
            boolean_presence=key in boolean_presence_keys,
            generalized_unknown=key in generalized_unknown_keys,
        )
        if fact is not None:
            output[key] = fact
    return output


def scoring_values_for_policy(
    facts: dict[str, EffectiveFact], policy: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split point/Gate inputs without changing the score-breakdown contract."""
    if policy not in {"full_rubric", "points_only", "unknown"}:
        raise ValueError(f"invalid generalized vision policy: {policy}")
    point_values: dict[str, Any] = {}
    gate_values: dict[str, Any] = {}
    for key, fact in facts.items():
        if not fact.generalized_vision:
            point_values[key] = fact.value
            if not fact.vision or fact.confidence is not Confidence.LOW:
                gate_values[key] = fact.value
        elif policy == "full_rubric":
            point_values[key] = fact.value
            if fact.confidence is not Confidence.LOW:
                gate_values[key] = fact.value
        elif policy == "points_only":
            point_values[key] = fact.value
    return point_values, gate_values
