"""DEDUPE stage (P3-4, DESIGN §10.3): resolve the incoming property's identity to
ONE canonical `properties` row before the multi-source waves run.

Extracted facts are GLOBAL — one Property, many Hunts — so two URLs for the same
building must land on one `properties` row or shared facts fork. Every submission
creates a fresh placeholder property (submit_listing migration); DEDUPE reads
EXTRACT's `property_identity` block, geocodes the address (a plain function call —
DEDUPE gets ZERO tools, §16), compares against existing properties, and decides:

    distance (m)        name similarity (rapidfuzz token_sort_ratio, 0-100)
    --------------      ---------------------------------------------------
    > 100m              (not a candidate — out of range)
    <= 100m             >= AUTO (90)         -> merge automatically
    <= 100m             GRAY (60) .. AUTO    -> `resolve_dedupe` checkpoint
    <= 100m             < GRAY               -> keep separate
    place_id equal      >= AUTO              -> merge automatically
    place_id equal      < AUTO               -> `resolve_dedupe` checkpoint
                                                (Google says same place, names
                                                 disagree: genuine ambiguity)

A merge switches the run to the existing canonical property (`state.property_id`);
the placeholder dies at the terminal projection (queue.py). DEDUPE itself NEVER
writes the database — the decision rides RunState and the projection applies it.

Conservative default (R5): the checkpoint's `default` is "keep_separate". A false
split is cheap to undo (re-merge later); a false merge poisons shared facts across
every hunt, so ambiguity never auto-merges. A Maps outage is not a run failure —
`geocode_failed` keeps the property separate, recoverable by a later re-merge.

Idempotent + resumable: DEDUPE stores its outcome on RunState and, on a parked-
then-answered resume, applies the answer without re-geocoding.
"""

from __future__ import annotations

import math

import structlog
from manzil_shared.config import (
    DEDUPE_MAX_DISTANCE_METERS,
    DEDUPE_NAME_AUTO_SIMILARITY,
    DEDUPE_NAME_GRAY_SIMILARITY,
)
from manzil_shared.errors import CheckpointRaised
from manzil_shared.models import CheckpointKind, CheckpointPrompt
from rapidfuzz import fuzz

from manzil_worker.enrich.maps import MapsError
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import DedupeCandidate, DedupeDecision, GeocodeIn, RunState

log = structlog.get_logger()

_EARTH_RADIUS_M = 6_371_000.0

# A resolve_dedupe answer's `choice` is one of these; a confirm_value answer's is
# yes/no. DEDUPE routes on this so it never consumes VERIFY's confirm_value answer
# (the checkpoint prompt itself is cleared by the API on answer, so choice — not
# kind — is the reliable discriminator on resume).
_DEDUPE_CHOICES = frozenset({"merge", "keep_separate"})


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres. Pure, dependency-free (§10.3: implement
    inline)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _name_similarity(name: str | None, candidate_name: str | None) -> float:
    """rapidfuzz token_sort_ratio over casefolded names (0-100). A missing name on
    either side scores 0.0 — no name is no evidence of sameness."""
    if not name or not candidate_name:
        return 0.0
    return float(fuzz.token_sort_ratio(name.casefold(), candidate_name.casefold()))


def _is_dedupe_answer(state: RunState) -> bool:
    answer = state.checkpoint_answer
    if not answer:
        return False
    checkpoint = state.checkpoint
    if checkpoint is not None and checkpoint.kind is not CheckpointKind.RESOLVE_DEDUPE:
        return False
    return answer.get("choice") in _DEDUPE_CHOICES


def _apply_answer(state: RunState) -> RunState:
    """Apply a resolved `resolve_dedupe` checkpoint without re-geocoding. "merge"
    switches the run to the chosen canonical property; anything else keeps it
    separate. Clears the answer (and the prompt, matching the confirm_value/API
    convention) so the resume advances past DEDUPE."""
    from uuid import UUID

    answer = state.checkpoint_answer or {}
    choice = answer.get("choice")
    context_ref = answer.get("context_ref")
    if choice == "merge" and context_ref:
        state.property_id = UUID(str(context_ref))
        state.dedupe = DedupeDecision(
            action="merged_user",
            candidate_property_id=str(context_ref),
            note="user confirmed merge",
        )
    else:
        state.dedupe = DedupeDecision(
            action="kept_separate_user",
            candidate_property_id=str(context_ref) if context_ref else None,
            note="user kept separate",
        )
    state.checkpoint_answer = None
    state.checkpoint = None
    log.info("deduped", job_id=str(state.job_id), stage="dedupe", action=state.dedupe.action)
    return state


