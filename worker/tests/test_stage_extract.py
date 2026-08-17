"""P0-8: EXTRACT stage — full-catalog extraction, provenance stamping, and the
§10.2 P1 rule: one corrective retry on validation failure, then job error."""

from __future__ import annotations

import asyncio

import pytest
from manzil_shared.errors import ExtractionInvalid
from manzil_shared.models import Confidence
from manzil_worker.fetching.cleaner import clean_html
from manzil_worker.llm.client import StructuredValidationError
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.extract import extract_stage
from manzil_worker.stages.schema_gen import build_extraction_schema, extractable_entries
from manzil_worker.state import SourceClaim, SourceState
from pydantic import ValidationError
from worker_helpers import (
    PAGES,
    FakeLLM,
    extraction_payload,
    field_payload,
    get_claim,
    make_state,
    maple_extraction,
    scoped_claim_payload,
)

CLEANED = clean_html((PAGES / "e2e_listing.html").read_text()).text


def test_extract_isolates_each_source_and_mirrors_submitted_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = make_state(cleaned_text="submitted body")
    state.sources.append(
        SourceState(
            url="https://sibling.example/property",
            cleaned_text="sibling body",
            cleaned_hash="sibling",
        )
    )

    async def fake_extract_single(source_state, ctx):  # type: ignore[no-untyped-def]
        source = source_state.sources[0]
        source_state.source_claims = [
            SourceClaim(
                criterion_key="pool",
                value=source.url,
                confidence=Confidence.HIGH,
                source_id=source.url,
                model="fixture",
                prompt_version=1,
            )
        ]
        return source_state

    monkeypatch.setattr("manzil_worker.stages.extract._extract_single", fake_extract_single)
    out = asyncio.run(extract_stage(state, StageCtx()))

    assert [result.source_url for result in out.source_results] == [
        state.url,
        "https://sibling.example/property",
    ]
    assert [result.source_claims[0].value for result in out.source_results] == [
        state.url,
        "https://sibling.example/property",
    ]
    assert out.source_claims[0].value == state.url
    assert all(source.authoritative_extraction for source in out.sources)


def test_extract_populates_every_criterion_with_provenance() -> None:
    llm = FakeLLM({"extract": maple_extraction()})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert {claim.criterion_key for claim in state.source_claims} == {
        e.key for e in extractable_entries()
    } - {
        "private_entry",
        "walk_in_closets",
        "pantry",
        "disposal",
        "fireplace",
        "ceiling_fans",
        "stainless_steel_appliances",
        "flooring_materials",
        "is_renovated",
    }
    assert not any(claim.criterion_key == "beds" for claim in state.source_claims)
    assert not any(claim.criterion_key == "sqft" for claim in state.source_claims)
    assert not any(claim.criterion_key == "private_entry" for claim in state.source_claims)
    assert [(p.plan_name, p.beds, p.sqft_min) for p in state.floor_plans] == [("The Maple", 2, 950)]


def test_extract_lands_property_identity_when_present() -> None:
    llm = FakeLLM({"extract": maple_extraction()})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert state.property_identity is not None
    assert state.property_identity.name == "Maple Court Apartments"
    assert state.property_identity.address == "120 Maple Court Dr, Detroit, MI 48187"
    assert state.property_identity.official_url is None


def test_extract_preserves_property_facts_and_floor_plan_unit_types() -> None:
    payload = maple_extraction()
    payload["pool"] = field_payload("outdoor", "Outdoor swimming pool")
    payload["property_types"] = field_payload(["apartment"], "Apartment homes")
    payload["floor_plans"][0]["unit_types"] = ["loft"]
    state = asyncio.run(
        extract_stage(
            make_state(cleaned_text=CLEANED),
            StageCtx(call_structured=FakeLLM({"extract": payload})),
        )
    )

    pool = get_claim(state, "pool")
    assert pool.value == "outdoor"
    assert pool.applicability is None
    assert not any(claim.criterion_key == "unit_types" for claim in state.source_claims)
    assert state.floor_plans[0].unit_types == ["loft"]


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
    bad = extraction_payload(pool=field_payload("not-a-pool"))
    llm = FakeLLM({"extract": [bad, maple_extraction()]})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert state.floor_plans[0].beds == 2
    assert len(llm.calls) == 2
    retry_content = llm.calls[1][1]
    assert "failed schema validation" in retry_content
    assert "pool" in retry_content  # the validation error travels back to the model


