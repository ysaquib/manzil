"""Stage protocol + injected context (IMPLEMENTATION §3).

A stage is `async (RunState, StageCtx) -> RunState`. Everything a stage
touches beyond its state arrives injected through StageCtx, so tests fake the
world wholesale — no monkeypatching stage internals.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from manzil_shared.models import Confidence, RubricCriterion

from manzil_worker.llm import client as llm_client

if TYPE_CHECKING:
    from manzil_worker.enrich.images import DownloadImage, ImageObjectStore
    from manzil_worker.fetching.registry import AdapterRegistry
    from manzil_worker.fetching.tiers import Fetcher
    from manzil_worker.state import DedupeCandidate, GeocodeIn, RunState, SourceFreshness

CallStructured = Callable[[str, type[Any], str], Awaitable[Any]]
CallVision = Callable[[str, type[Any], list[Any]], Awaitable[Any]]

# PLAN's DB seam (P3-2): given a property id and a source URL, return the
# persisted source's freshness inputs, or None when no row exists. Injected like
# `call_structured` so PLAN reaches Postgres in the worker but fakes without a DB.
FreshSourceLookup = Callable[[UUID | None, str], Awaitable["SourceFreshness | None"]]

# DEDUPE's DB seam (P3-4): the existing `properties` rows the incoming identity is
# compared against (self excluded by the caller). A dumb read, injected like
# `fresh_source_lookup` so DEDUPE reaches Postgres in the worker but fakes with a
# plain list in unit tests.
DedupeCandidates = Callable[[], Awaitable[list["DedupeCandidate"]]]

# DEDUPE's geocode seam (P3-4): a plain function call (NOT a tool loop — DEDUPE
# gets zero tools, §16). Default wraps the live Maps Geocoding call; tests inject
# a fake, and a fake raising `MapsError` exercises the geocode-failed path.
GeocodeAddress = Callable[[str], Awaitable["GeocodeIn"]]
ExistingImageHashes = Callable[[UUID], Awaitable[set[str]]]

# ENRICH's Maps seams (P3-8): plain function calls, not tools (§10.2 — ENRICH is
# not a tool-loop stage). Defaults wrap the live Maps calls lazily, mirroring
# `geocode_address`; tests inject fakes. `nearby_places(lat, lng, keyword)`,
# `commute_minutes(origin_latlng, destination, mode)`, `place_details(place_id)`.
NearbyPlaces = Callable[[float, float, str], Awaitable[list[dict[str, Any]]]]
CommuteMinutes = Callable[[str, str, str], Awaitable[float | None]]
PlaceDetails = Callable[[str], Awaitable[dict[str, Any] | None]]

# SCORE's baselines seam (P3-9): `(metro, beds_bucket)` → utility →
# (monthly_high, monthly_median), or None when the metro has no baseline rows —
# the composer's graceful v1 fallback. The queue wires the DB read; the default
# returns None so CLI and unit runs compose exactly like shipped v1.
UtilityBaselines = Callable[[str, int], Awaitable[dict[str, tuple[float, float]] | None]]


async def _no_fresh_source(property_id: UUID | None, url: str) -> SourceFreshness | None:
    """Default lookup: no database wired (CLI / unit tests) → nothing is fresh, so
    PLAN always plans `action: fetch`."""
    return None


async def _no_dedupe_candidates() -> list[DedupeCandidate]:
    """Default: no database wired (CLI / unit runs) → no candidates, so DEDUPE
    no-ops to `no_candidates` and the run keeps its own placeholder property."""
    return []


async def _no_existing_image_hashes(property_id: UUID) -> set[str]:
    return set()


async def _no_utility_baselines(metro: str, bucket: int) -> dict[str, tuple[float, float]] | None:
    return None


async def _live_nearby_places(lat: float, lng: float, keyword: str) -> list[dict[str, Any]]:
    from manzil_worker.enrich.maps import _places_nearby_call

    return await _places_nearby_call(lat, lng, keyword=keyword)


async def _live_commute_minutes(origin_latlng: str, destination: str, mode: str) -> float | None:
    from manzil_worker.enrich.maps import _commute_time_call

    return await _commute_time_call(origin_latlng, destination, mode=mode)


async def _live_place_details(place_id: str) -> dict[str, Any] | None:
    from manzil_worker.enrich.maps import _place_details_call

    return await _place_details_call(place_id)


async def _live_geocode_address(address: str) -> GeocodeIn:
    """Default geocode: the live Maps Geocoding call as a plain function (§10.3).
    Imported lazily so non-DEDUPE runs and CI never import the Maps surface, and
    so a missing key raises only at live-use time (MapsError names the var)."""
    from manzil_worker.enrich.maps import _geocode_call
    from manzil_worker.state import GeocodeIn

    return GeocodeIn(**await _geocode_call(address))


class Persistence(Protocol):
    """The persist-before-advance sink. Phase 0: a JSON file per run;
    Phase 1+ (P1-2): the jobs row."""

    async def save(self, state: RunState) -> None: ...


class NullPersistence:
    async def save(self, state: RunState) -> None:
        return None


def _today() -> date:
    return datetime.now(UTC).date()


@dataclass
class StageCtx:
    fetchers: dict[int, Fetcher] = field(default_factory=dict)
    registry: AdapterRegistry | None = None
    call_structured: CallStructured = llm_client.call_structured
    call_vision: CallVision = llm_client.call_vision
    rubric: list[RubricCriterion] = field(default_factory=list)
    rubric_version: int = 0
    # Hunt setting (§8.2 contract, DESIGN v2.3): effective values below this
    # score as unknown. Phase 0 uses the contract default; hunts own it from P1-5.
    min_confidence: Confidence = Confidence.MEDIUM
    # Household counts (§8.2 hunt settings, §9.5 v1): pet counts drive the pet-rent
    # component of `all_in_monthly`. Default 0 so Phase 0 CLI runs compose no pet rent.
    cats: int = 0
    dogs: int = 0
    # §9.5 P3-9 composition inputs: mode picks the baseline column (conservative →
    # monthly_high); occupants scales the per-person utilities (water/sewer).
    cost_estimate_mode: str = "conservative"
    occupants: int = 1
    utility_baselines_lookup: UtilityBaselines = _no_utility_baselines
    persistence: Persistence = field(default_factory=NullPersistence)
    today: Callable[[], date] = _today
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep  # injected so tests skip backoff
    # PLAN inputs (P3-2). `fresh_source_lookup` reaches `property_sources`; the
    # default returns None so non-DB runs never skip. `plan_trigger` is the §10.4
    # manifest trigger (`user:submit` new / `user:retry` manual retry).
    fresh_source_lookup: FreshSourceLookup = _no_fresh_source
    plan_trigger: str = "user:submit"
    # DEDUPE inputs (P3-4). `dedupe_candidates` reads existing `properties`;
    # `geocode_address` geocodes the extracted address as a plain call (no tools).
    # Defaults no-op without a DB / key, so CLI and unit runs never merge or
    # touch Google.
    dedupe_candidates: DedupeCandidates = _no_dedupe_candidates
    geocode_address: GeocodeAddress = _live_geocode_address
    # ENRICH inputs (P3-8). `proximity_mode` is the hunt setting (§8.2) grocery
    # proximity honors; the Maps seams default to the live calls and fake in tests.
    proximity_mode: str = "driving"
    nearby_places: NearbyPlaces = _live_nearby_places
    commute_minutes: CommuteMinutes = _live_commute_minutes
    place_details: PlaceDetails = _live_place_details
    # IMAGE_FETCH inputs (P3-7a). Binary downloads and private Storage are
    # injected so CI never touches the network; the queue wires production
    # defaults when Supabase credentials exist.
    download_image: DownloadImage | None = None
    image_store: ImageObjectStore | None = None
    existing_image_hashes: ExistingImageHashes = _no_existing_image_hashes


Stage = Callable[["RunState", StageCtx], Awaitable["RunState"]]
