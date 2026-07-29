from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from manzil_shared.errors import CheckpointRaised
from manzil_shared.models import (
    Confidence,
    JobType,
    MatchOp,
    NonNegotiable,
    OptionMatch,
    RubricCriterion,
    RubricOption,
    TargetScope,
    UnitApplicability,
)
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.reconcile import reconcile_stage
from manzil_worker.state import (
    PlanManifest,
    RunState,
    SourceClaim,
    SourceResult,
)


def claim(
    source: str,
    value: object,
    *,
    key: str = "sqft",
    confidence: Confidence = Confidence.HIGH,
    applicability: UnitApplicability | None = UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
) -> SourceClaim:
    return SourceClaim(
        criterion_key=key,
        value=value,
        confidence=confidence,
        evidence_quote=str(value),
        source_id=source,
        model="fixture",
        prompt_version=1,
        target_scope=TargetScope.PROPERTY,
        applicability=applicability,
    )


def result(
    source: str,
    family: str,
    claims: list[SourceClaim],
    *,
    fetched_at: datetime | None = None,
    official: bool = False,
) -> SourceResult:
    return SourceResult(
        source_url=source,
        syndication_family=family,
        role="official_arbiter" if official else "baseline",
        is_official=official,
        fetched_at=fetched_at or datetime.now(UTC),
        source_claims=claims,
        verified=True,
    )


def state(*results: SourceResult) -> RunState:
    return RunState(
        job_id=uuid4(),
        job_type=JobType.INGEST,
        url=results[0].source_url,
        source_results=list(results),
        plan=PlanManifest(
            job_type="ingest",
            trigger="test",
            source_policy="tiers_1_2_3",
            sources=[],
            stages=["RECONCILE"],
            skipped={},
            est_cost_usd=0,
        ),
    )


def test_numeric_tolerance_takes_conservative_high_value() -> None:
    run = state(
        result("https://one.test", "one", [claim("https://one.test", 900)]),
        result("https://two.test", "two", [claim("https://two.test", 940)]),
    )
    out = asyncio.run(reconcile_stage(run, StageCtx()))
    assert out.resolved_claims[0].value == 940
    assert out.resolved_claims[0].resolution_rule == "numeric_tolerance_conservative"


def test_family_supermajority_counts_one_fresh_vote_per_family() -> None:
    now = datetime.now(UTC)
    run = state(
        result(
            "https://old.test",
            "shared-feed",
            [claim("https://old.test", "cats_only", key="pets_policy", applicability=None)],
            fetched_at=now - timedelta(days=1),
        ),
        result(
            "https://fresh.test",
            "shared-feed",
            [claim("https://fresh.test", "cats_and_dogs", key="pets_policy", applicability=None)],
            fetched_at=now,
        ),
        result(
            "https://independent.test",
            "other",
            [
                claim(
                    "https://independent.test",
                    "cats_and_dogs",
                    key="pets_policy",
                    applicability=None,
                )
            ],
        ),
    )
    out = asyncio.run(reconcile_stage(run, StageCtx()))
    assert out.resolved_claims[0].value == "cats_and_dogs"
    assert out.resolved_claims[0].resolution_rule == "family_supermajority"


def test_agreeing_value_uses_best_evidence_applicability() -> None:
    low = claim(
        "https://one.test",
        True,
        key="patio_balcony",
        confidence=Confidence.MEDIUM,
        applicability=UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
    )
    high = claim(
        "https://two.test",
        True,
        key="patio_balcony",
        confidence=Confidence.HIGH,
        applicability=UnitApplicability.ALL_UNITS,
    )
    out = asyncio.run(
        reconcile_stage(
            state(
                result("https://one.test", "one", [low]),
                result("https://two.test", "two", [high]),
            ),
            StageCtx(),
        )
    )
    assert out.resolved_claims[0].applicability is UnitApplicability.ALL_UNITS


def test_semantic_conflicts_are_normalized_in_one_batched_call() -> None:
    calls: list[dict[str, object]] = []

    async def normalize(stage_name, schema, content):  # type: ignore[no-untyped-def]
        assert stage_name == "reconcile_equivalence"
        payload = json.loads(content)
        calls.append(payload)
        return schema.model_validate(
            {
                "items": [
                    {
                        "item_id": item["item_id"],
                        "equivalence_key": item["criterion_key"],
                    }
                    for item in payload["claims"]
                ]
            }
        )

    one = "https://one.test"
    two = "https://two.test"
    run = state(
        result(
            one,
            "one",
            [
                claim(one, "cats & dogs", key="pets_policy", applicability=None),
                claim(one, "no smoking", key="smoking_policy", applicability=None),
            ],
        ),
        result(
            two,
            "two",
            [
                claim(two, "cats and dogs", key="pets_policy", applicability=None),
                claim(two, "smoke-free", key="smoking_policy", applicability=None),
            ],
        ),
    )

    out = asyncio.run(reconcile_stage(run, StageCtx(call_structured=normalize)))

    assert len(calls) == 1
    assert len(calls[0]["claims"]) == 4  # type: ignore[arg-type]
    assert {claim.criterion_key for claim in out.resolved_claims} == {
        "pets_policy",
        "smoking_policy",
    }
    assert all(claim.resolution_rule == "family_supermajority" for claim in out.resolved_claims)


