"""P0-8 gate: non-listing corpus page rejected by VALIDATE (heuristics first,
LLM to confirm)."""

from __future__ import annotations

import asyncio

import pytest
from manzil_shared.errors import StageFatal
from manzil_worker.fetching.cleaner import clean_html
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.validate import validate_stage
from worker_helpers import PAGES, FakeLLM, make_state


def _cleaned(fixture: str) -> str:
    return clean_html((PAGES / fixture).read_text()).text


def test_article_page_rejected_by_heuristics_without_llm() -> None:
    llm = FakeLLM({})  # any LLM call would KeyError — none may happen
    state = make_state(cleaned_text=_cleaned("not_listing_article.html"))
    with pytest.raises(StageFatal, match=r"not a listing.*heuristic"):
        asyncio.run(validate_stage(state, StageCtx(call_structured=llm)))
    assert llm.calls == []


def test_thin_page_rejected_by_heuristics_without_llm() -> None:
    llm = FakeLLM({})
    state = make_state(cleaned_text="2 bed apartment $1,200")  # signal but far too short
    with pytest.raises(StageFatal, match="below minimum"):
        asyncio.run(validate_stage(state, StageCtx(call_structured=llm)))
    assert llm.calls == []


def test_listing_page_confirmed_by_llm_passes() -> None:
    llm = FakeLLM(
        {
            "validate": {
                "is_listing": True,
                "property_name": "Maple Court Apartments",
                "reason": "advertises one property's floor plans and rent",
            }
        }
    )
    state = make_state(cleaned_text=_cleaned("e2e_listing.html"))
    result = asyncio.run(validate_stage(state, StageCtx(call_structured=llm)))
    assert result is state
    assert len(llm.calls) == 1
    assert llm.calls[0][0] == "validate"


def test_llm_verdict_not_listing_is_fatal() -> None:
    llm = FakeLLM(
        {
            "validate": {
                "is_listing": False,
                "property_name": None,
                "reason": "search results page listing many properties",
            }
        }
    )
    state = make_state(cleaned_text=_cleaned("e2e_listing.html"))
    with pytest.raises(StageFatal, match="search results page"):
        asyncio.run(validate_stage(state, StageCtx(call_structured=llm)))
