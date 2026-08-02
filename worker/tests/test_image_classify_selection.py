from __future__ import annotations

import asyncio
import io
from uuid import uuid4

import pytest
from manzil_shared.config import DIAGRAM_MAX_DIM, DIAGRAM_NORMALIZATION_PROFILE
from manzil_shared.models import JobState, JobType
from manzil_worker.llm.config import model_for_stage
from manzil_worker.llm.prompt_loader import load_prompt
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.image_classify import (
    ImageClassification,
    ImageClassificationBatch,
    image_classify_stage,
    reconcile_classification_batch,
    select_kitchen_targets,
)
from manzil_worker.stages.vision import KitchenAssessment, aggregate_kitchen
from manzil_worker.state import PropertyImageIn, RunState, StageWarning
from manzil_worker.vision_onnx import (
    ONNX_SHADOW_ARTIFACT_SHA256,
    ONNX_SHADOW_BACKEND,
    ONNX_SHADOW_CACHE_KEY,
    ONNX_SHADOW_DIAGRAM_THRESHOLD,
    ONNX_SHADOW_KITCHEN_THRESHOLD,
    ONNXShadowBatch,
    ONNXShadowPrediction,
)
from PIL import Image


def _image(
    digest: str,
    *,
    phash: str,
    scene: str = "kitchen",
    visibility: str = "assessable",
    confidence: str = "high",
    framing: str = "full_room",
    diagram: bool = False,
    plan: str | None = None,
    order: int = 0,
) -> PropertyImageIn:
    assessment = {
        "content_hash": digest,
        "primary_scene": scene,
        "kitchen_visibility": visibility,
        "flooring_assessability": "assessable",
        "bathroom_visibility": "not_visible",
        "framing": framing,
        "confidence": confidence,
        "irrelevant": False,
        "diagram": diagram,
    }
    return PropertyImageIn(
        source_url=f"https://images.test/{digest}",
        storage_path=f"properties/p/{digest}.webp",
        content_hash=digest,
        width=100,
        height=100,
        byte_size=100,
        perceptual_hash=phash,
        source_url_page="https://listing.test",
        source_page_order=order,
        exact_floor_plan_refs=[plan] if plan else [],
        vision_assessment={
            "classification": {
                "cache_key": "model:prompt-1",
                "assessment": assessment,
            }
        },
    )


def test_selector_excludes_diagrams_and_near_duplicates_and_covers_plans() -> None:
    images = [
        _image("a" * 64, phash="0000000000000000", plan="plan-a", order=0),
        _image("b" * 64, phash="0000000000000001", plan="plan-a", order=1),
        _image("c" * 64, phash="ffffffffffffffff", plan="plan-b", order=2),
        _image("d" * 64, phash="0f0f0f0f0f0f0f0f", diagram=True, order=3),
        _image("e" * 64, phash="f0f0f0f0f0f0f0f0", order=4),
    ]
    selected = select_kitchen_targets(images)
    assert [image.content_hash for image in selected] == ["a" * 64, "c" * 64, "e" * 64]


def test_weighted_median_tie_chooses_lower_and_spread_guard() -> None:
    tied = [
        KitchenAssessment(
            content_hash="a" * 64,
            visibility="visible",
            rating=2,
            confidence="high",
            rationale="visible",
        ),
        KitchenAssessment(
            content_hash="b" * 64,
            visibility="visible",
            rating=4,
            confidence="high",
            rationale="visible",
        ),
    ]
    aggregate = aggregate_kitchen(tied)
    assert aggregate is not None
    assert aggregate.rating == 2
    assert aggregate.confidence.value == "medium"

    spread = [
        tied[0],
        KitchenAssessment(
            content_hash="c" * 64,
            visibility="visible",
            rating=5,
            confidence="medium",
            rationale="visible",
        ),
    ]
    assert aggregate_kitchen(spread) is None


