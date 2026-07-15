"""Scoring engine — pure, deterministic, LLM-free (DESIGN §9.3, §9.4).

`score(rubric, effective_values, floor_plan) -> ScoreBreakdown`:

1. Effective values arrive resolved (override > latest extraction > unknown,
   confidence-thresholded) — a missing key or `None` means unknown. Floor-plan
   fields overlay the property-level values for plan-scoped criteria.
2. Gate pass: evaluate all dealbreakers and non-negotiables first. Any firing
   -> total = min(set_scores fired), breakdown records the gates, stop.
3. Delta pass: start at BASE_SCORE; apply the first-matching option's delta
   per enabled criterion; unknown -> `unknown_delta`.
4. Clamp to [SCORE_MIN, SCORE_MAX] (bonuses may exceed 10).

Semantics recorded in DESIGN §3 (Gate), §9.3, and the v2.1 §20 entry:

- Options are ordered; first match wins (§9.2). A known value matching no
  option contributes delta 0.
- A **dealbreaker** fires when the first-matching option carries
  `dealbreaker_set_score`.
- A **non-negotiable** fires unless the value is known and its first-matching
  option is *acceptable*: `delta >= 0` and not itself a dealbreaker option.
  Unknown values therefore fire the gate — a non-negotiable cannot be
  satisfied by missing data.
- Object values (e.g. `management_reviews` `{rating, summary}`) compare on
  their `"rating"` field.
- `range` matches are inclusive on both ends. Ordered comparisons compare
  numbers, or strings pairwise (ISO dates order correctly as strings).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from manzil_shared.models import (
    BreakdownCriterion,
    FloorPlan,
    GateFiring,
    MatchOp,
    OptionMatch,
    RubricCriterion,
    RubricOption,
    ScoreBreakdown,
)

# Contract constants (§9.3) — not tunables: the breakdown shape pins base 10
# and the [0, 15] clamp.
BASE_SCORE = 10.0
SCORE_MIN = 0.0
SCORE_MAX = 15.0


def criterion_key(criterion: RubricCriterion) -> str:
    """Catalog criteria use `catalog_key`; custom criteria carry their hunt-scoped
    key in `custom_def["key"]` (§8.2)."""
    if criterion.catalog_key is not None:
        return criterion.catalog_key
    if criterion.custom_def is not None and "key" in criterion.custom_def:
        return str(criterion.custom_def["key"])
    raise ValueError("rubric criterion has neither catalog_key nor custom_def['key']")


def _comparable(value: Any) -> Any:
    if isinstance(value, Mapping) and "rating" in value:
        return value["rating"]
    return value


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _ordered(a: Any, b: Any) -> bool:
    """True when a and b are mutually comparable for lt/gt/range."""
    return (_is_number(a) and _is_number(b)) or (isinstance(a, str) and isinstance(b, str))


def matches(match: OptionMatch, value: Any) -> bool:
    """Evaluate one option match against a known (non-None) value. Type
    mismatches never raise — they simply don't match."""
    v = _comparable(value)
    mv = match.value
    op = match.op
    if op is MatchOp.EQ:
        if isinstance(v, bool) != isinstance(mv, bool):  # True == 1 must not match eq 1
            return False
        return bool(v == mv)
    if op is MatchOp.BOOL:
        return isinstance(v, bool) and v is bool(mv)
    if op is MatchOp.LT:
        return _ordered(v, mv) and v < mv
    if op is MatchOp.LTE:
        return _ordered(v, mv) and v <= mv
    if op is MatchOp.GT:
        return _ordered(v, mv) and v > mv
    if op is MatchOp.GTE:
        return _ordered(v, mv) and v >= mv
    if op is MatchOp.RANGE:
        if not isinstance(mv, Sequence) or isinstance(mv, str) or len(mv) != 2:
            return False
        lo, hi = mv[0], mv[1]
        return _ordered(v, lo) and _ordered(v, hi) and lo <= v <= hi
    if op is MatchOp.IN:
        return isinstance(mv, Sequence) and not isinstance(mv, str) and v in mv
    return False


