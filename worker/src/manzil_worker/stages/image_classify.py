"""Cheap all-gallery classification and deterministic quality-target selection."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

import structlog
from manzil_shared.config import (
    DIAGRAM_NORMALIZATION_PROFILE,
    IMAGE_CLASSIFY_ANOMALY_TOLERANCE,
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
from manzil_worker.state import PropertyImageIn, RunState, StageWarning
from manzil_worker.vision_onnx import (
    ONNX_SHADOW_CACHE_KEY,
    ONNXShadowBatch,
    ONNXShadowPrediction,
)
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


CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}

# Scenes that are containers rather than claims: a specific room recognised
# where the other reading said "living" or "other" is the same picture read more
# sharply, not a contradiction (open-plan kitchens produce exactly this).
_GENERIC_SCENES = {"other", "living"}
_INTERIOR_SCENES = {"kitchen", "bathroom", "bedroom", "living"}


class ClassificationBatch(BaseModel):
    """What one classifier response actually yielded, after reconciliation.

    `resolved` is the usable classification per requested hash; `missing`,
    `disputed`, and `surplus` are the tolerated anomalies the stage turns into
    task-card warnings.
    """

    resolved: dict[str, ImageClassification] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    disputed: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)
    repeats: int = 0


def _sharper(left: ImageClassification, right: ImageClassification) -> ImageClassification | None:
    """The sharper of two readings of one image, or None when they truly disagree.

    A diagram claim flips the image's `kind` and removes it from every quality
    path, so a disagreement about it is never reconciled away.
    """
    if left.diagram != right.diagram or left.irrelevant != right.irrelevant:
        return None
    if left.primary_scene == right.primary_scene:
        return left  # same picture, same verdict — the first reading stands
    scenes = {left.primary_scene, right.primary_scene}
    if not scenes & _GENERIC_SCENES:
        return None  # two positive, incompatible claims — e.g. kitchen vs exterior
    if "other" in scenes:  # the catch-all loses to any real scene
        return left if right.primary_scene == "other" else right
    if scenes <= _INTERIOR_SCENES:  # living vs a specific room inside it
        return left if right.primary_scene == "living" else right
    return None  # e.g. living vs exterior — same generality, different picture


def _reconcile_repeats(records: list[ImageClassification]) -> ImageClassification | None:
    """Fold repeated readings of one hash into one, or None when disputed.

    Confidence decides first — a `high` reading beats a `medium` one outright.
    Only a tie falls through to the content of the two classifications.
    """
    winner = records[0]
    for record in records[1:]:
        by_confidence = CONFIDENCE_RANK[record.confidence] - CONFIDENCE_RANK[winner.confidence]
        if by_confidence > 0:
            winner = record
        elif by_confidence == 0:
            sharper = _sharper(winner, record)
            if sharper is None:
                return None
            winner = sharper
    return winner


def reconcile_classification_batch(
    requested: list[str], assessments: list[ImageClassification]
) -> ClassificationBatch:
    """Reconcile a classifier response against the hashes it was asked about.

    The strict contract (every requested hash exactly once, nothing else) is
    what we want and what the prompt asks for, but no benched model holds it
    across a 30-image batch (DESIGN §20 2026-07-28). So a *small* shortfall
    degrades instead of failing: up to `IMAGE_CLASSIFY_ANOMALY_TOLERANCE`
    unanswered hashes and as many surplus records are tolerated and reported.
    Past that the response is malformed, not lossy, and the stage still fails
    closed rather than persist evidence from a call that went wrong.
    """
    wanted = set(requested)
    grouped: dict[str, list[ImageClassification]] = {}
    unknown: list[str] = []
    for assessment in assessments:
        if assessment.content_hash in wanted:
            grouped.setdefault(assessment.content_hash, []).append(assessment)
        else:
            unknown.append(assessment.content_hash)

    missing = [content_hash for content_hash in requested if content_hash not in grouped]
    repeats = sum(len(records) - 1 for records in grouped.values())
    surplus = len(unknown) + repeats
    if (
        len(missing) > IMAGE_CLASSIFY_ANOMALY_TOLERANCE
        or surplus > IMAGE_CLASSIFY_ANOMALY_TOLERANCE
    ):
        raise ValueError(
            "IMAGE_CLASSIFY response is malformed beyond tolerance: "
            f"{len(missing)} of {len(requested)} requested hashes unanswered, "
            f"{len(unknown)} unknown and {repeats} repeated records "
            f"(tolerance {IMAGE_CLASSIFY_ANOMALY_TOLERANCE} each)"
        )

    batch = ClassificationBatch(missing=missing, unknown=unknown, repeats=repeats)
    for content_hash, records in grouped.items():
        winner = records[0] if len(records) == 1 else _reconcile_repeats(records)
        if winner is None:
            batch.disputed.append(content_hash)
        else:
            batch.resolved[content_hash] = winner
    return batch


def _classification_warnings(
    *,
    requested: int,
    unanswered: list[str],
    disputed: list[str],
    unknown: int,
    repeats: int,
) -> list[StageWarning]:
    """One task-card line per kind of anomaly the batch survived."""
    warnings: list[StageWarning] = []
    if unanswered:
        warnings.append(
            StageWarning(
                stage="IMAGE_CLASSIFY",
                code="classification_missing",
                message=(
                    f"The classifier skipped {len(unanswered)} of {requested} photos; "
                    "they are marked unclassified and excluded from photo-based ratings."
                ),
                detail={"content_hashes": unanswered},
            )
        )
    if disputed:
        warnings.append(
            StageWarning(
                stage="IMAGE_CLASSIFY",
                code="classification_disputed",
                message=(
                    f"{len(disputed)} of {requested} photos came back with conflicting "
                    "classifications and were excluded from photo-based ratings."
                ),
                detail={"content_hashes": disputed},
            )
        )
    if unknown or repeats:
        warnings.append(
            StageWarning(
                stage="IMAGE_CLASSIFY",
                code="classification_surplus",
                message=(
                    f"The classifier returned {unknown + repeats} extra records "
                    f"for a batch of {requested} photos."
                ),
                detail={"unknown": unknown, "repeated": repeats},
            )
        )
    return warnings


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
    """Canonical ONNX-classified photos that may feed quality VISION.

    Floor Plan diagrams are excluded **categorically** (§7.2, workbook): a
    layout drawing says nothing about finish quality, and letting one through
    would dilute a kitchen or flooring rating with a line drawing. The rule
    lives here rather than in one criterion's selector so `flooring_quality`
    and every later target inherit it instead of re-deriving it.

    `kind` carries deterministic page evidence; ONNX's diagram result is a
    second categorical exclusion. The promoted narrow contract deliberately
    has no invented assessability, framing, relevance, or confidence fields.
    """
    return [
        image
        for image in images
        if image.kind == "listing_photo"
        and (assessment := _onnx_classification(image)) is not None
        and not assessment.diagram_predicted
    ]


def select_kitchen_targets(images: list[PropertyImageIn]) -> list[PropertyImageIn]:
    """Select up to three photos by descending ONNX kitchen probability."""
    eligible = eligible_quality_images(images)
    eligible.sort(
        key=lambda image: (
            -_onnx_classification(image).kitchen_score,  # type: ignore[union-attr]
            image.source_url_page or "",
            image.source_page_order if image.source_page_order is not None else 10**9,
            image.content_hash,
        )
    )
    return eligible[: VISION_TARGET_QUOTAS["kitchen_quality"]]


def select_kitchen_targets_llm_legacy(images: list[PropertyImageIn]) -> list[PropertyImageIn]:
    """Disabled pre-v3.52 selector retained for the historical LLM benchmark."""
    eligible = [
        image
        for image in images
        if image.kind != "floor_plan_diagram"
        and (assessment := _classification(image)) is not None
        and not assessment.diagram
        and not assessment.irrelevant
        and assessment.framing != "unusable"
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


def _onnx_classification(image: PropertyImageIn) -> ONNXShadowPrediction | None:
    payload = (image.vision_assessment or {}).get("classification")
    if not _valid_cached_shadow(payload):
        return None
    try:
        return ONNXShadowPrediction.model_validate(payload["assessment"])
    except (KeyError, TypeError, ValueError):
        return None


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


def _valid_cached_shadow(payload: object) -> bool:
    if not isinstance(payload, dict) or payload.get("cache_key") != ONNX_SHADOW_CACHE_KEY:
        return False
    try:
        ONNXShadowBatch.model_validate(
            {
                "cache_key": payload["cache_key"],
                "backend": payload["backend"],
                "artifact_sha256": payload["artifact_sha256"],
                "kitchen_threshold": payload["kitchen_threshold"],
                "diagram_threshold": payload["diagram_threshold"],
                "elapsed_seconds": 0.0,
                "peak_rss_mb": None,
                "predictions": [payload["assessment"]],
            }
        )
    except (KeyError, TypeError, ValueError):
        return False
    return True


async def _apply_onnx_shadow(
    state: RunState,
    ctx: StageCtx,
    cached: dict[str, dict],
) -> None:
    """Persist observational ONNX readings without influencing pipeline truth."""
    if ctx.image_classify_onnx is None or ctx.image_store is None:
        return

    pending: list[tuple[str, bytes]] = []
    images_by_hash: dict[str, PropertyImageIn] = {}
    try:
        for image in state.property_images[:MAX_IMAGE_CLASSIFY_IMAGES]:
            images_by_hash[image.content_hash] = image
            current = image.vision_assessment or {}
            persisted = cached.get(image.content_hash, {})
            shadow = current.get("classification_shadow")
            if not _valid_cached_shadow(shadow):
                shadow = persisted.get("classification_shadow")
            if _valid_cached_shadow(shadow):
                image.vision_assessment = {
                    **current,
                    "classification_shadow": shadow,
                }
                continue
            normalized = await ctx.image_store.get(image.storage_path)
            pending.append((image.content_hash, classification_thumbnail(normalized)))
        if not pending:
            log.info("image_classify_onnx_shadow_cached", images=len(images_by_hash))
            return

        batch = await ctx.image_classify_onnx(pending)
        if batch.cache_key != ONNX_SHADOW_CACHE_KEY:
            raise ValueError(f"unexpected shadow cache key {batch.cache_key}")
        prediction_by_hash = {
            prediction.content_hash: prediction for prediction in batch.predictions
        }
        requested = {content_hash for content_hash, _ in pending}
        if (
            len(prediction_by_hash) != len(batch.predictions)
            or set(prediction_by_hash) != requested
        ):
            raise ValueError("shadow response hashes do not exactly match the requested images")
    except Exception as error:  # optional evidence must never interrupt the Job
        log.warning("image_classify_onnx_shadow_failed", error=str(error))
        return

    kitchen_disagreements: list[str] = []
    diagram_disagreements: list[str] = []
    for content_hash, prediction in prediction_by_hash.items():
        image = images_by_hash[content_hash]
        authoritative = _classification(image)
        if authoritative is not None:
            if prediction.kitchen_predicted != (authoritative.primary_scene == "kitchen"):
                kitchen_disagreements.append(content_hash)
            if prediction.diagram_predicted != authoritative.diagram:
                diagram_disagreements.append(content_hash)
        image.vision_assessment = {
            **(image.vision_assessment or {}),
            "classification_shadow": {
                "cache_key": batch.cache_key,
                "backend": batch.backend,
                "artifact_sha256": batch.artifact_sha256,
                "kitchen_threshold": batch.kitchen_threshold,
                "diagram_threshold": batch.diagram_threshold,
                "assessment": prediction.model_dump(),
            },
        }
    log.info(
        "image_classify_onnx_shadow_complete",
        classified=len(batch.predictions),
        cached=len(images_by_hash) - len(batch.predictions),
        elapsed_seconds=batch.elapsed_seconds,
        child_peak_rss_mb=batch.peak_rss_mb,
        images_per_second=(len(batch.predictions) / batch.elapsed_seconds)
        if batch.elapsed_seconds > 0
        else None,
        kitchen_disagreements=kitchen_disagreements,
        diagram_disagreements=diagram_disagreements,
    )


async def _image_classify_llm_stage(state: RunState, ctx: StageCtx) -> RunState:
    """Disabled legacy LLM classifier retained for rollback/reference."""
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
    # Classifications from an earlier run under a *different* model/prompt. They
    # are not fresh enough to skip the call, but they are real evidence, so a
    # re-ask the classifier then skips must not throw them away.
    superseded: dict[str, dict] = {}
    for image in state.property_images[:MAX_IMAGE_CLASSIFY_IMAGES]:
        prior_analysis = cached.get(image.content_hash)
        prior = prior_analysis.get("classification") if isinstance(prior_analysis, dict) else None
        if isinstance(prior, dict) and prior.get("cache_key") != cache_key:
            try:
                ImageClassification.model_validate(prior.get("assessment"))
            except (ValueError, TypeError):
                pass
            else:
                superseded[image.content_hash] = prior
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

    warnings: list[StageWarning] = []
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
        batch = reconcile_classification_batch(
            [block.content_hash for block in blocks], result.assessments
        )
        unanswered: list[str] = []
        disputed: list[str] = []
        for (image, _), block in zip(pending, blocks, strict=True):
            resolved = batch.resolved.get(block.content_hash)
            if resolved is None:
                # Unanswered or disputed. Recorded as exactly that — an image the
                # classifier failed on reads differently from one it looked at
                # and found nothing in — and deliberately left un-cache-keyed so
                # the next run asks about it again.
                unresolved = "disputed" if block.content_hash in batch.disputed else "missing"
                (disputed if unresolved == "disputed" else unanswered).append(image.content_hash)
                # A skipped image keeps an older run's classification (this call
                # said nothing about it, so nothing is contradicted) with the
                # skip recorded beside it — the retained assessment's own
                # model/prompt provenance stays intact. A disputed image does
                # not: two current readings conflict, and that is the one case
                # where stale evidence must not settle it. With no `assessment`,
                # every quality path skips it (`eligible_quality_images`).
                prior = superseded.get(image.content_hash) if unresolved == "missing" else None
                classification = (
                    {**prior, "status": unresolved, "unanswered_by": model}
                    if prior is not None
                    else {
                        "status": unresolved,
                        "model": model,
                        "prompt_version": prompt.version,
                    }
                )
                image.vision_assessment = {
                    **(image.vision_assessment or {}),
                    "classification": classification,
                }
                continue
            # The transport hash authenticates the in-memory thumbnail bytes;
            # cache and selection remain keyed to the normalized Property image.
            assessment = resolved.model_copy(update={"content_hash": image.content_hash})
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
        warnings.extend(
            _classification_warnings(
                requested=len(blocks),
                unanswered=unanswered,
                disputed=disputed,
                unknown=len(batch.unknown),
                repeats=batch.repeats,
            )
        )
    state.replace_warnings("IMAGE_CLASSIFY", warnings)

    await _renormalize_late_diagrams(state, ctx)
    await _apply_onnx_shadow(state, ctx, cached)

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


def _canonical_onnx_record(
    batch: ONNXShadowBatch, prediction: ONNXShadowPrediction
) -> dict[str, object]:
    return {
        "cache_key": batch.cache_key,
        "backend": batch.backend,
        "artifact_sha256": batch.artifact_sha256,
        "kitchen_threshold": batch.kitchen_threshold,
        "diagram_threshold": batch.diagram_threshold,
        "assessment": prediction.model_dump(),
    }


def _promote_cached_onnx(
    image: PropertyImageIn, analysis: dict[str, object], record: dict[str, object]
) -> None:
    legacy = analysis.get("classification")
    if _classification(image) is not None and "classification_llm_legacy" not in analysis:
        analysis["classification_llm_legacy"] = legacy
    analysis["classification"] = record
    analysis.pop("classification_shadow", None)
    image.vision_assessment = analysis
    prediction = ONNXShadowPrediction.model_validate(record["assessment"])
    if prediction.diagram_predicted:
        image.kind = "floor_plan_diagram"


async def image_classify_stage(state: RunState, ctx: StageCtx) -> RunState:
    """Classify gallery images exclusively with the canonical ONNX backend."""
    if not state.property_images or state.property_id is None or ctx.image_store is None:
        state.vision_targets["kitchen_quality"] = []
        if state.plan is not None:
            state.plan.skipped["VISION"] = "no_classified_kitchen_targets"
        return state
    if ctx.image_classify_onnx is None:
        raise RuntimeError(
            "IMAGE_CLASSIFY requires MANZIL_IMAGE_CLASSIFY_ONNX_DIR "
            "(legacy alias MANZIL_IMAGE_CLASSIFY_ONNX_SHADOW_DIR is also accepted)"
        )

    cached = await ctx.existing_image_classifications(state.property_id)
    pending: list[tuple[str, bytes]] = []
    images_by_hash: dict[str, PropertyImageIn] = {}
    for image in state.property_images[:MAX_IMAGE_CLASSIFY_IMAGES]:
        images_by_hash[image.content_hash] = image
        persisted = cached.get(image.content_hash, {})
        analysis: dict[str, object] = {
            **persisted,
            **(image.vision_assessment or {}),
        }
        candidates = (
            analysis.get("classification"),
            analysis.get("classification_shadow"),
        )
        record = next(
            (candidate for candidate in candidates if _valid_cached_shadow(candidate)), None
        )
        if isinstance(record, dict):
            image.vision_assessment = analysis
            _promote_cached_onnx(image, analysis, record)
            continue
        normalized = await ctx.image_store.get(image.storage_path)
        pending.append((image.content_hash, classification_thumbnail(normalized)))

    classified = 0
    if pending:
        batch = await ctx.image_classify_onnx(pending)
        if batch.cache_key != ONNX_SHADOW_CACHE_KEY:
            raise ValueError(f"unexpected ONNX cache key {batch.cache_key}")
        prediction_by_hash = {
            prediction.content_hash: prediction for prediction in batch.predictions
        }
        requested = {content_hash for content_hash, _ in pending}
        if (
            len(prediction_by_hash) != len(batch.predictions)
            or set(prediction_by_hash) != requested
        ):
            raise ValueError("ONNX response hashes do not exactly match the requested images")
        for content_hash, prediction in prediction_by_hash.items():
            image = images_by_hash[content_hash]
            analysis = dict(image.vision_assessment or {})
            if _classification(image) is not None and "classification_llm_legacy" not in analysis:
                analysis["classification_llm_legacy"] = analysis.get("classification")
            _promote_cached_onnx(image, analysis, _canonical_onnx_record(batch, prediction))
        classified = len(batch.predictions)
        log.info(
            "image_classify_onnx_complete",
            classified=classified,
            cached=len(images_by_hash) - classified,
            elapsed_seconds=batch.elapsed_seconds,
            child_peak_rss_mb=batch.peak_rss_mb,
            images_per_second=(classified / batch.elapsed_seconds)
            if batch.elapsed_seconds > 0
            else None,
        )
    else:
        log.info("image_classify_onnx_cached", images=len(images_by_hash))

    state.replace_warnings("IMAGE_CLASSIFY", [])
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
        prior_digests = {
            ((image.vision_assessment or {}).get("kitchen_quality") or {}).get("input_digest")
            for image in selected
        }
        if prior_digests == {digest} and state.plan is not None:
            state.plan.skipped["VISION"] = "quality_inputs_unchanged"
    return state