def test_unchanged_classifier_cache_makes_zero_calls_and_reads() -> None:
    image = _image("a" * 64, phash="0" * 16)
    cached = image.vision_assessment
    assert cached is not None
    cached["classification"]["cache_key"] = (
        f"{model_for_stage('image_classify')}:prompt-{load_prompt('image_classify').version}"
    )
    image.vision_assessment = None
    state = RunState(
        job_id=uuid4(),
        job_type=JobType.INGEST,
        url="https://listing.test",
        property_id=uuid4(),
        property_images=[image],
    )

    class Store:
        async def get(self, path: str) -> bytes:
            raise AssertionError("cached classification must not read Storage")

        async def put(self, path: str, content: bytes) -> None:
            raise AssertionError("classifier never writes derivatives")

    async def existing(property_id):  # type: ignore[no-untyped-def]
        return {image.content_hash: cached}

    async def call(*args):  # type: ignore[no-untyped-def]
        raise AssertionError("cached classification must make zero model calls")

    out = asyncio.run(
        image_classify_stage(
            state,
            StageCtx(
                image_store=Store(),
                existing_image_classifications=existing,
                call_vision=call,
            ),
        )
    )
    assert out.vision_targets == {"kitchen_quality": [image.content_hash]}


def test_classifier_maps_thumbnail_response_hash_back_to_property_image_hash() -> None:
    image = _image("a" * 64, phash="0" * 16)
    image.vision_assessment = None
    output = io.BytesIO()
    Image.new("RGB", (24, 24), (200, 20, 20)).save(output, format="WEBP")

    class Store:
        async def get(self, path: str) -> bytes:
            return output.getvalue()

        async def put(self, path: str, content: bytes) -> None:
            raise AssertionError("classifier never writes derivatives")

    async def call(stage, schema, blocks):  # type: ignore[no-untyped-def]
        assert stage == "image_classify"
        assert schema is ImageClassificationBatch
        return ImageClassificationBatch(
            assessments=[
                ImageClassification(
                    content_hash=blocks[0].content_hash,
                    primary_scene="kitchen",
                    kitchen_visibility="assessable",
                    flooring_assessability="not_visible",
                    bathroom_visibility="not_visible",
                    framing="full_room",
                    confidence="high",
                    irrelevant=False,
                    diagram=False,
                )
            ]
        )

    state = RunState(
        job_id=uuid4(),
        job_type=JobType.INGEST,
        url="https://listing.test",
        property_id=uuid4(),
        property_images=[image],
    )
    out = asyncio.run(image_classify_stage(state, StageCtx(image_store=Store(), call_vision=call)))
    assessment = out.property_images[0].vision_assessment["classification"]["assessment"]
    assert assessment["content_hash"] == image.content_hash


# --- P3-SC5: the LLM fallback re-stores its diagrams at the diagram profile ---


def _classify_batch(*, diagram: bool):
    async def call(stage, schema, blocks):  # type: ignore[no-untyped-def]
        return ImageClassificationBatch(
            assessments=[
                ImageClassification(
                    content_hash=block.content_hash,
                    primary_scene="diagram" if diagram else "kitchen",
                    kitchen_visibility="not_visible" if diagram else "assessable",
                    flooring_assessability="not_visible",
                    bathroom_visibility="not_visible",
                    framing="full_room",
                    confidence="high",
                    irrelevant=False,
                    diagram=diagram,
                )
                for block in blocks
            ]
        )

    return call


def _thumb() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (2400, 1600), (240, 240, 240)).save(output, format="PNG")
    return output.getvalue()


