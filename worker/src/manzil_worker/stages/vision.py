"""Anchored kitchen-quality VISION over deterministic IMAGE_CLASSIFY targets."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from manzil_shared.models import Confidence, TargetScope, UnitApplicability
from pydantic import BaseModel, Field

from manzil_worker.llm import VisionImage
from manzil_worker.llm.config import model_for_stage
from manzil_worker.llm.prompt_loader import load_prompt
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import RunState, SourceClaim
from manzil_worker.vision_refs import (
    VISION_REFS_DIR,
    load_reference_manifest,
    vision_references_ready,
)


class KitchenAssessment(BaseModel):
    content_hash: str
    visibility: Literal["visible", "not_visible"]
    rating: int | None = Field(default=None, ge=1, le=5)
    confidence: Literal["high", "medium", "low"]
    rationale: str = Field(max_length=300)


class KitchenAssessmentBatch(BaseModel):
    assessments: list[KitchenAssessment] = Field(default_factory=list)


@dataclass(frozen=True)
class KitchenAggregate:
    rating: int
    confidence: Confidence
    hashes: tuple[str, ...]


def aggregate_kitchen(assessments: list[KitchenAssessment]) -> KitchenAggregate | None:
    usable = [
        assessment
        for assessment in assessments
        if assessment.visibility == "visible"
        and assessment.rating is not None
        and assessment.confidence in {"high", "medium"}
    ]
    if not usable:
        return None
    ratings = [assessment.rating for assessment in usable if assessment.rating is not None]
    if max(ratings) - min(ratings) > 2:
        return None
    weighted = sorted(
        (assessment.rating, 2 if assessment.confidence == "high" else 1)
        for assessment in usable
        if assessment.rating is not None
    )
    total = sum(weight for _, weight in weighted)
    running = 0
    rating = weighted[0][0]
    for candidate, weight in weighted:
        running += weight
        rating = candidate
        # Equality intentionally stops on the lower value.
        if running * 2 >= total:
            break
    if len(usable) == 1:
        confidence = Confidence.MEDIUM
    elif max(ratings) - min(ratings) <= 1 and any(a.confidence == "high" for a in usable):
        confidence = Confidence.HIGH
    else:
        confidence = Confidence.MEDIUM
    return KitchenAggregate(
        rating=rating,
        confidence=confidence,
        hashes=tuple(assessment.content_hash for assessment in usable),
    )


async def vision_stage(state: RunState, ctx: StageCtx) -> RunState:
    if not vision_references_ready(criterion="kitchen_quality"):
        if state.plan is not None:
            state.plan.skipped["VISION"] = "missing_kitchen_reference_set"
        return state
    selected_hashes = state.vision_targets.get("kitchen_quality", [])
    selected = [
        image for image in state.property_images if image.content_hash in selected_hashes
    ]
    if not selected or ctx.image_store is None:
        if state.plan is not None:
            state.plan.skipped["VISION"] = "no_classified_kitchen_targets"
        return state

    manifest = load_reference_manifest(criterion="kitchen_quality")
    assert manifest is not None
    profile = manifest["profiles"]["kitchen_quality"]
    input_digest = hashlib.sha256(
        json.dumps(
            {
                "criterion": "kitchen_quality",
                "targets": [
                    {
                        "hash": image.content_hash,
                        "associations": sorted(image.exact_floor_plan_refs),
                    }
                    for image in selected
                ],
                "model": model_for_stage("vision"),
                "prompt_version": load_prompt("vision").version,
                "reference_version": profile["version"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    images: list[VisionImage] = []
    for rating in range(1, 6):
        sheet = profile["sheets"][str(rating)]
        data = (VISION_REFS_DIR / sheet["file"]).read_bytes()
        images.append(
            VisionImage(
                content_hash=sheet["sha256"],
                data=data,
                label=f"reference:kitchen_quality:{rating}:v{profile['version']}",
            )
        )
    for image in selected:
        data = await ctx.image_store.get(image.storage_path)
        associations = ",".join(sorted(image.exact_floor_plan_refs)) or "gallery"
        images.append(
            VisionImage(
                content_hash=image.content_hash,
                data=data,
                label=f"target:{image.content_hash}:associations={associations}",
            )
        )
    result = await ctx.call_vision("vision", KitchenAssessmentBatch, images)
    returned = [assessment.content_hash for assessment in result.assessments]
    if len(returned) != len(set(returned)) or set(returned) != set(selected_hashes):
        raise ValueError("VISION must assess every selected target hash exactly once")
    for assessment in result.assessments:
        if assessment.visibility == "not_visible" and assessment.rating is not None:
            raise ValueError("not_visible VISION target cannot carry a rating")

    by_hash = {assessment.content_hash: assessment for assessment in result.assessments}
    for image in selected:
        image.vision_assessment = {
            **(image.vision_assessment or {}),
            "kitchen_quality": {
                "input_digest": input_digest,
                "model": model_for_stage("vision"),
                "prompt_version": load_prompt("vision").version,
                "reference_version": profile["version"],
                "assessment": by_hash[image.content_hash].model_dump(),
            },
        }

    origin = (
        f"vision:{model_for_stage('vision')}:prompt-{load_prompt('vision').version}:"
        f"references-{profile['version']}"
    )
    gallery = aggregate_kitchen(result.assessments)
    claims: list[SourceClaim] = []
    if gallery is not None:
        claims.append(
            SourceClaim(
                criterion_key="kitchen_quality",
                value=gallery.rating,
                confidence=gallery.confidence,
                evidence_quote="Property-gallery visual estimate from selected kitchen photos.",
                model=model_for_stage("vision"),
                prompt_version=load_prompt("vision").version,
                target_scope=TargetScope.PROPERTY,
                applicability=UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
                origin_key=origin,
                resolution_rule="vision_weighted_median_gallery",
                image_hashes=list(gallery.hashes),
            )
        )

    by_plan: dict[str, list[KitchenAssessment]] = defaultdict(list)
    for image in selected:
        for ref in image.exact_floor_plan_refs:
            by_plan[ref].append(by_hash[image.content_hash])
    for ref, assessments in by_plan.items():
        aggregate = aggregate_kitchen(assessments)
        if aggregate is None:
            continue
        claims.append(
            SourceClaim(
                criterion_key="kitchen_quality",
                value=aggregate.rating,
                confidence=aggregate.confidence,
                evidence_quote="Exact Source-local Floor Plan kitchen assessment.",
                model=model_for_stage("vision"),
                prompt_version=load_prompt("vision").version,
                target_scope=TargetScope.FLOOR_PLAN,
                floor_plan_ref=ref,
                applicability=UnitApplicability.SPECIFIC_FLOOR_PLANS,
                origin_key=origin,
                resolution_rule="vision_weighted_median_exact",
                image_hashes=list(aggregate.hashes),
            )
        )
    state.source_claims.extend(claims)
    state.resolved_claims.extend(claim.model_copy(deep=True) for claim in claims)
    return state
