"""P1-14: VERIFY confirm_value checkpoint escalation and resume path."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from manzil_shared.errors import CheckpointRaised
from manzil_shared.models import CheckpointKind, Confidence
from manzil_worker.phase0_rubric import phase0_rubric
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.score import score_stage
from manzil_worker.stages.verify import verify_stage
from worker_helpers import FakeLLM, fe, get_claim, make_state, set_claim

TODAY = date(2026, 7, 6)
NO_CONTRADICTIONS = {"verify": {"contradictions": []}}
PAGE_TEXT = (
    "Two bedroom apartments with washer and dryer hookups in every unit. "
    "Rent starts at $1,500 per month. "
) * 5


def _ctx() -> StageCtx:
    return StageCtx(
        rubric=phase0_rubric(),
        min_confidence=Confidence.MEDIUM,
        call_structured=FakeLLM(NO_CONTRADICTIONS),
        today=lambda: TODAY,
    )


def test_gate_relevant_demotion_raises_confirm_value() -> None:
    state = make_state(cleaned_text=PAGE_TEXT)
    set_claim(state, "beds", fe(2, "this quote is not on the page at all"))

    with pytest.raises(CheckpointRaised) as raised:
        asyncio.run(verify_stage(state, _ctx()))

    prompt = raised.value.prompt
    assert prompt.kind is CheckpointKind.CONFIRM_VALUE
    assert prompt.context_ref == "beds"
    assert "yes" in prompt.options


def test_checkpoint_answer_yes_upgrades_confidence_for_score() -> None:
    state = make_state(cleaned_text=PAGE_TEXT)
    set_claim(state, "beds", fe(2, "this quote is not on the page at all"))
    set_claim(state, "in_unit_laundry", fe("in_unit", "washer and dryer hookups in every unit"))
    state.checkpoint_answer = {"choice": "yes", "context_ref": "beds"}

    asyncio.run(verify_stage(state, _ctx()))
    assert get_claim(state, "beds").confidence is Confidence.MEDIUM

    asyncio.run(score_stage(state, _ctx()))
    assert state.effective_values.get("beds") == 2


def test_checkpoint_answer_no_leaves_demoted() -> None:
    state = make_state(cleaned_text=PAGE_TEXT)
    set_claim(state, "beds", fe(2, "this quote is not on the page at all"))
    set_claim(state, "in_unit_laundry", fe("in_unit", "washer and dryer hookups in every unit"))
    state.checkpoint_answer = {"choice": "no", "context_ref": "beds"}

    asyncio.run(verify_stage(state, _ctx()))
    assert get_claim(state, "beds").confidence is Confidence.LOW
    assert "beds" in state.confirm_value_resolved
