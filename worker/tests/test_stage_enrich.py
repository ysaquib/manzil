"""P3-8: ENRICH stage — Maps-derived grocery proximity (honoring
`proximity_mode`), ratings stage 1 (Places rating + review synthesis), and the
`location_safety` placeholder (nothing emitted, §20 2026-07-18). All Maps seams
faked; the review synthesis goes through FakeLLM like every P1 call.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from manzil_shared.models import Confidence, JobType
from manzil_worker.enrich.maps import MapsError
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.enrich import enrich_stage
from manzil_worker.state import GeocodeIn, RunState
from worker_helpers import FakeLLM

PLACE_ID = "ChIJmaple"
GEOCODE = GeocodeIn(place_id=PLACE_ID, lat=42.30, lng=-83.05, formatted_address="123 Maple Ct")

KROGER = {"name": "Kroger", "place_id": "ChIJkroger", "lat": 42.31, "lng": -83.06}
DETAILS = {
    "name": "Maple Court Apartments",
    "rating": 4.2,
    "user_ratings_total": 87,
    "reviews": [
        {"rating": 5, "text": "Management fixes things fast.", "relative_time": "a month ago"},
        {"rating": 2, "text": "Towing is aggressive.", "relative_time": "3 months ago"},
    ],
}


def _state() -> RunState:
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url="https://maplecourt.test")
    state.geocode = GEOCODE.model_copy()
    return state


class SeamLog:
    """Fake Maps seams recording their calls."""

    def __init__(
        self,
        *,
        places: list[dict[str, Any]] | Exception | None = None,
        minutes: float | None | Exception = 7.5,
        details: dict[str, Any] | None | Exception = DETAILS,
    ) -> None:
        self._places = [KROGER] if places is None else places
        self._minutes = minutes
        self._details = details
        self.nearby_calls: list[tuple[float, float, str]] = []
        self.commute_calls: list[tuple[str, str, str]] = []
        self.details_calls: list[str] = []

    async def nearby(self, lat: float, lng: float, keyword: str) -> list[dict[str, Any]]:
        self.nearby_calls.append((lat, lng, keyword))
        if isinstance(self._places, Exception):
            raise self._places
        return self._places

    async def commute(self, origin: str, destination: str, mode: str) -> float | None:
        self.commute_calls.append((origin, destination, mode))
        if isinstance(self._minutes, Exception):
            raise self._minutes
        return self._minutes

    async def details(self, place_id: str) -> dict[str, Any] | None:
        self.details_calls.append(place_id)
        if isinstance(self._details, Exception):
            raise self._details
        return self._details

    def ctx(self, **overrides: Any) -> StageCtx:
        return StageCtx(
            nearby_places=self.nearby,
            commute_minutes=self.commute,
            place_details=self.details,
            call_structured=overrides.pop(
                "call_structured",
                FakeLLM({"enrich_reviews": {"summary": "Responsive management."}}),
            ),
            **overrides,
        )


def test_happy_path_grocery_reviews_and_no_safety() -> None:
    seams = SeamLog()
    out = asyncio.run(enrich_stage(_state(), seams.ctx()))

    (grocery,) = out.extractions["grocery_proximity"]
    assert grocery.value == 7.5
    assert grocery.confidence is Confidence.HIGH
    assert grocery.model == "maps"
    assert "Kroger" in (grocery.evidence_quote or "")
    assert seams.commute_calls == [("42.3,-83.05", "42.31,-83.06", "driving")]

    (reviews,) = out.extractions["management_reviews"]
    assert reviews.value == {"rating": 4.2, "summary": "Responsive management."}
    assert reviews.source_id == f"google_places:{PLACE_ID}"
    assert reviews.model != "maps"  # synthesis ran → the LLM pin is recorded

    # §20 2026-07-18: the placeholder emits nothing — safety scores unknown.
    assert "location_safety" not in out.extractions


def test_proximity_mode_walking_reaches_the_commute_call() -> None:
    seams = SeamLog()
    asyncio.run(enrich_stage(_state(), seams.ctx(proximity_mode="walking")))
    assert seams.commute_calls[0][2] == "walking"


def test_no_geocode_skips_everything() -> None:
    seams = SeamLog()
    state = _state()
    state.geocode = None
    out = asyncio.run(enrich_stage(state, seams.ctx()))
    assert out.extractions == {}
    assert seams.nearby_calls == [] and seams.details_calls == []


def test_nearby_maps_error_skips_grocery_but_not_reviews() -> None:
    seams = SeamLog(places=MapsError("quota"))
    out = asyncio.run(enrich_stage(_state(), seams.ctx()))
    assert "grocery_proximity" not in out.extractions
    assert "management_reviews" in out.extractions


def test_details_maps_error_skips_reviews_but_not_grocery() -> None:
    seams = SeamLog(details=MapsError("denied"))
    out = asyncio.run(enrich_stage(_state(), seams.ctx()))
    assert "grocery_proximity" in out.extractions
    assert "management_reviews" not in out.extractions


def test_rating_without_review_text_records_rating_with_zero_llm_spend() -> None:
    class Boom:
        async def __call__(self, stage: str, schema: type[Any], content: str) -> Any:
            raise AssertionError("no review text → the synthesis must not fire")

    seams = SeamLog(details={**DETAILS, "reviews": []})
    out = asyncio.run(enrich_stage(_state(), seams.ctx(call_structured=Boom())))
    (reviews,) = out.extractions["management_reviews"]
    assert reviews.value == {"rating": 4.2, "summary": None}
    assert reviews.model == "maps"


def test_no_place_details_result_records_nothing() -> None:
    seams = SeamLog(details=None)
    out = asyncio.run(enrich_stage(_state(), seams.ctx()))
    assert "management_reviews" not in out.extractions


def test_no_route_records_no_grocery_value() -> None:
    seams = SeamLog(minutes=None)
    out = asyncio.run(enrich_stage(_state(), seams.ctx()))
    assert "grocery_proximity" not in out.extractions
