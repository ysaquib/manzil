"""P3-3: Google Maps wrappers + forever-cache. CI never touches Google — every
test injects an httpx transport; the missing-key path is asserted too."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from manzil_worker.enrich import maps


def _transport(handler) -> httpx.MockTransport:  # type: ignore[no-untyped-def]
    return httpx.MockTransport(handler)


GEOCODE_BODY = {
    "status": "OK",
    "results": [
        {
            "place_id": "PLACE_ABC",
            "formatted_address": "120 Maple Ct, Detroit, MI 48187, USA",
            "geometry": {"location": {"lat": 42.331, "lng": -83.045}},
            "address_components": [
                {
                    "long_name": "Detroit",
                    "short_name": "Detroit",
                    "types": ["locality", "political"],
                },
                {
                    "long_name": "Michigan",
                    "short_name": "MI",
                    "types": ["administrative_area_level_1", "political"],
                },
                {
                    "long_name": "Wayne County",
                    "short_name": "Wayne",
                    "types": ["administrative_area_level_2", "political"],
                },
                {
                    "long_name": "United States",
                    "short_name": "US",
                    "types": ["country", "political"],
                },
            ],
        }
    ],
}
NEARBY_BODY = {
    "status": "OK",
    "results": [
        {
            "name": "Kroger",
            "place_id": "P1",
            "rating": 4.2,
            "user_ratings_total": 900,
            "vicinity": "100 Main St",
            "geometry": {"location": {"lat": 42.33, "lng": -83.05}},
        }
    ],
}
DISTANCE_BODY = {
    "status": "OK",
    "rows": [{"elements": [{"status": "OK", "duration": {"value": 900, "text": "15 mins"}}]}],
}


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")


class FakeConn:
    """Minimal asyncpg-shaped conn: one properties row in a dict."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
        return self.row

    async def execute(self, query: str, pid: Any, place_id: str, lat: float, lng: float) -> None:
        self.row.update(place_id=place_id, lat=lat, lng=lng)


async def test_geocode_property_geocodes_once_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert "geocode" in str(request.url)
        assert "key=test-key" in str(request.url)
        return httpx.Response(200, json=GEOCODE_BODY)

    transport = _transport(handler)
    conn = FakeConn({"place_id": None, "lat": None, "lng": None, "canonical_address": "120 Maple"})

    first = await maps.geocode_property(conn, uuid4(), transport=transport)
    assert first == ("PLACE_ABC", 42.331, -83.045)
    assert conn.row["place_id"] == "PLACE_ABC"  # columns written
    assert conn.row["lat"] == 42.331

    # Second call short-circuits on the cached place_id — no HTTP request.
    second = await maps.geocode_property(conn, uuid4(), transport=transport)
    assert second == ("PLACE_ABC", 42.331, -83.045)
    assert calls["n"] == 1  # the "$0 second geocode"


async def test_places_nearby_parses_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "nearbysearch" in str(request.url)
        return httpx.Response(200, json=NEARBY_BODY)

    out = await maps._places_nearby_call(
        42.33, -83.05, keyword="grocery", transport=_transport(handler)
    )
    assert out == [
        {
            "name": "Kroger",
            "place_id": "P1",
            "rating": 4.2,
            "user_ratings_total": 900,
            "vicinity": "100 Main St",
            "lat": 42.33,
            "lng": -83.05,
        }
    ]


async def test_commute_time_returns_minutes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "distancematrix" in str(request.url)
        return httpx.Response(200, json=DISTANCE_BODY)

    minutes = await maps._commute_time_call(
        "42.33,-83.05", "1 Campus Martius, Detroit", mode="driving", transport=_transport(handler)
    )
    assert minutes == 15.0


async def test_commute_time_with_avoid_uses_directions_api() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "directions" in str(request.url)
        assert "avoid=highways" in str(request.url)
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "routes": [{"legs": [{"duration": {"value": 900}}]}],
            },
        )

    minutes = await maps._commute_time_call(
        "42.33,-83.05",
        "1 Campus Martius, Detroit",
        mode="driving",
        avoid_highways=True,
        transport=_transport(handler),
    )
    assert minutes == 15.0


async def test_missing_key_raises_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        return httpx.Response(200, json=GEOCODE_BODY)

    with pytest.raises(maps.MapsError, match="GOOGLE_MAPS_API_KEY"):
        await maps._geocode_call("120 Maple", transport=_transport(handler))


async def test_quota_backoff_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(maps, "MAPS_BACKOFF_BASE_SECONDS", 0.0)  # no real sleep
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(200, json={"status": "OVER_QUERY_LIMIT"})
        return httpx.Response(200, json=GEOCODE_BODY)

    result = await maps._geocode_call("120 Maple", transport=_transport(handler))
    assert result["place_id"] == "PLACE_ABC"
    assert result["city"] == "Detroit"
    assert result["state"] == "MI"
    assert result["county"] == "Wayne County"
    assert state["n"] == 2  # retried once


async def test_hard_status_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "REQUEST_DENIED", "error_message": "bad key"})

    with pytest.raises(maps.MapsError, match="REQUEST_DENIED"):
        await maps._geocode_call("120 Maple", transport=_transport(handler))


# ── place details: contact fields (P3-21) ─────────────────────────────────────

DETAILS_BODY = {
    "status": "OK",
    "result": {
        "name": "Maple Court Apartments",
        "rating": 4.2,
        "user_ratings_total": 87,
        "reviews": [
            {"rating": 5, "text": "Great staff.", "relative_time_description": "a month ago"}
        ],
        "formatted_phone_number": "(313) 555-0142",
        "website": "https://maplecourt.test/",
    },
}


async def test_place_details_requests_contact_fields_and_surfaces_them() -> None:
    """P3-21 rung 2: phone + website ride on the existing once-per-property
    Place Details call. The field mask must actually ask for them — Google
    silently omits unrequested fields, so a missing mask entry would look
    identical to a property with no listed phone."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert "place/details" in str(request.url)
        seen["fields"] = request.url.params["fields"]
        return httpx.Response(200, json=DETAILS_BODY)

    out = await maps._place_details_call("PLACE_ABC", transport=_transport(handler))
    assert "formatted_phone_number" in seen["fields"]
    assert "website" in seen["fields"]
    assert out is not None
    assert out["phone"] == "(313) 555-0142"
    assert out["website"] == "https://maplecourt.test/"
    # The ratings half (§10.12 stage 1) keeps working unchanged.
    assert out["rating"] == 4.2


async def test_place_details_contact_is_none_when_google_omits_it() -> None:
    body = {"status": "OK", "result": {"name": "Maple Court", "rating": 4.2}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    out = await maps._place_details_call("PLACE_ABC", transport=_transport(handler))
    assert out is not None
    assert out["phone"] is None
    assert out["website"] is None
