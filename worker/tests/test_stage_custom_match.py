"""P3-10 CUSTOM_MATCH acquisition and evidence-boundary tests."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from manzil_shared.errors import StageRetryable
from manzil_shared.models import (
    CustomCriterionDef,
    JobType,
    MatchOp,
    OptionMatch,
    RefreshClass,
    RubricCriterion,
    RubricOption,
    TargetScope,
)
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.custom_match import custom_match_stage
from manzil_worker.state import FloorPlanIn, RunState, SourceState
from worker_helpers import FakeLLM

URL = "https://maplecourt.test/floorplans"


def _criterion(*, scope: str = "property") -> RubricCriterion:
    return RubricCriterion(
        hunt_id=uuid4(),
        custom_def=CustomCriterionDef(
            key=f"custom:{uuid4()}",
            label="Quiet hours",
            description="Whether the listing states quiet hours.",
            fact_scope=scope,
            value_schema={"type": "boolean"},
            refresh_class=RefreshClass.LISTING_DETAILS,
            routing_confirmed=True,
        ),
        options=[
            RubricOption(
                match=OptionMatch(op=MatchOp.BOOL, value=True),
                delta=1,
            )
        ],
    )


def _state() -> RunState:
    return RunState(
        job_id=uuid4(),
        job_type=JobType.INGEST,
        url=URL,
        sources=[
            SourceState(
                url=URL,
                cleaned_text="Community quiet hours run from 10 PM to 7 AM.",
            )
        ],
    )


def test_text_custom_match_requires_verbatim_evidence() -> None:
    criterion = _criterion()
    llm = FakeLLM(
        {
            "custom_match": {
                "results": [
                    {
                        "target": "property",
                        "value": True,
                        "confidence": "high",
                        "source_url": URL,
                        "evidence_quote": "quiet hours run from 10 PM to 7 AM",
                    }
                ]
            }
        }
    )

    out = asyncio.run(
        custom_match_stage(_state(), StageCtx(rubric=[criterion], call_structured=llm))
    )

    assert len(out.custom_claims) == 1
    claim = out.custom_claims[0]
    assert claim.criterion_key == criterion.custom_def.key
    assert claim.value is True
    assert claim.target_scope is TargetScope.PROPERTY
    assert claim.source_id == URL


def test_floor_plan_custom_match_is_source_local() -> None:
    criterion = _criterion(scope="floor_plan")
    state = _state()
    state.floor_plans = [
        FloorPlanIn(response_key="a1", source_url=URL, plan_name="A1"),
    ]
    state.sources.append(
        SourceState(
            url="https://other.test/a1",
            cleaned_text="Community quiet hours run from 10 PM to 7 AM.",
        )
    )
    llm = FakeLLM(
        {
            "custom_match": {
                "results": [
                    {
                        "target": f"{URL}#a1",
                        "value": True,
                        "confidence": "high",
                        "source_url": "https://other.test/a1",
                        "evidence_quote": "quiet hours run from 10 PM to 7 AM",
                    }
                ]
            }
        }
    )

    with pytest.raises(StageRetryable, match="Source-local"):
        asyncio.run(custom_match_stage(state, StageCtx(rubric=[criterion], call_structured=llm)))


def test_custom_match_rejects_values_outside_the_author_schema() -> None:
    criterion = _criterion()
    llm = FakeLLM(
        {
            "custom_match": {
                "results": [
                    {
                        "target": "property",
                        "value": "yes",
                        "confidence": "high",
                        "source_url": URL,
                        "evidence_quote": "quiet hours run from 10 PM to 7 AM",
                    }
                ]
            }
        }
    )

    with pytest.raises(StageRetryable, match="violates its schema"):
        asyncio.run(custom_match_stage(_state(), StageCtx(rubric=[criterion], call_structured=llm)))
