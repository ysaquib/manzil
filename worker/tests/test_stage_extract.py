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
    get_claim,
    make_state,
    maple_extraction,
)

CLEANED = clean_html((PAGES / "e2e_listing.html").read_text()).text


def test_extract_populates_every_criterion_with_provenance() -> None:
    llm = FakeLLM({"extract": maple_extraction()})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert {claim.criterion_key for claim in state.source_claims} == {
        e.key for e in extractable_entries()
    }
    beds = get_claim(state, "beds")
    assert beds.value == 2
    assert beds.source_id == state.sources[0].url
    assert beds.model == model_for_stage("extract")
    from manzil_worker.llm.prompt_loader import load_prompt

    assert beds.prompt_version == load_prompt("extract").version  # provenance, not a pin
    unknown = get_claim(state, "private_entry")
    assert unknown.value is None
    assert unknown.confidence == "not_found"
    assert [p.plan_name for p in state.floor_plans] == ["The Maple"]


def test_extract_lands_property_identity_when_present() -> None:
    llm = FakeLLM({"extract": maple_extraction()})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert state.property_identity is not None
    assert state.property_identity.name == "Maple Court Apartments"
    assert state.property_identity.address == "120 Maple Court Dr, Detroit, MI 48201"
    assert state.property_identity.official_url is None


def test_extract_leaves_property_identity_none_when_block_absent() -> None:
    """The identity block is optional — a payload without it leaves state.property_identity
    None, so recorded fixtures predating the block keep working."""
    llm = FakeLLM({"extract": extraction_payload()})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert state.property_identity is None


def test_extract_lands_pet_costs_and_utilities_when_present() -> None:
    payload = maple_extraction()
    payload["pet_costs"] = {
        "cat_rent_monthly": 20.0,
        "dog_rent_monthly": 35.0,
        "pet_rent_monthly": None,
        "evidence_quote": "Cat rent $20/mo, dog rent $35/mo",
    }
    payload["utilities"] = {
        "included": ["water", "trash"],
        "evidence_quote": "Water & trash included",
    }
    llm = FakeLLM({"extract": payload})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert state.pet_costs is not None
    assert state.pet_costs.cat_rent_monthly == 20.0
    assert state.pet_costs.dog_rent_monthly == 35.0
    assert state.pet_costs.pet_rent_monthly is None
    assert state.utilities is not None
    assert state.utilities.included == ["water", "trash"]


def test_extract_leaves_pet_costs_and_utilities_none_when_absent() -> None:
    """Both §9.5 blocks are optional — a payload without them leaves the RunState
    fields None so recorded fixtures predating the blocks keep working."""
    llm = FakeLLM({"extract": extraction_payload()})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert state.pet_costs is None
    assert state.utilities is None


def test_invalid_first_response_gets_one_corrective_retry() -> None:
    bad = extraction_payload(beds=field_payload("two"))  # not an integer
    llm = FakeLLM({"extract": [bad, maple_extraction()]})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert get_claim(state, "beds").value == 2
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


def test_available_now_sentinel_rewrites_to_run_date() -> None:
    """Immediate-availability phrasing extracts as available_now; EXTRACT
    rewrites criterion + floor-plan dates to ctx.today before VERIFY."""
    from datetime import date

    from manzil_worker.stages.extract import AVAILABLE_NOW_SENTINEL

    quote = "Available Now"
    payload = maple_extraction()
    payload["availability_date"] = field_payload(AVAILABLE_NOW_SENTINEL, quote)
    payload["floor_plans"][0]["availability_date"] = AVAILABLE_NOW_SENTINEL
    payload["floor_plans"][0]["evidence_quote"] = quote
    llm = FakeLLM({"extract": payload})
    state = make_state(cleaned_text=CLEANED)
    frozen = date(2026, 7, 16)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm, today=lambda: frozen)))

    assert get_claim(state, "availability_date").value == "2026-07-16"
    assert get_claim(state, "availability_date").evidence_quote == quote
    assert state.floor_plans[0].availability_date == "2026-07-16"
    assert state.floor_plans[0].evidence_quote == quote


def test_iso_availability_date_is_left_untouched() -> None:
    llm = FakeLLM({"extract": maple_extraction()})
    state = make_state(cleaned_text=CLEANED)
    from datetime import date

    state = asyncio.run(
        extract_stage(state, StageCtx(call_structured=llm, today=lambda: date(2026, 7, 16)))
    )

    assert get_claim(state, "availability_date").value == "2026-08-01"
    assert state.floor_plans[0].availability_date == "2026-08-01"


def test_extract_lands_p39_fee_and_heating_blocks() -> None:
    # §9.5 P3-9: optional-with-default blocks — present when the model emits
    # them, None on older recordings that predate them.
    payload = maple_extraction()
    payload["mandatory_fees"] = {
        "fees": [{"name": "valet trash", "amount_monthly": 25.0}],
        "evidence_quote": "Valet trash $25/mo",
    }
    payload["heating"] = {"heating": "gas", "evidence_quote": "gas forced-air heat"}
    llm = FakeLLM({"extract": payload})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert state.mandatory_fees is not None
    assert state.mandatory_fees.fees[0].name == "valet trash"
    assert state.mandatory_fees.fees[0].amount_monthly == 25.0
    assert state.heating is not None and state.heating.heating == "gas"


def test_extract_blocks_absent_stay_none() -> None:
    llm = FakeLLM({"extract": maple_extraction()})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))
    assert state.mandatory_fees is None
    assert state.heating is None
    assert state.one_time_fees is None


def test_extract_lands_one_time_fees_block() -> None:
    # §9.5 one-time fees (§20 2026-07-18): move-in costs with a payment basis,
    # optional-with-default like the other blocks.
    payload = maple_extraction()
    payload["one_time_fees"] = {
        "fees": [
            {"name": "application fee", "amount": 50.0, "basis": "per_person"},
            {"name": "admin fee", "amount": 150.0, "basis": "per_application"},
            {"name": "pet deposit", "amount": 300.0, "basis": "per_pet", "refundable": True},
        ],
        "evidence_quote": "App fee $50/applicant; $150 admin; $300 refundable pet deposit",
    }
    llm = FakeLLM({"extract": payload})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert state.one_time_fees is not None
    fees = state.one_time_fees.fees
    assert [(f.name, f.amount, f.basis) for f in fees] == [
        ("application fee", 50.0, "per_person"),
        ("admin fee", 150.0, "per_application"),
        ("pet deposit", 300.0, "per_pet"),
    ]
    assert fees[2].refundable is True
    assert fees[0].refundable is None  # page silent → never invented