def first_match(options: Sequence[RubricOption], value: Any) -> RubricOption | None:
    """Options are ordered; first match wins (§9.2). `None` (unknown) matches nothing."""
    if value is None:
        return None
    for option in options:
        if matches(option.match, value):
            return option
    return None


def plan_values(floor_plan: FloorPlan) -> dict[str, Any]:
    """Per-plan overlay for plan-scoped criteria (§9.4: each floor plan is scored
    independently). `sqft` uses the conservative end of the range (min when
    present) — the tool never makes a unit look better than its worst case."""
    values: dict[str, Any] = {"beds": floor_plan.beds, "baths": floor_plan.baths}
    sqft = floor_plan.sqft_min if floor_plan.sqft_min is not None else floor_plan.sqft_max
    if sqft is not None:
        values["sqft"] = sqft
    if floor_plan.deposit is not None:
        values["security_deposit"] = float(floor_plan.deposit)
    if floor_plan.availability_date is not None:
        values["availability_date"] = floor_plan.availability_date.isoformat()
    return values


def score(
    rubric: Sequence[RubricCriterion],
    effective_values: Mapping[str, Any],
    floor_plan: FloorPlan | None = None,
    *,
    rubric_version: int,
) -> ScoreBreakdown:
    """Facts in, points out — nothing else. See module docstring for the passes."""
    values: dict[str, Any] = dict(effective_values)
    if floor_plan is not None:
        values.update(plan_values(floor_plan))

    enabled = [c for c in rubric if c.enabled]

    # Gate pass (§9.3 step 2): min, never average — multiple gates must not average up.
    gates: list[GateFiring] = []
    for criterion in enabled:
        key = criterion_key(criterion)
        value = values.get(key)
        matched = first_match(criterion.options, value)
        if matched is not None and matched.dealbreaker_set_score is not None:
            gates.append(
                GateFiring(key=key, kind="dealbreaker", set_score=matched.dealbreaker_set_score)
            )
        if criterion.non_negotiable is not None:
            acceptable = (
                matched is not None and matched.delta >= 0 and matched.dealbreaker_set_score is None
            )
            if not acceptable:
                gates.append(
                    GateFiring(
                        key=key,
                        kind="non_negotiable",
                        set_score=criterion.non_negotiable.set_score,
                    )
                )
    if gates:
        return ScoreBreakdown(
            base=BASE_SCORE,
            total=min(g.set_score for g in gates),
            rubric_version=rubric_version,
            clamped=False,
            gates=gates,
            criteria=[],
        )

    # Delta pass (§9.3 step 3).
    total = BASE_SCORE
    criteria: list[BreakdownCriterion] = []
    for criterion in enabled:
        key = criterion_key(criterion)
        value = values.get(key)
        if value is None:
            criteria.append(
                BreakdownCriterion(
                    key=key, value=None, matched=None, delta=criterion.unknown_delta, unknown=True
                )
            )
            total += criterion.unknown_delta
            continue
        matched = first_match(criterion.options, value)
        delta = matched.delta if matched is not None else 0.0
        criteria.append(
            BreakdownCriterion(
                key=key,
                value=value,
                matched=matched.match if matched is not None else None,
                delta=delta,
            )
        )
        total += delta

    total = round(total, 6)  # keep quarter-point sums free of float noise
    clamped = total < SCORE_MIN or total > SCORE_MAX
    return ScoreBreakdown(
        base=BASE_SCORE,
        total=min(max(total, SCORE_MIN), SCORE_MAX),
        rubric_version=rubric_version,
        clamped=clamped,
        gates=[],
        criteria=criteria,
    )


def select_display_score(breakdowns: Sequence[ScoreBreakdown], pinned: int | None = None) -> int:
    """§9.4: a unit group displays its best plan score unless a plan is pinned.
    Returns the index into `breakdowns`; ties keep the first (stable)."""
    if pinned is not None:
        return pinned
    return max(range(len(breakdowns)), key=lambda i: breakdowns[i].total)
