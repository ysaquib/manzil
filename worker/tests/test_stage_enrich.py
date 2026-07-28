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


def _claims(state: RunState):  # type: ignore[no-untyped-def]
    return {claim.criterion_key: claim for claim in state.source_claims}


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

    grocery = _claims(out)["grocery_proximity"]
    assert grocery.value == 7.5
    assert grocery.confidence is Confidence.HIGH
    assert grocery.model == "maps"
    assert "Kroger" in (grocery.evidence_quote or "")
    assert seams.commute_calls == [("42.3,-83.05", "42.31,-83.06", "driving")]

    reviews = _claims(out)["management_reviews"]
    assert reviews.value == {"rating": 4.2, "summary": "Responsive management."}
    assert reviews.source_id == f"google_places:{PLACE_ID}"
    assert reviews.model != "maps"  # synthesis ran → the LLM pin is recorded

    # §20 2026-07-18: the placeholder emits nothing — safety scores unknown.
    assert "location_safety" not in _claims(out)


def test_proximity_mode_walking_reaches_the_commute_call() -> None:
    seams = SeamLog()
    asyncio.run(enrich_stage(_state(), seams.ctx(proximity_mode="walking")))
    assert seams.commute_calls[0][2] == "walking"


def test_no_geocode_skips_everything() -> None:
    seams = SeamLog()
    state = _state()
    state.geocode = None
    out = asyncio.run(enrich_stage(state, seams.ctx()))
    assert out.source_claims == []
    assert seams.nearby_calls == [] and seams.details_calls == []


def test_nearby_maps_error_skips_grocery_but_not_reviews() -> None:
    seams = SeamLog(places=MapsError("quota"))
    out = asyncio.run(enrich_stage(_state(), seams.ctx()))
    assert "grocery_proximity" not in _claims(out)
    assert "management_reviews" in _claims(out)


def test_details_maps_error_skips_reviews_but_not_grocery() -> None:
    seams = SeamLog(details=MapsError("denied"))
    out = asyncio.run(enrich_stage(_state(), seams.ctx()))
    assert "grocery_proximity" in _claims(out)
    assert "management_reviews" not in _claims(out)


def test_rating_without_review_text_records_rating_with_zero_llm_spend() -> None:
    class Boom:
        async def __call__(self, stage: str, schema: type[Any], content: str) -> Any:
            raise AssertionError("no review text → the synthesis must not fire")

    seams = SeamLog(details={**DETAILS, "reviews": []})
    out = asyncio.run(enrich_stage(_state(), seams.ctx(call_structured=Boom())))
    reviews = _claims(out)["management_reviews"]
    assert reviews.value == {"rating": 4.2, "summary": None}
    assert reviews.model == "maps"


def test_no_place_details_result_records_nothing() -> None:
    seams = SeamLog(details=None)
    out = asyncio.run(enrich_stage(_state(), seams.ctx()))
    assert "management_reviews" not in _claims(out)


def test_no_route_records_no_grocery_value() -> None:
    seams = SeamLog(minutes=None)
    out = asyncio.run(enrich_stage(_state(), seams.ctx()))
    assert "grocery_proximity" not in _claims(out)


# ── P3-21: Places contact (rung 2) ────────────────────────────────────────────

CONTACT_DETAILS = {**DETAILS, "phone": "(313) 555-0142", "website": "https://maplecourt.test/"}


def test_places_contact_lands_on_state_not_source_claims() -> None:
    """Contact info is unscored display metadata (§16, §8.2). It must never enter
    `source_claims`, which is the path into scoring."""
    seams = SeamLog(details=CONTACT_DETAILS)
    out = asyncio.run(enrich_stage(_state(), seams.ctx()))

    assert out.maps_contact is not None
    assert out.maps_contact.phone == "(313) 555-0142"
    assert out.maps_contact.contact_url == "https://maplecourt.test/"
    assert "property_contact" not in _claims(out)
    assert "maps_contact" not in _claims(out)


def test_places_contact_captured_even_when_google_has_no_rating() -> None:
    """A property can have a listed phone and no rating — the contact capture must
    not sit behind the ratings gate."""
    seams = SeamLog(
        details={"name": "Maple Court", "phone": "(313) 555-0142", "website": None, "reviews": []}
    )
    out = asyncio.run(enrich_stage(_state(), seams.ctx()))

    assert "management_reviews" not in _claims(out)
    assert out.maps_contact is not None
    assert out.maps_contact.phone == "(313) 555-0142"


def test_no_contact_fields_leaves_maps_contact_unset() -> None:
    seams = SeamLog(details=DETAILS)  # no phone/website keys
    out = asyncio.run(enrich_stage(_state(), seams.ctx()))
    assert out.maps_contact is None


def test_place_details_failure_leaves_contact_unset_without_failing_the_job() -> None:
    seams = SeamLog(details=MapsError("denied"))
    out = asyncio.run(enrich_stage(_state(), seams.ctx()))
    assert out.maps_contact is None
    assert _claims(out)["grocery_proximity"].value == 7.5  # other slices survive
