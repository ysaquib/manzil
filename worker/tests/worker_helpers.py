"""Shared worker-test helpers: fake fetcher/LLM, state builders, and the
full-catalog extraction payload used by P0-8/9/10 stage tests. Lives outside
conftest.py because test modules import these by name, and bare `conftest`
imports collide across suites in a root-level pytest run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from manzil_shared.models import Confidence, FetchOutcome, JobType
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


async def seed_recorded_llm(stage: str, schema: type[Any], content: str) -> Any:
    """Pin seed EXTRACT outputs while replaying every other LLM stage."""
    if stage != "extract":
        return await call_structured(stage, schema, content)
    filename = next(
        name for url, name in _SEED_EXTRACT_RECORDINGS.items() if f"URL: {url}" in content
    )
    recording = json.loads((RECORDED / filename).read_text())
    return schema.model_validate(recording["output"])


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


def extraction_payload(**overrides: dict[str, Any]) -> dict[str, Any]:
    """A full ListingExtraction payload: everything not_found unless overridden."""
    payload: dict[str, Any] = {
        entry.key: {"value": None, "confidence": "not_found", "evidence_quote": None}
        for entry in extractable_entries()
    }
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
        patio_balcony=field_payload(True, "Private balcony or ground-floor patio"),
        in_unit_laundry=field_payload("in_unit", "Full-size washer and dryer in every home"),
        pets_policy=field_payload("cats_and_dogs", "Cats and small dogs welcome!"),
        security_deposit=field_payload(500.0, "Security deposit | $500 with approved credit"),
        availability_date=field_payload("2026-08-01", "Available August 1, 2026"),
        parking=field_payload("dedicated_lot", "Dedicated parking lot with one assigned space"),
        cooling=field_payload("central", "Central air conditioning and forced-air heating"),
        dishwasher=field_payload(True, "Dishwasher, garbage disposal"),
        min_lease_months=field_payload(12, "Minimum lease term | 12 months"),
    )
    payload["property_identity"] = {
        "name": "Maple Court Apartments",
        "address": "120 Maple Court Dr, Detroit, MI 48201",
        "official_url": None,  # the page names no official website
    }
    payload["floor_plans"] = [
        {
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


def set_claim(state: RunState, key: str, extraction: SourceClaim) -> None:
    extraction.criterion_key = key
    state.source_claims = [claim for claim in state.source_claims if claim.criterion_key != key]
    state.source_claims.append(extraction)


def get_claim(state: RunState, key: str) -> SourceClaim:
    return next(claim for claim in state.source_claims if claim.criterion_key == key)
