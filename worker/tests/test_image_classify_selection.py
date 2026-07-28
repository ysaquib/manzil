from __future__ import annotations

import asyncio
import io
from uuid import uuid4

from manzil_shared.config import DIAGRAM_MAX_DIM, DIAGRAM_NORMALIZATION_PROFILE
from manzil_shared.models import JobType
from manzil_worker.llm.config import model_for_stage
from manzil_worker.llm.prompt_loader import load_prompt
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.image_classify import (
    ImageClassification,
    ImageClassificationBatch,
    image_classify_stage,
    select_kitchen_targets,
)
from manzil_worker.stages.vision import KitchenAssessment, aggregate_kitchen
from manzil_worker.state import PropertyImageIn, RunState
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
