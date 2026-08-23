"""The §7.5 required fixtures for Floor Plan diagram association (P3-SC5).

Workbook §7.5 names these cases explicitly as the bar for the feature. Each one
is a claim the UI makes on the user's behalf, so each gets a test:

* a card with one unambiguous diagram links correctly;
* one diagram shared across several plans creates several associations without
  duplicate bytes;
* several diagrams may link to one plan;
* an ambiguous diagram remains unmatched;
* a generic Property photo never becomes a Floor Plan diagram;
* a partial fetch cannot remove the prior diagram (see
  `test_queue_diagram_projection`);
* diagrams never enter kitchen/flooring VISION inputs.
"""

from __future__ import annotations

import asyncio
import io
from uuid import uuid4

from manzil_shared.models import JobType
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.image_classify import (
    eligible_quality_images,
    eligible_quality_images_onnx,
    select_kitchen_targets,
)
from manzil_worker.stages.image_fetch import image_fetch_stage
from manzil_worker.state import FloorPlanIn, PlanManifest, PropertyImageIn, RunState, SourceState
from manzil_worker.vision_onnx import (
    ONNX_SHADOW_ARTIFACT_SHA256,
    ONNX_SHADOW_BACKEND,
    ONNX_SHADOW_CACHE_KEY,
    ONNX_SHADOW_DIAGRAM_THRESHOLD,
    ONNX_SHADOW_KITCHEN_THRESHOLD,
)
from PIL import Image


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, path: str, content: bytes) -> None:
        self.objects[path] = content


def _png(color: str) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (1600, 1200), color).save(output, format="PNG")
    return output.getvalue()


def _candidate(order: int, url: str, **over: object) -> dict[str, object]:
    return {"url": url, "page_order": order, "discovery_mechanism": "markup", **over}


def _run(candidates: list[dict[str, object]], plans: list[FloorPlanIn]):
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url="https://listing.test")
    state.property_id = uuid4()
    state.sources = [SourceState(url=state.url, image_candidates=candidates)]
    state.floor_plans = plans
    state.plan = PlanManifest(
        job_type="ingest",
        trigger="user:submit",
        source_policy="tiers_1_2_3",
        stages=["IMAGE_FETCH"],
        skipped={},
        est_cost_usd=0.01,
    )

    async def fetch(url: str) -> bytes:
        return _png(f"#{abs(hash(url)) % 0xFFFFFF:06x}")

    async def previous(property_id):  # type: ignore[no-untyped-def]
        return set()

    store = MemoryStore()
    out = asyncio.run(
        image_fetch_stage(
            state,
            StageCtx(download_image=fetch, image_store=store, existing_image_hashes=previous),
        )
    )
    return out, store


def _plan(key: str, name: str, *, native: str | None = None) -> FloorPlanIn:
    return FloorPlanIn(response_key=key, plan_name=name, beds=2, baths=2, source_native_id=native)


def test_a_card_with_one_unambiguous_diagram_links_to_its_plan() -> None:
    state, _ = _run(
        [
            _candidate(
                0,
                "https://img.test/winslow.png",
                containing_floor_plan_card=True,
                nearby_plan_label="The Winslow",
            )
        ],
        [_plan("fp1", "The Winslow"), _plan("fp2", "The Harlow")],
    )
    image = state.property_images[0]
    assert image.kind == "floor_plan_diagram"
    assert image.exact_floor_plan_refs == ["fp1"]


def test_one_diagram_shared_by_several_plans_stores_one_asset() -> None:
    """A Source-native ID shared by two plans links both without duplicate bytes."""
    state, store = _run(
        [_candidate(0, "https://img.test/shared.png", source_native_plan_id="FP-2B2B")],
        [
            _plan("fp1", "The Winslow", native="FP-2B2B"),
            _plan("fp2", "The Winslow Corner", native="FP-2B2B"),
        ],
    )
    assert sorted(state.property_images[0].exact_floor_plan_refs) == ["fp1", "fp2"]
    assert len(store.objects) == 1  # content-addressed: one asset, two links


def test_several_diagrams_may_link_to_one_plan() -> None:
    state, _ = _run(
        [
            _candidate(0, "https://img.test/a.png", source_native_plan_id="FP-1"),
            _candidate(1, "https://img.test/b.png", source_native_plan_id="FP-1"),
        ],
        [_plan("fp1", "The Winslow", native="FP-1")],
    )
    linked = [i for i in state.property_images if "fp1" in i.exact_floor_plan_refs]
    assert len(linked) == 2


def test_an_ambiguous_diagram_stays_unmatched() -> None:
    """Labelled a floor plan, but nothing ties it to a specific plan.

    It must be stored and classified — it is genuinely a diagram — while
    attaching to no plan at all. Attaching it to every plan would be a lie.
    """
    state, _ = _run(
        [_candidate(0, "https://img.test/plan.png", alt="Floor plan")],
        [_plan("fp1", "The Winslow"), _plan("fp2", "The Harlow")],
    )
    image = state.property_images[0]
    assert image.kind == "floor_plan_diagram"
    assert image.exact_floor_plan_refs == []


def test_a_generic_property_photo_never_becomes_a_diagram() -> None:
    state, _ = _run(
        [_candidate(0, "https://img.test/pool.jpg", alt="Resort-style swimming pool")],
        [_plan("fp1", "The Winslow")],
    )
    image = state.property_images[0]
    assert image.kind == "listing_photo"
    assert image.exact_floor_plan_refs == []


def test_a_nearby_label_matching_no_plan_does_not_guess() -> None:
    state, _ = _run(
        [
            _candidate(
                0,
                "https://img.test/x.png",
                containing_floor_plan_card=True,
                nearby_plan_label="The Ashford",
            )
        ],
        [_plan("fp1", "The Winslow")],
    )
    assert state.property_images[0].exact_floor_plan_refs == []


