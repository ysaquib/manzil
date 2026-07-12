"""Google Maps tools + forever-cache (DESIGN §12, §2.3 of the Phase 3 plan).

Three custom tools — ``geocode``, ``places_nearby``, ``commute_time`` — plus the
``geocode_property`` cache helper, all thin ``httpx`` wrappers over the Geocoding,
Places, and Routes (Distance Matrix) HTTP APIs. No Google SDK: this one module
owns the Maps HTTP surface, the way ``llm/client.py`` owns the LLM SDK (NFR5).

Caching is the "$0 second geocode": ``geocode_property`` reads
``properties.place_id/lat/lng`` and returns immediately when they are set,
geocoding + writing the columns only on a miss (§2.3 — location facts are
immutable, so a geocode is paid once per property, ever).

Credential: ``GOOGLE_MAPS_API_KEY``, server-side only (worker env), read the same
way tier-3 reads its provider key — a clear error names the var when it is absent
at live use. CI never touches Google: tests inject an ``httpx`` transport.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import structlog
from manzil_shared.config import (
    MAPS_BACKOFF_BASE_SECONDS,
    MAPS_MAX_RETRIES,
    MAPS_TIMEOUT_SECONDS,
)

from manzil_worker.llm.tools import current_tool_context, tool

log = structlog.get_logger()

_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
_DISTANCE_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"

# Google `status` values that mean "no error, just no data" — an empty result,
# not a failure.
_EMPTY_STATUSES = frozenset({"ZERO_RESULTS", "NOT_FOUND"})
# `status` values worth retrying (transient quota); everything else is fatal.
_RETRY_STATUSES = frozenset({"OVER_QUERY_LIMIT", "UNKNOWN_ERROR"})


class MapsError(RuntimeError):
    """A Maps request failed unrecoverably (bad key, denied, exhausted retries)."""


def google_maps_key() -> str:
    """The server-side Maps key, or a clear error naming the env var. Only read at
    live-use time so record/replay + fake-transport tests never require it."""
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise MapsError(
            "GOOGLE_MAPS_API_KEY unset — the Google Maps tools need a restricted, "
            "server-side key (Geocoding/Places/Routes). Set it in the worker env."
        )
    return key


async def _get_json(url: str, params: dict[str, str], *, transport: Any = None) -> dict[str, Any]:
    """One Maps GET with quota-aware backoff. Retries HTTP 429/5xx and Google's
    transient `status` values; raises `MapsError` on a hard failure or once the
    retry budget is spent."""
    params = {**params, "key": google_maps_key()}
    last_error = "unknown"
    # A hard failure `raise`s and a success `return`s inside the loop, so any path
    # that reaches the bottom is transient and retries with backoff.
    for attempt in range(MAPS_MAX_RETRIES + 1):
        async with httpx.AsyncClient(timeout=MAPS_TIMEOUT_SECONDS, transport=transport) as client:
            try:
                response = await client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_error = repr(exc)
            else:
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = f"http {response.status_code}"
                else:
                    body = response.json()
                    status = body.get("status", "")
                    if status in _RETRY_STATUSES:
                        last_error = f"maps status {status}"
                    elif status and status != "OK" and status not in _EMPTY_STATUSES:
                        # REQUEST_DENIED / INVALID_REQUEST / OVER_DAILY_LIMIT — hard.
                        raise MapsError(
                            f"Maps {url} returned status {status!r}: "
                            f"{body.get('error_message', '(no message)')}"
                        )
                    else:
                        return body
        if attempt < MAPS_MAX_RETRIES:
            await asyncio.sleep(MAPS_BACKOFF_BASE_SECONDS * (2**attempt))
            log.warning("maps_retry", url=url, attempt=attempt + 1, reason=last_error)
    raise MapsError(f"Maps {url} failed after {MAPS_MAX_RETRIES + 1} attempts: {last_error}")


# ── geocoding ─────────────────────────────────────────────────────────────────


async def _geocode_call(address: str, *, transport: Any = None) -> dict[str, Any]:
    body = await _get_json(_GEOCODE_URL, {"address": address}, transport=transport)
    results = body.get("results") or []
    if not results:
        raise MapsError(f"geocode: no results for {address!r}")
    top = results[0]
    loc = top["geometry"]["location"]
    return {
        "place_id": top["place_id"],
        "lat": float(loc["lat"]),
        "lng": float(loc["lng"]),
        "formatted_address": top.get("formatted_address", address),
    }


@tool
async def geocode(address: str) -> dict[str, Any]:
    """Geocode a street address to a Google place_id and lat/lng coordinates."""
    ctx = current_tool_context()
    return await _geocode_call(address, transport=ctx.maps_transport)


# ── places nearby ─────────────────────────────────────────────────────────────


async def _places_nearby_call(
    lat: float,
    lng: float,
    *,
    keyword: str | None = None,
    place_type: str | None = None,
    transport: Any = None,
) -> list[dict[str, Any]]:
    params: dict[str, str] = {"location": f"{lat},{lng}", "rankby": "distance"}
    if keyword:
        params["keyword"] = keyword
    if place_type:
        params["type"] = place_type
    body = await _get_json(_NEARBY_URL, params, transport=transport)
    out: list[dict[str, Any]] = []
    for r in body.get("results") or []:
        loc = r.get("geometry", {}).get("location", {})
        out.append(
            {
                "name": r.get("name"),
                "place_id": r.get("place_id"),
                "rating": r.get("rating"),
                "user_ratings_total": r.get("user_ratings_total"),
                "vicinity": r.get("vicinity"),
                "lat": loc.get("lat"),
                "lng": loc.get("lng"),
            }
        )
    return out


@tool
async def places_nearby(
    lat: float,
    lng: float,
    keyword: str | None = None,
    place_type: str | None = None,
) -> list[dict[str, Any]]:
    """Find nearby places (grocery, transit, worship, …) around a lat/lng, ranked
    by distance. Filter with a free-text `keyword` and/or a Google place `type`."""
    ctx = current_tool_context()
    return await _places_nearby_call(
        lat, lng, keyword=keyword, place_type=place_type, transport=ctx.maps_transport
    )


# ── commute time (Distance Matrix; Routes family) ─────────────────────────────


async def _commute_time_call(
    origin_latlng: str,
    destination: str,
    *,
    mode: str = "driving",
    transport: Any = None,
) -> float | None:
    body = await _get_json(
        _DISTANCE_URL,
        {"origins": origin_latlng, "destinations": destination, "mode": mode},
        transport=transport,
    )
    rows = body.get("rows") or []
    if not rows:
        return None
    elements = rows[0].get("elements") or []
    if not elements or elements[0].get("status") != "OK":
        return None
    seconds = elements[0]["duration"]["value"]
    return round(seconds / 60.0, 1)


@tool
async def commute_time(
    origin_latlng: str,
    destination: str,
    mode: str = "driving",
) -> float | None:
    """Estimate commute minutes from an origin "lat,lng" to a destination address
    by `mode` (driving | walking | bicycling | transit). None when no route."""
    ctx = current_tool_context()
    return await _commute_time_call(
        origin_latlng, destination, mode=mode, transport=ctx.maps_transport
    )


# ── forever-cache helper ──────────────────────────────────────────────────────


async def geocode_property(
    conn: Any, property_id: Any, *, transport: Any = None
) -> tuple[str, float, float]:
    """Return `(place_id, lat, lng)` for a property, geocoding at most once ever.
    A property whose `place_id` is already set is a $0 read; otherwise geocode its
    `canonical_address`, persist the three columns, and return — the "cached
    second geocode is free" contract (§2.3). `conn` is any asyncpg
    connection/pool."""
    row = await conn.fetchrow(
        "select place_id, lat, lng, canonical_address from properties where id = $1",
        property_id,
    )
    if row is None:
        raise MapsError(f"geocode_property: no property {property_id}")
    if row["place_id"]:
        return (row["place_id"], float(row["lat"]), float(row["lng"]))
    address = row["canonical_address"]
    if not address:
        raise MapsError(f"geocode_property: property {property_id} has no canonical_address")
    result = await _geocode_call(address, transport=transport)
    await conn.execute(
        "update properties set place_id = $2, lat = $3, lng = $4 where id = $1",
        property_id,
        result["place_id"],
        result["lat"],
        result["lng"],
    )
    return (result["place_id"], result["lat"], result["lng"])
