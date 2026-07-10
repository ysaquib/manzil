"""P0-8: EXTRACT stage — full-catalog extraction, provenance stamping, and the
§10.2 P1 rule: one corrective retry on validation failure, then job error."""

from __future__ import annotations

import asyncio

import pytest
from manzil_shared.errors import ExtractionInvalid
from manzil_worker.fetching.cleaner import clean_html
from manzil_worker.llm.config import model_for_stage
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.extract import extract_stage
from manzil_worker.stages.schema_gen import extractable_entries
from worker_helpers import (
    PAGES,
    FakeLLM,
    extraction_payload,
    field_payload,
    make_state,
    maple_extraction,
)

CLEANED = clean_html((PAGES / "e2e_listing.html").read_text()).text


def test_extract_populates_every_criterion_with_provenance() -> None:
    llm = FakeLLM({"extract": maple_extraction()})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert set(state.extractions) == {e.key for e in extractable_entries()}
    beds = state.extractions["beds"][0]
    assert beds.value == 2
    assert beds.source_id == state.sources[0].url
    assert beds.model == model_for_stage("extract")
    from manzil_worker.llm.prompt_loader import load_prompt

    assert beds.prompt_version == load_prompt("extract").version  # provenance, not a pin
    unknown = state.extractions["private_entry"][0]
    assert unknown.value is None
    assert unknown.confidence == "not_found"
    assert [p.plan_name for p in state.floor_plans] == ["The Maple"]


def test_invalid_first_response_gets_one_corrective_retry() -> None:
    bad = extraction_payload(beds=field_payload("two"))  # not an integer
    llm = FakeLLM({"extract": [bad, maple_extraction()]})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert state.extractions["beds"][0].value == 2
    assert len(llm.calls) == 2
    retry_content = llm.calls[1][1]
    assert "failed schema validation" in retry_content
    assert "beds" in retry_content  # the validation error travels back to the model


def test_second_invalid_response_is_a_job_error_not_a_retry() -> None:
    bad = extraction_payload(beds=field_payload("two"))
    llm = FakeLLM({"extract": [bad, bad]})
    state = make_state(cleaned_text=CLEANED)
    with pytest.raises(ExtractionInvalid, match="twice"):
        asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))
    assert len(llm.calls) == 2
