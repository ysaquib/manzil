"""Shared worker-test helpers: fake fetcher/LLM, state builders, and the
full-catalog extraction payload used by P0-8/9/10 stage tests. Lives outside
conftest.py because test modules import these by name, and bare `conftest`
imports collide across suites in a root-level pytest run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from manzil_shared.catalog import SCOPED_UNIT_CLAIM_KEYS
from manzil_shared.models import (
    Confidence,
    FetchOutcome,
    JobType,
    TargetScope,
    UnitApplicability,
)
from manzil_worker.fetching.results import FetchResult
from manzil_worker.llm.client import call_structured
from manzil_worker.llm.tools import AgentResult
from manzil_worker.stages.schema_gen import extractable_entries
from manzil_worker.state import RunState, SourceClaim, SourceState

PAGES = Path(__file__).parent / "fixtures" / "pages"
RECORDED = Path(__file__).parent / "fixtures" / "recorded"

_SEED_EXTRACT_RECORDINGS = {
    "https://maple-court.seed.example/floorplans": "extract--5c2ab4abc7ec5991.json",
    "https://oakwood.seed.example/apartments": "extract--e4eff37208aec8e0.json",
    "https://willow-bend.seed.example/apartments": "extract--2ffad86017282b67.json",
}

# VALIDATE fixtures are hash-keyed to cleaned page text. Keep the committed
# filenames here so a cleaner drift fails the seed guard test at the desk.
_SEED_VALIDATE_RECORDINGS = (
    "validate--00b35a7d16a02e88.json",  # e2e_listing.html (Maple Court)
    "validate--5597dcd9cd5fa47a.json",  # success_text.html (Birch Run)
    "validate--01e1247a25586880.json",  # injection_listing.html (Willow Bend)
)

_SEED_VALIDATE_BY_NAME = {
    "Maple Court Apartments": {
        "is_listing": True,
        "property_name": "Maple Court Apartments",
        "reason": (
            "This page advertises one named apartment community with a specific "
            "two-bedroom floor plan, rent, availability date, amenities, and leasing terms."
        ),
    },
    "Birch Run Apartments": {
        "is_listing": True,
        "property_name": "Birch Run Apartments",
        "reason": (
            "It advertises one named apartment property with a specific rent, "
            "address, unit details, and amenities."
        ),
    },
    "Willow Bend Flats": {
        "is_listing": True,
        "property_name": "Willow Bend Flats",
        "reason": (
            "This page advertises one named apartment property with a specific "
            "unit type, rent, availability, and amenities."
        ),
    },
}


async def seed_recorded_llm(stage: str, schema: type[Any], content: str) -> Any:
    """Pin legacy seed VALIDATE/EXTRACT/VERIFY outputs at the synthetic-test seam."""
    if stage == "validate":
        # Same rationale as VERIFY below: keep the three synthetic pages
        # deterministic for DB/queue coverage. `scripts/dev_seed.py` without an
        # override still replays the committed hash-keyed VALIDATE fixtures.
        for name, payload in _SEED_VALIDATE_BY_NAME.items():
            if name in content:
                return schema.model_validate(payload)
        return await call_structured(stage, schema, content)
    if stage == "verify":
        # Adding Catalog fields changes the serialized VERIFY input and therefore
        # its recording hash even though the three synthetic seed pages remain
        # internally consistent. Keep this fixture deterministic until P3-SC4
        # replaces the legacy recordings with its human-labeled scoped corpus.
        return schema.model_validate({"contradictions": []})
    if stage != "extract":
        return await call_structured(stage, schema, content)
    filename = next(
        name for url, name in _SEED_EXTRACT_RECORDINGS.items() if f"URL: {url}" in content
    )
    recording = json.loads((RECORDED / filename).read_text())
    output = dict(recording["output"])
    # The three P1 dev-seed recordings predate the P3-SC3 Property tranche.
    # Adapt only this deterministic legacy seed boundary with explicit
    # not_found wrappers; production EXTRACT and new recordings still require
    # every Catalog field from the generated schema. P3-SC4 owns the canonical
    # scoped bench/recording refresh after its human labels are complete.
    for entry in extractable_entries():
        if entry.key in SCOPED_UNIT_CLAIM_KEYS:
            legacy = output.get(entry.key)
            if isinstance(legacy, dict) and legacy.get("value") is not None:
                output[entry.key] = [
                    {
                        **legacy,
                        "applicability": (
                            "all_units"
                            if entry.key == "in_unit_laundry"
                            else "unit_scope_unspecified"
                        ),
                        "floor_plan_refs": [],
                    }
                ]
            else:
                output[entry.key] = []
        else:
            output.setdefault(
                entry.key,
                {"value": None, "confidence": "not_found", "evidence_quote": None},
            )
    legacy_heating = output.get("heating")
    if isinstance(legacy_heating, dict) and legacy_heating.get("heating") is not None:
        output["heating"] = [
            {
                "value": legacy_heating["heating"],
                "confidence": "high",
                "evidence_quote": legacy_heating.get("evidence_quote") or "",
                "applicability": "unit_scope_unspecified",
                "floor_plan_refs": [],
            }
        ]
    else:
        output["heating"] = []
    return schema.model_validate(output)


class FakeFetcher:
    def __init__(self, tier: int, body: str, status: int = 200) -> None:
        self.tier = tier
        self._body = body
        self._status = status

    async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
        return FetchResult(
            url=url, final_url=url, status_code=self._status, body=self._body, tier=self.tier
        )


class FakeLLM:
    """Stands in for the seam's call_structured. Handlers map stage -> payload
    dict (returned every call) or list of payloads (consumed in order).
    Payloads run through the real schema, exactly like the seam."""

    def __init__(self, handlers: dict[str, Any]) -> None:
        self.handlers = handlers
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, stage: str, schema: type[Any], content: str) -> Any:
        self.calls.append((stage, content))
        handler = self.handlers[stage]
        payload = handler.pop(0) if isinstance(handler, list) else handler
        return schema.model_validate(payload)


async def empty_discovery_agent(stage, task, tools, max_turns):  # type: ignore[no-untyped-def]
    """Deterministic no-sibling DISCOVER result for non-DISCOVER integration tests."""
    assert stage == "discover"
    return AgentResult(final_text='{"candidates": []}', turns=1)


def field_payload(value: Any, quote: str | None = None, confidence: str = "high") -> dict[str, Any]:
    return {"value": value, "confidence": confidence, "evidence_quote": quote}


def scoped_claim_payload(
    value: Any,
    quote: str,
    *,
    applicability: str = "unit_scope_unspecified",
    floor_plan_refs: list[str] | None = None,
    confidence: str = "high",
) -> list[dict[str, Any]]:
    return [
        {
            "value": value,
            "confidence": confidence,
            "evidence_quote": quote,
            "applicability": applicability,
            "floor_plan_refs": floor_plan_refs or [],
        }
    ]


def extraction_payload(**overrides: dict[str, Any]) -> dict[str, Any]:
    """A full ListingExtraction payload: everything not_found unless overridden."""
    payload: dict[str, Any] = {}
    for entry in extractable_entries():
        payload[entry.key] = (
            []
            if entry.key in SCOPED_UNIT_CLAIM_KEYS
            else {"value": None, "confidence": "not_found", "evidence_quote": None}
        )
    payload["floor_plans"] = []
    payload.update(overrides)
    return payload


def maple_extraction() -> dict[str, Any]:
    """Ground truth for fixtures/pages/e2e_listing.html — every evidence quote
    is verbatim from the page so VERIFY passes with zero flags."""
    payload = extraction_payload(
        beds=field_payload(2, "2 bedroom, 1.5 bathroom apartment home"),
        baths=field_payload(1.5, "2 bedroom, 1.5 bathroom apartment home"),
        sqft=field_payload(950, "950 square feet of thoughtfully designed living space"),
        patio_balcony=scoped_claim_payload(
            True,
            "Private balcony or ground-floor patio",
        ),
        in_unit_laundry=scoped_claim_payload(
            "in_unit",
            "Full-size washer and dryer in every home",
            applicability="all_units",
        ),
        pets_policy=field_payload("cats_and_dogs", "Cats and small dogs welcome!"),
        security_deposit=field_payload(500.0, "Security deposit | $500 with approved credit"),
        availability_date=field_payload("2026-08-01", "Available August 1, 2026"),
        parking=scoped_claim_payload(
            "dedicated_lot", "Dedicated parking lot with one assigned space"
        ),
        cooling=scoped_claim_payload("central", "Central air conditioning and forced-air heating"),
        dishwasher=scoped_claim_payload(True, "Dishwasher, garbage disposal"),
        min_lease_months=field_payload(12, "Minimum lease term | 12 months"),
    )
    payload["property_identity"] = {
        "name": "Maple Court Apartments",
        "address": "120 Maple Court Dr, Detroit, MI 48201",
        "official_url": None,  # the page names no official website
    }
    payload["floor_plans"] = [
        {
            "response_key": "the-maple",
            "plan_name": "The Maple",
            "beds": 2,
            "baths": 1.5,
            "sqft_min": 950,
            "rent_min": 1700.0,
            "rent_max": 1750.0,
            "deposit": 500.0,
            "availability_date": "2026-08-01",
            "evidence_quote": "Rent from $1,700 to $1,750 per month",
        }
    ]
    return payload


def make_state(url: str = "https://example.test/listing", cleaned_text: str = "") -> RunState:
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url=url)
    state.sources = [
        SourceState(url=url, tier_used=1, outcome=FetchOutcome.SUCCESS, cleaned_text=cleaned_text)
    ]
    return state


def fe(
    value: Any, quote: str | None = None, confidence: Confidence = Confidence.HIGH
) -> SourceClaim:
    return SourceClaim(
        criterion_key="",
        value=value,
        confidence=confidence,
        evidence_quote=quote,
        source_id="https://example.test/listing",
        model="test-model",
        prompt_version=1,
    )


def all_units_fe(
    value: Any, quote: str | None = None, confidence: Confidence = Confidence.HIGH
) -> SourceClaim:
    claim = fe(value, quote, confidence)
    claim.target_scope = TargetScope.PROPERTY
    claim.applicability = UnitApplicability.ALL_UNITS
    return claim


def set_claim(state: RunState, key: str, extraction: SourceClaim) -> None:
    extraction.criterion_key = key
    state.source_claims = [claim for claim in state.source_claims if claim.criterion_key != key]
    state.source_claims.append(extraction)


def get_claim(state: RunState, key: str) -> SourceClaim:
    return next(claim for claim in state.source_claims if claim.criterion_key == key)