def test_corrective_retry_includes_the_invalid_scoped_claim_fragment() -> None:
    repeated = scoped_claim_payload(True, "Renovated kitchen") * 2
    bad = extraction_payload(is_renovated=repeated)
    schema = build_extraction_schema()
    with pytest.raises(ValidationError) as raised:
        schema.model_validate(bad)
    invalid = StructuredValidationError(raised.value, bad)
    calls: list[str] = []

    async def retrying_llm(stage, response_schema, content):  # type: ignore[no-untyped-def]
        assert stage == "extract"
        calls.append(content)
        if len(calls) == 1:
            raise invalid
        return response_schema.model_validate(maple_extraction())

    state = asyncio.run(
        extract_stage(make_state(cleaned_text=CLEANED), StageCtx(call_structured=retrying_llm))
    )

    assert state.floor_plans[0].beds == 2
    assert len(calls) == 2
    assert '"is_renovated"' in calls[1]
    assert calls[1].index("invalid portion") < calls[1].index("URL:")


def test_conflicting_laundry_none_and_on_site_canonicalizes_to_positive() -> None:
    """Rent.com can state both "no in-unit" and shared laundry. `none` means no
    laundry at all, so the redundant negative must not fail the Job or persist
    beside the explicitly supported positive for one Property target."""
    none = {
        "value": "none",
        "confidence": "high",
        "evidence_quote": "In-unit laundry is not available.",
        "applicability": "all_units",
        "floor_plan_refs": [],
    }
    on_site = {
        "value": "on_site",
        "confidence": "high",
        "evidence_quote": "laundry facility located in each building",
        "applicability": "unit_scope_unspecified",
        "floor_plan_refs": [],
    }
    bad = extraction_payload(in_unit_laundry=[none, on_site])
    llm = FakeLLM({"extract": bad})

    state = asyncio.run(
        extract_stage(
            make_state(
                cleaned_text=(
                    "In-unit laundry is not available. Residents have a laundry "
                    "facility located in each building."
                )
            ),
            StageCtx(call_structured=llm),
        )
    )

    laundry = get_claim(state, "in_unit_laundry")
    assert laundry.value == "on_site"
    assert laundry.applicability == "unit_scope_unspecified"
    assert len(llm.calls) == 1


def test_second_invalid_response_is_a_job_error_not_a_retry() -> None:
    bad = extraction_payload(pool=field_payload("not-a-pool"))
    llm = FakeLLM({"extract": [bad, bad]})
    state = make_state(cleaned_text=CLEANED)
    with pytest.raises(ExtractionInvalid, match="twice"):
        asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))
    assert len(llm.calls) == 2


def test_available_now_sentinel_rewrites_to_run_date() -> None:
    """Immediate-availability phrasing rewrites Floor Plan dates to ctx.today
    before VERIFY."""
    from datetime import date

    from manzil_worker.stages.extract import AVAILABLE_NOW_SENTINEL

    quote = "Available Now"
    payload = maple_extraction()
    payload["floor_plans"][0]["availability_date"] = AVAILABLE_NOW_SENTINEL
    payload["floor_plans"][0]["evidence_quote"] = quote
    llm = FakeLLM({"extract": payload})
    state = make_state(cleaned_text=CLEANED)
    frozen = date(2026, 7, 16)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm, today=lambda: frozen)))

    assert state.floor_plans[0].availability_date == "2026-07-16"
    assert state.floor_plans[0].evidence_quote == quote


def test_iso_availability_date_is_left_untouched() -> None:
    llm = FakeLLM({"extract": maple_extraction()})
    state = make_state(cleaned_text=CLEANED)
    from datetime import date

    state = asyncio.run(
        extract_stage(state, StageCtx(call_structured=llm, today=lambda: date(2026, 7, 16)))
    )

    assert state.floor_plans[0].availability_date == "2026-08-01"


def test_extract_lands_p39_fee_and_heating_blocks() -> None:
    # §9.5 P3-9: optional-with-default blocks — present when the model emits
    # them, None on older recordings that predate them.
    payload = maple_extraction()
    payload["mandatory_fees"] = {
        "fees": [{"name": "valet trash", "amount_monthly": 25.0}],
        "evidence_quote": "Valet trash $25/mo",
    }
    payload["heating"] = [
        {
            "value": "gas",
            "confidence": "high",
            "evidence_quote": "gas forced-air heat",
            "applicability": "specific_floor_plans",
            "floor_plan_refs": ["the-maple"],
        }
    ]
    llm = FakeLLM({"extract": payload})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert state.mandatory_fees is not None
    assert state.mandatory_fees.fees[0].name == "valet trash"
    assert state.mandatory_fees.fees[0].amount_monthly == 25.0
    heating = get_claim(state, "heating_type")
    assert heating.value == "gas"
    assert heating.floor_plan_ref == "the-maple"
    assert heating.applicability == "specific_floor_plans"


