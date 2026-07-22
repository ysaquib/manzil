"""ENRICH stage (P3-8, DESIGN §10.3, §10.12): Maps-derived location criteria +
ratings stage 1 (Google Places), deterministic dispatch — no tool loop (§10.2:
ENRICH is not a loop stage; the Maps seams are plain injected calls).

What it emits (into `state.source_claims`, downstream of VERIFY by design so the
page-evidence audit never runs on API-derived values):
- `grocery_proximity` — minutes to the nearest grocery per the hunt's
  `proximity_mode` setting (places_nearby → commute_time).
- `management_reviews` — `{rating, summary}` from one Place Details call keyed
  by the DEDUPE geocode's place_id; the summary is one small-model synthesis
  over the returned snippets (skipped, zero LLM spend, when Google returns a
  rating but no review text).
- `location_safety` — **nothing** (§20 2026-07-18): the criterion is an
  override-first A+..F placeholder until the P3-17 safety module lands. ENRICH
  deliberately emits no value so the criterion scores unknown rather than a
  fabricated grade.

Failure posture: a Maps failure on one slice logs and skips that slice — a dead
enrichment is a missing value, never a failed job. No geocode (DEDUPE couldn't
resolve one and the identity has no address) skips the stage the same way.
"""

from __future__ import annotations

from typing import Any

import structlog
from manzil_shared.models import Confidence
from pydantic import BaseModel

from manzil_worker.enrich.maps import MapsError
from manzil_worker.llm.config import model_for_stage
from manzil_worker.llm.prompt_loader import load_prompt
from manzil_worker.stages.base import CommuteMinutes, NearbyPlaces, StageCtx
from manzil_worker.state import RunState, SourceClaim

log = structlog.get_logger()

# `FieldExtraction.model` sentinel for API-derived values with no LLM involved.
MAPS_MODEL = "maps"
_GROCERY_KEYWORD = "grocery"


class ReviewSynthesisOut(BaseModel):
    """Forced schema for the review synthesis (P1 call)."""

    summary: str


async def nearest_grocery_minutes(
    lat: float,
    lng: float,
    mode: str,
    *,
    nearby_places: NearbyPlaces,
    commute_minutes: CommuteMinutes,
) -> tuple[float, str] | None:
    """`(minutes, place_name)` to the nearest grocery by `mode`, or None when
    Google finds no grocery or no route. Shared by the ingest stage and the
    proximity-flip refresh dispatcher (queue.py), so both paths stay identical."""
    places = await nearby_places(lat, lng, _GROCERY_KEYWORD)
    nearest = next(
        (p for p in places if p.get("lat") is not None and p.get("lng") is not None), None
    )
    if nearest is None:
        return None
    minutes = await commute_minutes(f"{lat},{lng}", f"{nearest['lat']},{nearest['lng']}", mode)
    if minutes is None:
        return None
    return (minutes, nearest.get("name") or "unnamed")


def grocery_extraction(minutes: float, place_name: str, mode: str) -> SourceClaim:
    return SourceClaim(
        criterion_key="grocery_proximity",
        value=minutes,
        confidence=Confidence.HIGH,
        evidence_quote=f"Nearest grocery: {place_name} — {minutes} min {mode} (Google Maps)",
        source_id="google_maps:places_nearby",
        model=MAPS_MODEL,
        prompt_version=0,
    )


def _reviews_content(details: dict[str, Any]) -> str:
    lines = [
        f"Property: {details.get('name') or 'unknown'}",
        f"Google rating: {details['rating']} ({details.get('user_ratings_total') or 0} ratings)",
        "",
    ]
    for review in details["reviews"]:
        stars = f"{review['rating']}★ " if review.get("rating") is not None else ""
        when = f" ({review['relative_time']})" if review.get("relative_time") else ""
        lines.append(f"- {stars}{review['text']}{when}")
    return "\n".join(lines)


async def enrich_stage(state: RunState, ctx: StageCtx) -> RunState:
    geocode = state.geocode
    if geocode is None:
        log.info("enrich_skipped_no_geocode", job_id=str(state.job_id), stage="enrich")
        return state

    # grocery_proximity — Maps only, no LLM.
    try:
        found = await nearest_grocery_minutes(
            geocode.lat,
            geocode.lng,
            ctx.proximity_mode,
            nearby_places=ctx.nearby_places,
            commute_minutes=ctx.commute_minutes,
        )
    except MapsError as error:
        log.warning("enrich_grocery_failed", job_id=str(state.job_id), error=str(error))
        found = None
    if found is not None:
        minutes, place_name = found
        state.source_claims.append(grocery_extraction(minutes, place_name, ctx.proximity_mode))

    # management_reviews — ratings stage 1 (§10.12): one Place Details call; the
    # summary synthesis fires only when Google returned review text.
    try:
        details = await ctx.place_details(geocode.place_id)
    except MapsError as error:
        log.warning("enrich_reviews_failed", job_id=str(state.job_id), error=str(error))
        details = None
    if details is not None and details.get("rating") is not None:
        summary: str | None = None
        model = MAPS_MODEL
        prompt_version = 0
        if details.get("reviews"):
            synthesis = await ctx.call_structured(
                "enrich_reviews", ReviewSynthesisOut, _reviews_content(details)
            )
            summary = synthesis.summary
            model = model_for_stage("enrich_reviews")
            prompt_version = load_prompt("enrich_reviews").version
        total = details.get("user_ratings_total") or 0
        state.source_claims.append(
            SourceClaim(
                criterion_key="management_reviews",
                value={"rating": details["rating"], "summary": summary},
                confidence=Confidence.HIGH,
                evidence_quote=f"Google Places rating {details['rating']} ({total} ratings)",
                source_id=f"google_places:{geocode.place_id}",
                model=model,
                prompt_version=prompt_version,
            )
        )

    # location_safety — deliberately nothing (§20 2026-07-18): override-first
    # placeholder until the P3-17 module; an emitted guess would score.
    log.info(
        "enrich_safety_placeholder",
        job_id=str(state.job_id),
        stage="enrich",
        note="location_safety awaits the P3-17 module; value arrives via override",
    )
    return state