def test_available_sources_positive_preferred_does_not_buy_escalation() -> None:
    one = "https://one.test"
    two = "https://two.test"
    run = state(
        result(
            one,
            "one",
            [claim(one, "outdoor", key="pool", confidence=Confidence.MEDIUM, applicability=None)],
        ),
        result(two, "two", [claim(two, "none", key="pool", applicability=None)]),
    )
    run.official_source_url = "https://official.test"

    out = asyncio.run(reconcile_stage(run, StageCtx()))

    assert out.resolved_claims[0].value == "outdoor"
    assert out.resolved_claims[0].resolution_rule == "verified_positive_preferred"
    assert out.resolved_claims[0].disputed is True
    assert out.plan is not None and out.plan.escalation is None


def test_sc6_presence_uses_p3_6_catalog_policy() -> None:
    one = "https://one.test"
    two = "https://two.test"
    run = state(
        result(one, "one", [claim(one, True, key="fireplace")]),
        result(two, "two", [claim(two, False, key="fireplace")]),
    )
    run.official_source_url = "https://official.test"

    out = asyncio.run(reconcile_stage(run, StageCtx()))

    assert out.resolved_claims[0].value is True
    assert out.resolved_claims[0].resolution_rule == "verified_positive_preferred"
    assert out.resolved_claims[0].disputed is True
    assert out.plan is not None and out.plan.escalation is None


def test_gate_upgrades_available_sources_policy_to_normal_escalation() -> None:
    one = "https://one.test"
    two = "https://two.test"
    run = state(
        result(one, "one", [claim(one, "outdoor", key="pool", applicability=None)]),
        result(two, "two", [claim(two, "none", key="pool", applicability=None)]),
    )
    run.official_source_url = "https://official.test"
    rubric = RubricCriterion(
        hunt_id=uuid4(),
        catalog_key="pool",
        options=[],
        non_negotiable=NonNegotiable(set_score=-10),
    )

    out = asyncio.run(reconcile_stage(run, StageCtx(rubric=[rubric])))

    assert out.plan is not None and out.plan.escalation is not None
    assert out.plan.escalation.rounds[0].kind == "official_arbiter"


def test_source_local_exact_targets_never_cross_match() -> None:
    one = "https://one.test"
    two = "https://two.test"

    def exact(url: str, ref: str, value: bool) -> SourceClaim:
        return SourceClaim(
            criterion_key="dishwasher",
            value=value,
            confidence=Confidence.HIGH,
            source_id=url,
            model="fixture",
            prompt_version=1,
            target_scope=TargetScope.FLOOR_PLAN,
            floor_plan_ref=ref,
            applicability=UnitApplicability.SPECIFIC_FLOOR_PLANS,
        )

    out = asyncio.run(
        reconcile_stage(
            state(
                result(one, "one", [exact(one, "a1", True)]),
                result(two, "two", [exact(two, "a1", False)]),
            ),
            StageCtx(),
        )
    )

    assert len(out.resolved_claims) == 2
    assert {claim.source_id for claim in out.resolved_claims} == {one, two}
    assert all(claim.resolution_rule == "single_source" for claim in out.resolved_claims)


def test_official_escalation_is_inserted_immediately_after_cursor() -> None:
    first = claim("https://one.test", "cats_only", key="pets_policy", applicability=None)
    second = claim("https://two.test", "none", key="pets_policy", applicability=None)
    run = state(
        result("https://one.test", "one", [first]),
        result("https://two.test", "two", [second]),
    )
    run.official_source_url = "https://official.test"
    run.discovered_sources = []
    rubric = RubricCriterion(
        hunt_id=uuid4(),
        catalog_key="pets_policy",
        options=[],
        unknown_delta=-1,
    )
    out = asyncio.run(reconcile_stage(run, StageCtx(rubric=[rubric])))
    assert out.plan is not None
    assert out.plan.stages == [
        "RECONCILE",
        "FETCH",
        "EXTRACT",
        "VERIFY",
        "RECONCILE",
    ]
    assert out.plan.escalation is not None
    assert out.plan.escalation.rounds[0].kind == "official_arbiter"


def test_gate_dispute_defaults_to_unknown_on_answer() -> None:
    yes = claim("https://one.test", "in_unit", key="in_unit_laundry")
    no = claim("https://two.test", "none", key="in_unit_laundry")
    run = state(
        result("https://one.test", "one", [yes]),
        result("https://two.test", "two", [no]),
    )
    rubric = RubricCriterion(
        hunt_id=uuid4(),
        catalog_key="in_unit_laundry",
        options=[
            RubricOption(match=OptionMatch(op=MatchOp.EQ, value="in_unit"), delta=0),
        ],
        non_negotiable=NonNegotiable(set_score=-10),
    )
    with pytest.raises(CheckpointRaised) as raised:
        asyncio.run(reconcile_stage(run, StageCtx(rubric=[rubric])))
    assert raised.value.prompt.default == "Leave unknown"
    run.checkpoint_answer = {"choice": "Leave unknown"}
    out = asyncio.run(reconcile_stage(run, StageCtx(rubric=[rubric])))
    assert out.resolved_claims[-1].value is None
    assert out.resolved_claims[-1].resolution_rule == "dispute_left_unknown"