def test_extract_expands_one_claim_across_several_floor_plans() -> None:
    payload = extraction_payload(
        floor_plans=[
            {"response_key": "a1", "plan_name": "A1"},
            {"response_key": "a2", "plan_name": "A2"},
        ],
        dishwasher=scoped_claim_payload(
            True,
            "A1 and A2 include dishwashers",
            applicability="specific_floor_plans",
            floor_plan_refs=["a1", "a2"],
        ),
    )
    state = asyncio.run(
        extract_stage(
            make_state(cleaned_text="A1 and A2 include dishwashers"),
            StageCtx(call_structured=FakeLLM({"extract": payload})),
        )
    )
    claims = [claim for claim in state.source_claims if claim.criterion_key == "dishwasher"]
    assert [claim.floor_plan_ref for claim in claims] == ["a1", "a2"]
    assert len({claim.claim_group_id for claim in claims}) == 1


def test_extract_preserves_multiple_parking_values_and_variants() -> None:
    payload = extraction_payload(
        parking=[
            {
                "value": "carport",
                "confidence": "high",
                "evidence_quote": "Covered Parking: Carport",
                "applicability": "all_units",
                "floor_plan_refs": [],
            },
            {
                "value": "garage",
                "confidence": "high",
                "evidence_quote": "Attached Garages (in Select Townhomes)",
                "applicability": "select_units",
                "floor_plan_refs": [],
            },
        ]
    )
    state = asyncio.run(
        extract_stage(
            make_state(cleaned_text="Carport. Attached garages in select townhomes."),
            StageCtx(call_structured=FakeLLM({"extract": payload})),
        )
    )

    parking = [claim for claim in state.source_claims if claim.criterion_key == "parking"]
    assert [(claim.value, claim.applicability, claim.claim_variant) for claim in parking] == [
        ("carport", "all_units", "carport"),
        ("garage", "select_units", "garage"),
    ]


def test_extract_lands_sc6_presence_and_sc7_material_claims_without_a_side_path() -> None:
    payload = extraction_payload(
        floor_plans=[{"response_key": "a1", "plan_name": "A1"}],
        fireplace=scoped_claim_payload(
            True,
            "A1 includes a fireplace",
            applicability="specific_floor_plans",
            floor_plan_refs=["a1"],
        ),
        flooring_materials=scoped_claim_payload(
            ["hardwood", "tile"],
            "Hardwood living areas and tile bath",
            applicability="all_units",
        ),
    )
    state = asyncio.run(
        extract_stage(
            make_state(cleaned_text="A1 includes a fireplace. Hardwood and tile throughout."),
            StageCtx(call_structured=FakeLLM({"extract": payload})),
        )
    )

    fireplace = get_claim(state, "fireplace")
    assert fireplace.floor_plan_ref == "a1"
    assert fireplace.applicability == "specific_floor_plans"
    materials = get_claim(state, "flooring_materials")
    assert materials.value == ["hardwood", "tile"]
    assert materials.target_scope == "property"
    assert materials.applicability == "all_units"


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


# ── P3-21: property contact block ─────────────────────────────────────────────


def test_property_contact_block_projects_onto_state() -> None:
    """Rungs 1 and 3 share one schema block; provenance is decided at persist
    time from the Source's is_official flag, not here."""
    llm = FakeLLM(
        {
            "extract": extraction_payload(
                property_contact={
                    "phone": "(313) 555-0142",
                    "contact_url": "https://maplecourt.test/contact",
                    "evidence_quote": "Call our leasing office at (313) 555-0142",
                }
            )
        }
    )
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert state.property_contact is not None
    assert state.property_contact.phone == "(313) 555-0142"
    assert state.property_contact.contact_url == "https://maplecourt.test/contact"


def test_property_contact_block_is_optional() -> None:
    """Absent on pre-P3-21 recordings and on pages with no published contact —
    both must validate and leave the block unset."""
    llm = FakeLLM({"extract": extraction_payload()})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert state.property_contact is None


def test_property_contact_never_becomes_a_scored_claim() -> None:
    """§16/§8.2: contact info is unscored display metadata. It must not appear in
    source_claims, which is the path into the scoring engine."""
    llm = FakeLLM({"extract": extraction_payload(property_contact={"phone": "(313) 555-0142"})})
    state = make_state(cleaned_text=CLEANED)
    state = asyncio.run(extract_stage(state, StageCtx(call_structured=llm)))

    assert not any(c.criterion_key == "property_contact" for c in state.source_claims)


def test_property_contact_schema_has_no_person_field() -> None:
    """§16 PII control by construction: the block cannot carry an agent's name or
    role, so a named individual's identity has nowhere to land."""
    from manzil_worker.state import PropertyContactIn

    assert set(PropertyContactIn.model_fields) == {"phone", "contact_url", "evidence_quote"}