def _in_range(candidate: DedupeCandidate, geocode: GeocodeIn) -> tuple[bool, float | None]:
    """Whether a candidate is a merge target and, when known, its distance (m). In
    range iff its place_id equals ours OR it is within DEDUPE_MAX_DISTANCE_METERS.
    A candidate lacking both a place match and coordinates is skipped."""
    place_match = bool(candidate.place_id) and candidate.place_id == geocode.place_id
    distance: float | None = None
    if candidate.lat is not None and candidate.lng is not None:
        distance = _haversine_m(geocode.lat, geocode.lng, candidate.lat, candidate.lng)
    if place_match:
        return True, distance
    if distance is not None and distance <= DEDUPE_MAX_DISTANCE_METERS:
        return True, distance
    return False, distance


def _distance_phrase(distance: float | None) -> str:
    return f"{distance:.0f} m away" if distance is not None else "at the same mapped place"


async def dedupe_stage(state: RunState, ctx: StageCtx) -> RunState:
    # 1. Resolved checkpoint: apply the answer and advance (never re-geocode).
    if _is_dedupe_answer(state):
        return _apply_answer(state)

    # 2/3. No identity to match on → never fail the job; record and move on.
    identity = state.property_identity
    if identity is None or (not identity.name and not identity.address):
        state.dedupe = DedupeDecision(action="no_identity")
        return state
    if not identity.address:
        state.dedupe = DedupeDecision(action="no_address")
        return state

    # 4. Geocode the address as a plain call. A Maps outage must not fail the run
    # (the cost is a possible duplicate, recoverable by re-merge). Store the result
    # so the projection can seed the properties forever-cache columns (§2.3).
    try:
        geocode = await ctx.geocode_address(identity.address)
    except MapsError as error:
        state.dedupe = DedupeDecision(action="geocode_failed", note=str(error))
        log.warning("dedupe_geocode_failed", job_id=str(state.job_id), error=str(error))
        return state
    state.geocode = geocode

    # 5. Load candidates, excluding this run's own placeholder property.
    candidates = [c for c in await ctx.dedupe_candidates() if c.id != state.property_id]
    in_range = [(c, dist) for c in candidates for ok, dist in [_in_range(c, geocode)] if ok]
    if not in_range:
        state.dedupe = DedupeDecision(action="no_candidates")
        return state

    # 6/7. Best name similarity among the in-range candidates decides the branch.
    best, distance = max(in_range, key=lambda pair: _name_similarity(identity.name, pair[0].name))
    similarity = _name_similarity(identity.name, best.name)
    place_match = bool(best.place_id) and best.place_id == geocode.place_id

    if similarity >= DEDUPE_NAME_AUTO_SIMILARITY:
        state.property_id = best.id
        state.dedupe = DedupeDecision(
            action="merged_auto",
            candidate_property_id=str(best.id),
            distance_m=distance,
            name_similarity=similarity,
            note=f"auto-merged: {_distance_phrase(distance)}, name similarity {similarity:.0f}",
        )
        log.info("deduped", job_id=str(state.job_id), stage="dedupe", action="merged_auto")
        return state

    if similarity >= DEDUPE_NAME_GRAY_SIMILARITY or place_match:
        question = (
            f"Possible duplicate property. This listing "
            f"({identity.name or 'unnamed'} — {identity.address}) is {_distance_phrase(distance)} "
            f"from an existing property ({best.name or 'unnamed'} — "
            f"{best.canonical_address or 'address unknown'}); name similarity "
            f"{similarity:.0f}/100. Merge them into one property?"
        )
        raise CheckpointRaised(
            CheckpointPrompt(
                kind=CheckpointKind.RESOLVE_DEDUPE,
                question=question,
                options=["merge", "keep_separate"],
                default="keep_separate",
                context_ref=str(best.id),
            )
        )

    state.dedupe = DedupeDecision(
        action="kept_separate",
        candidate_property_id=str(best.id),
        distance_m=distance,
        name_similarity=similarity,
        note=f"kept separate: nearest name similarity {similarity:.0f} below gray zone",
    )
    log.info("deduped", job_id=str(state.job_id), stage="dedupe", action="kept_separate")
    return state