def _stored(kind: str, *, diagram_flag: bool) -> PropertyImageIn:
    return PropertyImageIn(
        source_url="https://img.test/x.png",
        storage_path="p/x.webp",
        content_hash="x" * 64,
        width=1024,
        height=768,
        byte_size=10,
        kind=kind,  # type: ignore[arg-type]
        vision_assessment={
            "classification": {
                "cache_key": "model:prompt-1",
                "assessment": {
                    "content_hash": "x" * 64,
                    "primary_scene": "diagram" if diagram_flag else "kitchen",
                    "kitchen_visibility": "not_visible" if diagram_flag else "assessable",
                    "flooring_assessability": "not_visible",
                    "bathroom_visibility": "not_visible",
                    "framing": "full_room",
                    "confidence": "high",
                    "irrelevant": False,
                    "diagram": diagram_flag,
                },
            }
        },
    )


def _stored_onnx(kind: str, *, diagram_flag: bool) -> PropertyImageIn:
    return PropertyImageIn(
        source_url="https://img.test/x.png",
        storage_path="p/x.webp",
        content_hash="x" * 64,
        width=1024,
        height=768,
        byte_size=10,
        kind=kind,  # type: ignore[arg-type]
        vision_assessment={
            "classification": {
                "cache_key": ONNX_SHADOW_CACHE_KEY,
                "backend": ONNX_SHADOW_BACKEND,
                "artifact_sha256": ONNX_SHADOW_ARTIFACT_SHA256,
                "kitchen_threshold": ONNX_SHADOW_KITCHEN_THRESHOLD,
                "diagram_threshold": ONNX_SHADOW_DIAGRAM_THRESHOLD,
                "assessment": {
                    "content_hash": "x" * 64,
                    "predicted_scene": "corridor" if diagram_flag else "kitchen",
                    "kitchen_score": 0.1 if diagram_flag else 0.9,
                    "kitchen_predicted": not diagram_flag,
                    "diagram_score": 0.99 if diagram_flag else 0.01,
                    "diagram_predicted": diagram_flag,
                },
            }
        },
    )


def test_diagrams_never_reach_quality_vision_by_either_signal() -> None:
    """`kind` and the visual flag are both honoured, independently.

    The shared gate means `flooring_quality` inherits this when it lands,
    rather than having to re-derive the exclusion.
    """
    by_kind = _stored("floor_plan_diagram", diagram_flag=False)
    by_assessment = _stored("listing_photo", diagram_flag=True)
    photo = _stored("listing_photo", diagram_flag=False)

    eligible = eligible_quality_images([by_kind, by_assessment, photo])
    assert eligible == [photo]
    assert select_kitchen_targets([by_kind, by_assessment]) == []

    onnx_eligible = eligible_quality_images_onnx(
        [
            _stored_onnx("floor_plan_diagram", diagram_flag=False),
            _stored_onnx("listing_photo", diagram_flag=True),
            _stored_onnx("listing_photo", diagram_flag=False),
        ]
    )
    assert [image.kind for image in onnx_eligible] == ["listing_photo"]
    predicted = onnx_eligible[0].vision_assessment["classification"]["assessment"]
    assert predicted["diagram_predicted"] is False


# --- Real pages name the plan in the diagram's own alt text (§7.2 label rule) ---


def test_a_diagram_whose_alt_names_exactly_one_plan_links_to_it() -> None:
    """The shape the corpus actually shows: `alt="Floor plan Studio"`."""
    state, _ = _run(
        [_candidate(0, "https://img.test/studio.png", alt="Floor plan Studio")],
        [_plan("fp1", "Studio"), _plan("fp2", "The Harlow")],
    )
    assert state.property_images[0].exact_floor_plan_refs == ["fp1"]


def test_the_most_specific_plan_name_wins_over_a_shorter_prefix() -> None:
    """`alt="Floor plan Studio Deluxe"` contains both "Studio" and "Studio
    Deluxe". Linking to the shorter one would be wrong; the page named the
    longer, so it wins."""
    state, _ = _run(
        [_candidate(0, "https://img.test/x.png", alt="Floor plan Studio Deluxe")],
        [_plan("fp1", "Studio"), _plan("fp2", "Studio Deluxe")],
    )
    assert state.property_images[0].exact_floor_plan_refs == ["fp2"]


def test_two_equally_specific_names_stay_unmatched() -> None:
    """A genuine tie is ambiguous, and ambiguity never guesses."""
    state, _ = _run(
        [_candidate(0, "https://img.test/x.png", alt="Floor plan: Aspen and Birch")],
        [_plan("fp1", "Aspen"), _plan("fp2", "Birch")],
    )
    assert state.property_images[0].exact_floor_plan_refs == []


def test_a_very_short_plan_name_is_not_matched_from_prose() -> None:
    """A plan called "A" must not swallow every diagram on the page."""
    state, _ = _run(
        [_candidate(0, "https://img.test/x.png", alt="Floor plan for a garden home")],
        [_plan("fp1", "A")],
    )
    assert state.property_images[0].exact_floor_plan_refs == []


def test_a_photos_alt_never_links_it_to_a_plan() -> None:
    """The alt-text rule is diagram-only; a photo mentioning a plan name stays free."""
    state, _ = _run(
        [_candidate(0, "https://img.test/pool.jpg", alt="Pool view from the Winslow building")],
        [_plan("fp1", "Winslow")],
    )
    image = state.property_images[0]
    assert image.kind == "listing_photo"
    assert image.exact_floor_plan_refs == []
