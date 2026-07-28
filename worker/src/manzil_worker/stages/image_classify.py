"""Cheap all-gallery classification and deterministic quality-target selection."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

import structlog
from manzil_shared.config import (
    DIAGRAM_NORMALIZATION_PROFILE,
    IMAGE_PERCEPTUAL_HASH_DISTANCE,
    MAX_IMAGE_CLASSIFY_IMAGES,
    VISION_TARGET_QUOTAS,
)
from manzil_shared.errors import PrivateAddressRefused
from pydantic import BaseModel, Field

from manzil_worker.enrich.images import (
    ImageError,
    classification_thumbnail,
    difference_hash,
    download_image,
    normalize_diagram,
)
from manzil_worker.llm import VisionImage
from manzil_worker.llm.config import model_for_stage
from manzil_worker.llm.prompt_loader import load_prompt
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import PropertyImageIn, RunState
from manzil_worker.vision_refs import load_reference_manifest, vision_references_ready

log = structlog.get_logger()


class ImageClassification(BaseModel):
    content_hash: str
    primary_scene: Literal[
        "kitchen", "bathroom", "living", "bedroom", "exterior", "amenity", "diagram", "other"
    ]
    kitchen_visibility: Literal["assessable", "partial", "not_visible"]
    flooring_assessability: Literal["assessable", "partial", "not_visible"]
    bathroom_visibility: Literal["assessable", "partial", "not_visible"]
    framing: Literal["full_room", "partial_room", "detail", "unusable"]
    confidence: Literal["high", "medium", "low"]
    irrelevant: bool
    diagram: bool


class ImageClassificationBatch(BaseModel):
    assessments: list[ImageClassification] = Field(default_factory=list)


def hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _classification(image: PropertyImageIn) -> ImageClassification | None:
    payload = (image.vision_assessment or {}).get("classification")
    if not isinstance(payload, dict):
        return None
    try:
        return ImageClassification.model_validate(payload.get("assessment"))
    except (ValueError, TypeError):
        return None


def eligible_quality_images(images: list[PropertyImageIn]) -> list[PropertyImageIn]:
    """Images that may ever feed a quality-rating VISION target.

    Floor Plan diagrams are excluded **categorically** (§7.2, workbook): a
    layout drawing says nothing about finish quality, and letting one through
    would dilute a kitchen or flooring rating with a line drawing. The rule
    lives here rather than in one criterion's selector so `flooring_quality`
    and every later target inherit it instead of re-deriving it.

    Both signals are honoured: `kind` carries the deterministic pass and any
    persisted classification, `assessment.diagram` the visual one.
    """
    return [
        image
        for image in images
        if image.kind != "floor_plan_diagram"
        and (assessment := _classification(image)) is not None
        and not assessment.diagram
        and not assessment.irrelevant
        and assessment.framing != "unusable"
    ]


def select_kitchen_targets(images: list[PropertyImageIn]) -> list[PropertyImageIn]:
    """Select diverse, assessable kitchens with stable evidence-first ordering."""
    eligible = [
        image
        for image in eligible_quality_images(images)
        if (assessment := _classification(image)) is not None
        and assessment.confidence == "high"
        and assessment.kitchen_visibility == "assessable"
    ]
    framing_rank = {"full_room": 0, "partial_room": 1, "detail": 2, "unusable": 3}
    eligible.sort(
        key=lambda image: (
            0 if image.exact_floor_plan_refs else 1,
            framing_rank[_classification(image).framing],  # type: ignore[union-attr]
            image.source_url_page or "",
            image.source_page_order if image.source_page_order is not None else 10**9,
            image.content_hash,
        )
    )

    selected: list[PropertyImageIn] = []
    covered_plans: set[str] = set()
    remaining = list(eligible)
    while remaining:
        image = min(
            remaining,
            key=lambda candidate: (
                0
                if any(ref not in covered_plans for ref in candidate.exact_floor_plan_refs)
                else 1,
                eligible.index(candidate),
            ),
        )
        remaining.remove(image)
        if image.perceptual_hash and any(
            prior.perceptual_hash
            and hamming_distance(image.perceptual_hash, prior.perceptual_hash)
            <= IMAGE_PERCEPTUAL_HASH_DISTANCE
            for prior in selected
        ):
            continue
        selected.append(image)
        covered_plans.update(image.exact_floor_plan_refs)
        if len(selected) >= VISION_TARGET_QUOTAS["kitchen_quality"]:
            break
    return selected


async def _renormalize_late_diagrams(state: RunState, ctx: StageCtx) -> None:
    """Re-store diagrams the deterministic pass missed at the diagram profile.

    `diagram_signals.looks_like_diagram` catches the explicitly-labelled cases
    before download, so this is the uncommon path: an image the page gave no
    structural or textual evidence for, which the classifier recognised
    visually. It was stored at the 1024 px photo profile, which makes its room
    labels unreadable, so re-fetch the original and re-store it at 2048.

    Failure is not fatal: the photo-profile copy stays, and the association is
    still correct — only legibility is degraded. Losing the image entirely
    would be worse.
    """
    late = [
        image
        for image in state.property_images
        if image.kind == "floor_plan_diagram"
        and image.normalization_profile != DIAGRAM_NORMALIZATION_PROFILE
    ]
    if not late or ctx.image_store is None or state.property_id is None:
        return
    fetch = ctx.download_image or download_image
    for image in late:
        candidate = image.discovery_context.get("full_size_url") or image.source_url
        try:
            normalized = normalize_diagram(await fetch(str(candidate)))
        except (PrivateAddressRefused, ImageError, OSError) as error:
            log.warning(
                "diagram_renormalize_failed",
                url=candidate,
                content_hash=image.content_hash,
                error=str(error),
            )
            continue
        path = f"properties/{state.property_id}/{normalized.content_hash}.webp"
        try:
            await ctx.image_store.put(path, normalized.webp)
        except Exception as error:  # degrade to the photo copy, never lose the image
            log.warning("diagram_renormalize_upload_failed", path=path, error=str(error))
            continue
        image.storage_path = path
        image.content_hash = normalized.content_hash
        image.width = normalized.width
        image.height = normalized.height
        image.byte_size = len(normalized.webp)
        image.perceptual_hash = difference_hash(normalized.webp)
        image.normalization_profile = DIAGRAM_NORMALIZATION_PROFILE


async def image_classify_stage(state: RunState, ctx: StageCtx) -> RunState:
    if not state.property_images or state.property_id is None or ctx.image_store is None:
        state.vision_targets["kitchen_quality"] = []
        if state.plan is not None:
            state.plan.skipped["VISION"] = "no_classified_kitchen_targets"
        return state

    prompt = load_prompt("image_classify")
    model = model_for_stage("image_classify")
    cache_key = f"{model}:prompt-{prompt.version}"
    cached = await ctx.existing_image_classifications(state.property_id)
    pending: list[tuple[PropertyImageIn, bytes]] = []
    for image in state.property_images[:MAX_IMAGE_CLASSIFY_IMAGES]:
        prior_analysis = cached.get(image.content_hash)
        prior = prior_analysis.get("classification") if isinstance(prior_analysis, dict) else None
        if isinstance(prior, dict) and prior.get("cache_key") == cache_key:
            image.vision_assessment = dict(prior_analysis)
            cached_assessment = ImageClassification.model_validate(prior.get("assessment"))
            if cached_assessment.diagram:
                image.kind = "floor_plan_diagram"
            elif cached_assessment.irrelevant:
                image.kind = "other"
            continue
        normalized = await ctx.image_store.get(image.storage_path)
        pending.append((image, classification_thumbnail(normalized)))

    if pending:
        blocks = [
            VisionImage(
                content_hash=hashlib.sha256(thumbnail).hexdigest(),
                data=thumbnail,
                label=f"target:{image.content_hash}",
            )
            for image, thumbnail in pending
        ]
        result = await ctx.call_vision("image_classify", ImageClassificationBatch, blocks)
        requested = [block.content_hash for block in blocks]
        returned = [assessment.content_hash for assessment in result.assessments]
        if len(returned) != len(set(returned)) or set(returned) != set(requested):
            raise ValueError("IMAGE_CLASSIFY must return every requested hash exactly once")
        by_hash = {assessment.content_hash: assessment for assessment in result.assessments}
        for (image, _), block in zip(pending, blocks, strict=True):
            # The transport hash authenticates the in-memory thumbnail bytes;
            # cache and selection remain keyed to the normalized Property image.
            assessment = by_hash[block.content_hash].model_copy(
                update={"content_hash": image.content_hash}
            )
            if assessment.diagram:
                image.kind = "floor_plan_diagram"
            elif assessment.irrelevant:
                image.kind = "other"
            image.vision_assessment = {
                **(image.vision_assessment or {}),
                "classification": {
                    "cache_key": cache_key,
                    "model": model,
                    "prompt_version": prompt.version,
                    "assessment": assessment.model_dump(),
                },
            }

    await _renormalize_late_diagrams(state, ctx)

    selected = select_kitchen_targets(state.property_images)
    state.vision_targets["kitchen_quality"] = [image.content_hash for image in selected]
    if not selected and state.plan is not None:
        state.plan.skipped["VISION"] = "no_classified_kitchen_targets"
    elif selected and vision_references_ready(criterion="kitchen_quality"):
        manifest = load_reference_manifest(criterion="kitchen_quality")
        assert manifest is not None
        profile = manifest["profiles"]["kitchen_quality"]
        quality_prompt = load_prompt("vision")
        digest = hashlib.sha256(
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
                    "prompt_version": quality_prompt.version,
                    "reference_version": profile["version"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if (
            all(
                (image.vision_assessment or {}).get("kitchen_quality", {}).get("input_digest")
                == digest
                for image in selected
            )
            and state.plan is not None
        ):
            state.plan.skipped["VISION"] = "quality_inputs_unchanged"
    return state