def test_diagram_found_only_by_the_classifier_is_restored_at_the_diagram_profile() -> None:
    """The deterministic pass missed it, so it is sitting at the photo profile."""
    image = _image("a" * 64, phash="0" * 16, scene="diagram")
    image.vision_assessment = None
    image.source_url = "https://img.test/plan.png"
    raw = _thumb()

    class Store:
        def __init__(self) -> None:
            self.written: dict[str, bytes] = {}

        async def get(self, path: str) -> bytes:
            return raw

        async def put(self, path: str, content: bytes) -> None:
            self.written[path] = content

    async def fetch(url: str) -> bytes:
        assert url == "https://img.test/plan.png"
        return raw

    store = Store()
    state = RunState(
        job_id=uuid4(),
        job_type=JobType.INGEST,
        url="https://listing.test",
        property_id=uuid4(),
        property_images=[image],
    )
    out = asyncio.run(
        image_classify_stage(
            state,
            StageCtx(
                image_store=store,
                call_vision=_classify_batch(diagram=True),
                download_image=fetch,
            ),
        )
    )
    stored = out.property_images[0]
    assert stored.kind == "floor_plan_diagram"
    assert stored.normalization_profile == DIAGRAM_NORMALIZATION_PROFILE
    assert stored.width == DIAGRAM_MAX_DIM
    assert store.written  # the larger asset was uploaded


def test_failed_renormalization_keeps_the_photo_profile_copy() -> None:
    """Degrade legibility, never lose the image or its association."""
    image = _image("a" * 64, phash="0" * 16, scene="diagram")
    image.vision_assessment = None
    original_path = image.storage_path
    raw = _thumb()

    class Store:
        async def get(self, path: str) -> bytes:
            return raw

        async def put(self, path: str, content: bytes) -> None:
            raise AssertionError("upload must not be reached")

    async def fetch(url: str) -> bytes:
        raise OSError("origin gone")

    state = RunState(
        job_id=uuid4(),
        job_type=JobType.INGEST,
        url="https://listing.test",
        property_id=uuid4(),
        property_images=[image],
    )
    out = asyncio.run(
        image_classify_stage(
            state,
            StageCtx(
                image_store=Store(),
                call_vision=_classify_batch(diagram=True),
                download_image=fetch,
            ),
        )
    )
    stored = out.property_images[0]
    assert stored.kind == "floor_plan_diagram"
    assert stored.storage_path == original_path
    assert stored.normalization_profile != DIAGRAM_NORMALIZATION_PROFILE


def test_non_diagram_images_are_never_renormalized() -> None:
    image = _image("a" * 64, phash="0" * 16)
    image.vision_assessment = None
    raw = _thumb()

    class Store:
        async def get(self, path: str) -> bytes:
            return raw

        async def put(self, path: str, content: bytes) -> None:
            raise AssertionError("a photo must not be re-stored")

    async def fetch(url: str) -> bytes:
        raise AssertionError("a photo must not be re-downloaded")

    state = RunState(
        job_id=uuid4(),
        job_type=JobType.INGEST,
        url="https://listing.test",
        property_id=uuid4(),
        property_images=[image],
    )
    out = asyncio.run(
        image_classify_stage(
            state,
            StageCtx(
                image_store=Store(),
                call_vision=_classify_batch(diagram=False),
                download_image=fetch,
            ),
        )
    )
    assert out.property_images[0].kind == "listing_photo"


# --- Tolerant batch reconciliation (DESIGN §20 2026-07-28, §10.8) ------------


def _assessment(digest: str, **overrides) -> ImageClassification:  # type: ignore[no-untyped-def]
    fields = {
        "content_hash": digest,
        "primary_scene": "kitchen",
        "kitchen_visibility": "assessable",
        "flooring_assessability": "assessable",
        "bathroom_visibility": "not_visible",
        "framing": "full_room",
        "confidence": "high",
        "irrelevant": False,
        "diagram": False,
    }
    return ImageClassification.model_validate({**fields, **overrides})


def test_reconcile_tolerates_two_missing_and_two_surplus_records() -> None:
    requested = [f"{n:064d}" for n in range(30)]
    returned = [_assessment(digest) for digest in requested[2:]]
    returned.append(_assessment("f" * 64))  # unknown hash
    returned.append(_assessment(requested[5]))  # repeat

    batch = reconcile_classification_batch(requested, returned)
    assert batch.missing == requested[:2]
    assert batch.unknown == ["f" * 64]
    assert batch.repeats == 1
    assert batch.disputed == []
    assert set(batch.resolved) == set(requested[2:])


def test_reconcile_fails_closed_past_the_tolerance() -> None:
    requested = [f"{n:064d}" for n in range(30)]
    with pytest.raises(ValueError, match="malformed beyond tolerance"):
        reconcile_classification_batch(requested, [_assessment(d) for d in requested[3:]])

    surplus = [_assessment(d) for d in requested] + [
        _assessment(f"{n:064x}") for n in range(900, 903)
    ]
    with pytest.raises(ValueError, match="malformed beyond tolerance"):
        reconcile_classification_batch(requested, surplus)


def test_repeated_hash_resolves_to_the_more_confident_reading() -> None:
    digest = "a" * 64
    batch = reconcile_classification_batch(
        [digest],
        [
            _assessment(digest, primary_scene="living", confidence="medium"),
            _assessment(digest, primary_scene="bedroom", confidence="high"),
        ],
    )
    assert batch.resolved[digest].primary_scene == "bedroom"
    assert batch.repeats == 1


def test_tied_repeat_prefers_the_more_specific_scene() -> None:
    digest = "a" * 64
    for generic in ("living", "other"):
        batch = reconcile_classification_batch(
            [digest],
            [
                _assessment(digest, primary_scene=generic),
                _assessment(digest, primary_scene="kitchen"),
            ],
        )
        assert batch.resolved[digest].primary_scene == "kitchen"
        assert batch.disputed == []


def test_tied_repeat_with_incompatible_scenes_is_disputed() -> None:
    digest = "a" * 64
    for left, right in (("kitchen", "exterior"), ("living", "exterior"), ("bathroom", "bedroom")):
        batch = reconcile_classification_batch(
            [digest],
            [_assessment(digest, primary_scene=left), _assessment(digest, primary_scene=right)],
        )
        assert batch.disputed == [digest]
        assert batch.resolved == {}


def test_tied_repeat_disagreeing_about_a_diagram_is_disputed() -> None:
    digest = "a" * 64
    batch = reconcile_classification_batch(
        [digest],
        [
            _assessment(digest, primary_scene="other"),
            _assessment(digest, primary_scene="diagram", diagram=True),
        ],
    )
    assert batch.disputed == [digest]


def _stage_state(images: list[PropertyImageIn]) -> RunState:
    return RunState(
        job_id=uuid4(),
        job_type=JobType.INGEST,
        url="https://listing.test",
        property_id=uuid4(),
        property_images=images,
    )


def test_stage_marks_skipped_and_disputed_images_and_warns_without_halting() -> None:
    """A slightly-lossy batch degrades: the run finishes, the card says so."""
    answered, skipped, disputed = ("a" * 64, "b" * 64, "c" * 64)
    images = [
        _image(digest, phash=f"{i:016x}") for i, digest in enumerate((answered, skipped, disputed))
    ]
    for image in images:
        image.vision_assessment = None

    class Store:
        # Distinct pixels per image, so the thumbnails hash distinctly too.
        async def get(self, path: str) -> bytes:
            output = io.BytesIO()
            shade = (sum(path.encode()) % 200) + 20
            Image.new("RGB", (48, 48), (shade, shade, shade)).save(output, format="PNG")
            return output.getvalue()

        async def put(self, path: str, content: bytes) -> None:
            raise AssertionError("classifier never writes derivatives")

    async def call(stage, schema, blocks):  # type: ignore[no-untyped-def]
        by_label = {block.label: block.content_hash for block in blocks}
        contested = by_label[f"target:{disputed}"]
        return ImageClassificationBatch(
            assessments=[
                _assessment(by_label[f"target:{answered}"]),
                # No record at all for `skipped`, and two irreconcilable ones
                # at equal confidence for `disputed`.
                _assessment(contested, primary_scene="kitchen"),
                _assessment(contested, primary_scene="exterior", kitchen_visibility="not_visible"),
            ]
        )

    out = asyncio.run(
        image_classify_stage(_stage_state(images), StageCtx(image_store=Store(), call_vision=call))
    )

    stored = {
        image.content_hash: image.vision_assessment["classification"]
        for image in out.property_images
    }
    assert stored[answered]["assessment"]["primary_scene"] == "kitchen"
    assert stored[skipped]["status"] == "missing"
    assert stored[disputed]["status"] == "disputed"
    # Neither marker is cache-keyed, so the next run asks about them again.
    assert "cache_key" not in stored[skipped] and "cache_key" not in stored[disputed]
    # Only the cleanly classified image can carry a quality rating.
    assert out.vision_targets == {"kitchen_quality": [answered]}
    assert out.status is JobState.RUNNING and out.error is None

    codes = {warning.code: warning for warning in out.warnings}
    assert set(codes) == {
        "classification_missing",
        "classification_disputed",
        "classification_surplus",
    }
    assert codes["classification_missing"].detail["content_hashes"] == [skipped]
    assert codes["classification_disputed"].detail["content_hashes"] == [disputed]
    assert all(warning.stage == "IMAGE_CLASSIFY" for warning in out.warnings)


def test_a_clean_batch_leaves_no_warnings_and_a_rerun_replaces_them() -> None:
    image = _image("a" * 64, phash="0" * 16)
    image.vision_assessment = None
    raw = _thumb()

    class Store:
        async def get(self, path: str) -> bytes:
            return raw

        async def put(self, path: str, content: bytes) -> None:
            raise AssertionError("classifier never writes derivatives")

    state = _stage_state([image])
    # A stale warning from an earlier attempt at this stage must not survive.
    state.warnings = [
        StageWarning(stage="IMAGE_CLASSIFY", code="classification_missing", message="old"),
        StageWarning(stage="FETCH", code="other_stage", message="kept"),
    ]
    out = asyncio.run(
        image_classify_stage(
            state, StageCtx(image_store=Store(), call_vision=_classify_batch(diagram=False))
        )
    )
    assert [warning.code for warning in out.warnings] == ["other_stage"]


def test_a_skipped_image_keeps_the_classification_an_earlier_run_earned() -> None:
    """The call said nothing about it, so it contradicts nothing."""
    image = _image("a" * 64, phash="0" * 16)
    prior = dict(image.vision_assessment["classification"])
    image.vision_assessment = None
    raw = _thumb()

    class Store:
        async def get(self, path: str) -> bytes:
            return raw

        async def put(self, path: str, content: bytes) -> None:
            raise AssertionError("classifier never writes derivatives")

    async def existing(property_id):  # type: ignore[no-untyped-def]
        # Cached under an older model/prompt, so the stage re-asks.
        return {image.content_hash: {"classification": prior}}

    async def call(stage, schema, blocks):  # type: ignore[no-untyped-def]
        return ImageClassificationBatch(assessments=[])  # answered nothing

    out = asyncio.run(
        image_classify_stage(
            _stage_state([image]),
            StageCtx(
                image_store=Store(), existing_image_classifications=existing, call_vision=call
            ),
        )
    )
    stored = out.property_images[0].vision_assessment["classification"]
    assert stored["status"] == "missing"
    assert stored["assessment"] == prior["assessment"]  # evidence survives the skip
    assert stored["cache_key"] == prior["cache_key"]  # ...and re-asks next run
    assert out.vision_targets == {"kitchen_quality": ["a" * 64]}
    assert [warning.code for warning in out.warnings] == ["classification_missing"]


def _shadow_batch(
    content_hash: str,
    *,
    scene: str = "bathroom",
    kitchen: bool = False,
    diagram: bool = True,
) -> ONNXShadowBatch:
    return ONNXShadowBatch(
        cache_key=ONNX_SHADOW_CACHE_KEY,
        backend=ONNX_SHADOW_BACKEND,
        artifact_sha256=ONNX_SHADOW_ARTIFACT_SHA256,
        kitchen_threshold=ONNX_SHADOW_KITCHEN_THRESHOLD,
        diagram_threshold=ONNX_SHADOW_DIAGRAM_THRESHOLD,
        elapsed_seconds=1.25,
        predictions=[
            ONNXShadowPrediction(
                content_hash=content_hash,
                predicted_scene=scene,
                kitchen_score=0.1,
                kitchen_predicted=kitchen,
                diagram_score=0.99,
                diagram_predicted=diagram,
            )
        ],
    )


def test_onnx_shadow_persists_disagreement_without_changing_pipeline_truth() -> None:
    image = _image("a" * 64, phash="0" * 16)
    image.vision_assessment = None
    raw = _thumb()

    class Store:
        async def get(self, path: str) -> bytes:
            return raw

        async def put(self, path: str, content: bytes) -> None:
            raise AssertionError("a shadow prediction must not write image derivatives")

    async def shadow(images):  # type: ignore[no-untyped-def]
        assert [content_hash for content_hash, _ in images] == [image.content_hash]
        return _shadow_batch(image.content_hash)

    out = asyncio.run(
        image_classify_stage(
            _stage_state([image]),
            StageCtx(
                image_store=Store(),
                call_vision=_classify_batch(diagram=False),
                image_classify_shadow=shadow,
            ),
        )
    )

    stored = out.property_images[0]
    assert stored.kind == "listing_photo"
    assert out.vision_targets == {"kitchen_quality": [image.content_hash]}
    assert stored.vision_assessment["classification"]["assessment"]["primary_scene"] == "kitchen"
    shadow_record = stored.vision_assessment["classification_shadow"]
    assert shadow_record["cache_key"] == ONNX_SHADOW_CACHE_KEY
    assert shadow_record["assessment"]["predicted_scene"] == "bathroom"
    assert shadow_record["assessment"]["diagram_predicted"] is True


def test_onnx_shadow_cache_avoids_storage_read_and_inference() -> None:
    image = _image("a" * 64, phash="0" * 16)
    current_cache_key = (
        f"{model_for_stage('image_classify')}:prompt-{load_prompt('image_classify').version}"
    )
    image.vision_assessment["classification"]["cache_key"] = current_cache_key
    batch = _shadow_batch(image.content_hash)
    image.vision_assessment["classification_shadow"] = {
        "cache_key": batch.cache_key,
        "backend": batch.backend,
        "artifact_sha256": batch.artifact_sha256,
        "kitchen_threshold": batch.kitchen_threshold,
        "diagram_threshold": batch.diagram_threshold,
        "assessment": batch.predictions[0].model_dump(),
    }
    cached = image.vision_assessment
    image.vision_assessment = None

    class Store:
        async def get(self, path: str) -> bytes:
            raise AssertionError("fresh incumbent and shadow caches must avoid Storage")

        async def put(self, path: str, content: bytes) -> None:
            raise AssertionError("classifier never writes derivatives")

    async def existing(property_id):  # type: ignore[no-untyped-def]
        return {image.content_hash: cached}

    async def call(*args):  # type: ignore[no-untyped-def]
        raise AssertionError("fresh caches must avoid inference")

    out = asyncio.run(
        image_classify_stage(
            _stage_state([image]),
            StageCtx(
                image_store=Store(),
                existing_image_classifications=existing,
                call_vision=call,
                image_classify_shadow=call,
            ),
        )
    )
    assert (
        out.property_images[0].vision_assessment["classification_shadow"]["cache_key"]
        == ONNX_SHADOW_CACHE_KEY
    )


def test_onnx_shadow_failure_does_not_fail_the_job() -> None:
    image = _image("a" * 64, phash="0" * 16)
    image.vision_assessment = None
    raw = _thumb()

    class Store:
        async def get(self, path: str) -> bytes:
            return raw

        async def put(self, path: str, content: bytes) -> None:
            raise AssertionError("classifier never writes derivatives")

    async def shadow(images):  # type: ignore[no-untyped-def]
        raise RuntimeError("optional backend unavailable")

    out = asyncio.run(
        image_classify_stage(
            _stage_state([image]),
            StageCtx(
                image_store=Store(),
                call_vision=_classify_batch(diagram=False),
                image_classify_shadow=shadow,
            ),
        )
    )
    assert out.status is JobState.RUNNING
    assert out.vision_targets == {"kitchen_quality": [image.content_hash]}
    assert "classification_shadow" not in out.property_images[0].vision_assessment
