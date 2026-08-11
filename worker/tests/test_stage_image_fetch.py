"""P3-7a IMAGE_FETCH: cap/dedupe/storage and content-hash spend gate."""

from __future__ import annotations

import asyncio
import io
from uuid import uuid4

from manzil_shared.config import (
    DIAGRAM_NORMALIZATION_PROFILE,
    MAX_FLOOR_PLAN_DIAGRAMS_PER_PROPERTY,
    MAX_STORED_IMAGES,
)
from manzil_shared.models import JobType
from manzil_worker.enrich.images import normalize_image
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.image_fetch import (
    PHOTO_NORMALIZATION_PROFILE,
    image_fetch_stage,
)
from manzil_worker.state import PlanManifest, RunState, SourceState
from PIL import Image


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, path: str, content: bytes) -> None:
        self.objects[path] = content


def _bytes(color: str) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (1200, 800), color).save(output, format="PNG")
    return output.getvalue()


def _state(urls: list[str]) -> RunState:
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url="https://listing.test")
    state.property_id = uuid4()
    state.sources = [SourceState(url=state.url, image_urls=urls)]
    state.plan = PlanManifest(
        job_type="ingest",
        trigger="user:submit",
        source_policy="tiers_1_2_3",
        stages=["IMAGE_FETCH", "VISION"],
        skipped={},
        est_cost_usd=0.03,
    )
    return state


def test_changed_images_are_deduped_stored_and_leave_vision_enabled() -> None:
    payloads = {"https://img.test/a": _bytes("red"), "https://img.test/b": _bytes("red")}

    async def fetch(url: str) -> bytes:
        return payloads[url]

    async def previous(property_id):  # type: ignore[no-untyped-def]
        return {"old"}

    store = MemoryStore()
    state = asyncio.run(
        image_fetch_stage(
            _state(list(payloads)),
            StageCtx(download_image=fetch, image_store=store, existing_image_hashes=previous),
        )
    )
    assert len(state.property_images) == 1
    assert state.image_fetch_completed
    assert len(store.objects) == 1
    assert state.plan is not None and "VISION" not in state.plan.skipped


def test_same_normalized_hashes_leave_quality_gate_to_classifier_digest() -> None:
    raw = _bytes("green")
    expected = normalize_image(raw).content_hash

    async def fetch(url: str) -> bytes:
        return raw

    async def previous(property_id):  # type: ignore[no-untyped-def]
        return {expected}

    store = MemoryStore()
    state = asyncio.run(
        image_fetch_stage(
            _state(["https://img.test/a"]),
            StageCtx(
                download_image=fetch,
                image_store=store,
                existing_image_hashes=previous,
            ),
        )
    )
    assert state.plan is not None
    assert state.plan.skipped == {}
    assert state.property_images[0].content_hash == expected
    assert store.objects == {}  # content-addressed object already exists


def test_partial_download_set_keeps_good_images_without_authoritative_replace() -> None:
    """One dead candidate must not discard the images that did download.

    `image_fetch_completed=False` already makes persistence additive
    (queue.py: the delete-not-in-current only runs when completed), so storing
    a partial set is safe -- it can never delete a prior row.
    """

    async def fetch(url: str) -> bytes:
        if url.endswith("bad"):
            return b"not an image"
        return _bytes("blue")

    store = MemoryStore()
    state = asyncio.run(
        image_fetch_stage(
            _state(["https://img.test/good", "https://img.test/bad"]),
            StageCtx(download_image=fetch, image_store=store),
        )
    )
    # Not authoritative -- the set is known-partial, so persistence stays additive.
    assert not state.image_fetch_completed
    # ...but the image that did download is kept and stored.
    assert len(state.property_images) == 1
    assert len(store.objects) == 1
    assert state.plan is not None and "VISION" not in state.plan.skipped
    assert len(state.warnings) == 1
    assert state.warnings[0].code == "image_fetch_partial"
    assert state.warnings[0].detail == {"failed_candidates": 1, "prepared_images": 1}
    assert not state.image_fetch_strict_complete


def test_cap_saturated_partial_is_complete_without_a_user_warning() -> None:
    interleaved: list[str] = []
    for i in range(MAX_STORED_IMAGES):
        interleaved.append(f"https://img.test/good{i}")
        interleaved.append(f"https://img.test/bad{i}")
    interleaved.extend(f"https://img.test/extra-bad{i}" for i in range(5))

    async def fetch(url: str) -> bytes:
        if "/bad" in url:
            return b"not an image"
        return _bytes(f"#{abs(hash(url)) % 0xFFFFFF:06x}")

    store = MemoryStore()
    state = asyncio.run(
        image_fetch_stage(
            _state(interleaved),
            StageCtx(download_image=fetch, image_store=store),
        )
    )
    photos = [image for image in state.property_images if image.kind == "listing_photo"]
    assert len(photos) == MAX_STORED_IMAGES
    assert state.image_fetch_completed
    assert not state.image_fetch_strict_complete
    assert state.warnings == []


def test_all_candidates_failing_stores_nothing_and_skips_vision() -> None:
    async def fetch(url: str) -> bytes:
        return b"not an image"

    state = asyncio.run(
        image_fetch_stage(
            _state(["https://img.test/bad1", "https://img.test/bad2"]),
            StageCtx(download_image=fetch, image_store=MemoryStore()),
        )
    )
    assert not state.image_fetch_completed
    assert state.property_images == []
    assert state.plan is not None
    assert state.plan.skipped == {"VISION": "no_usable_images"}
    assert state.warnings[0].code == "image_fetch_partial"


def test_partial_set_adding_no_new_hashes_leaves_quality_gate_to_classifier() -> None:
    raw = _bytes("green")
    expected = normalize_image(raw).content_hash

    async def fetch(url: str) -> bytes:
        if url.endswith("bad"):
            return b"not an image"
        return raw

    async def previous(property_id):  # type: ignore[no-untyped-def]
        return {expected}

    state = asyncio.run(
        image_fetch_stage(
            _state(["https://img.test/good", "https://img.test/bad"]),
            StageCtx(
                download_image=fetch,
                image_store=MemoryStore(),
                existing_image_hashes=previous,
            ),
        )
    )
    assert state.plan is not None
    assert state.plan.skipped == {}


# --- P3-SC5: diagrams get their own profile, budget, and full-size preference ---


def _diagram_state(candidates: list[dict[str, object]]) -> RunState:
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url="https://listing.test")
    state.property_id = uuid4()
    state.sources = [SourceState(url=state.url, image_candidates=candidates)]
    state.plan = PlanManifest(
        job_type="ingest",
        trigger="user:submit",
        source_policy="tiers_1_2_3",
        stages=["IMAGE_FETCH", "VISION"],
        skipped={},
        est_cost_usd=0.03,
    )
    return state


def _candidate(order: int, url: str, **over: object) -> dict[str, object]:
    return {"url": url, "page_order": order, "discovery_mechanism": "markup", **over}


async def _no_previous(property_id):  # type: ignore[no-untyped-def]
    return set()


def test_labelled_diagram_uses_the_full_size_target_and_diagram_profile() -> None:
    """An explicit diagram is stored once, from the anchor's full-size asset."""
    fetched: list[str] = []

    async def fetch(url: str) -> bytes:
        fetched.append(url)
        return _bytes("white")

    store = MemoryStore()
    state = asyncio.run(
        image_fetch_stage(
            _diagram_state(
                [
                    _candidate(
                        0,
                        "https://img.test/thumb.jpg",
                        alt="The Winslow floor plan",
                        full_size_url="https://img.test/full.png",
                    ),
                    _candidate(1, "https://img.test/kitchen.jpg", alt="Kitchen"),
                ]
            ),
            StageCtx(download_image=fetch, image_store=store, existing_image_hashes=_no_previous),
        )
    )

    diagram = next(i for i in state.property_images if i.kind == "floor_plan_diagram")
    photo = next(i for i in state.property_images if i.kind == "listing_photo")
    assert "https://img.test/full.png" in fetched
    assert "https://img.test/thumb.jpg" not in fetched  # never downloaded twice
    assert diagram.normalization_profile == DIAGRAM_NORMALIZATION_PROFILE
    assert photo.normalization_profile == PHOTO_NORMALIZATION_PROFILE
    assert len(store.objects) == 2


def test_full_size_failure_falls_back_to_the_thumbnail() -> None:
    async def fetch(url: str) -> bytes:
        if url.endswith("full.png"):
            raise OSError("gone")
        return _bytes("white")

    store = MemoryStore()
    state = asyncio.run(
        image_fetch_stage(
            _diagram_state(
                [
                    _candidate(
                        0,
                        "https://img.test/thumb.jpg",
                        containing_floor_plan_card=True,
                        full_size_url="https://img.test/full.png",
                    )
                ]
            ),
            StageCtx(download_image=fetch, image_store=store, existing_image_hashes=_no_previous),
        )
    )
    assert len(state.property_images) == 1
    assert state.property_images[0].kind == "floor_plan_diagram"


def test_diagram_budget_is_separate_so_photos_cannot_evict_a_late_diagram() -> None:
    """A diagram after MAX_STORED_IMAGES photos still lands (§P3-SC5 caps)."""
    photos = [_candidate(i, f"https://img.test/p{i}.jpg") for i in range(MAX_STORED_IMAGES + 5)]
    late = _candidate(
        MAX_STORED_IMAGES + 5, "https://img.test/plan.jpg", alt="Floor plan for the Winslow"
    )

    async def fetch(url: str) -> bytes:
        return _bytes(f"#{abs(hash(url)) % 0xFFFFFF:06x}")

    store = MemoryStore()
    state = asyncio.run(
        image_fetch_stage(
            _diagram_state([*photos, late]),
            StageCtx(download_image=fetch, image_store=store, existing_image_hashes=_no_previous),
        )
    )
    kinds = [image.kind for image in state.property_images]
    assert kinds.count("listing_photo") == MAX_STORED_IMAGES
    assert kinds.count("floor_plan_diagram") == 1


def test_property_diagram_cap_holds() -> None:
    candidates = [
        _candidate(i, f"https://img.test/d{i}.jpg", alt="Floor plan")
        for i in range(MAX_FLOOR_PLAN_DIAGRAMS_PER_PROPERTY + 4)
    ]

    async def fetch(url: str) -> bytes:
        return _bytes(f"#{abs(hash(url)) % 0xFFFFFF:06x}")

    store = MemoryStore()
    state = asyncio.run(
        image_fetch_stage(
            _diagram_state(candidates),
            StageCtx(download_image=fetch, image_store=store, existing_image_hashes=_no_previous),
        )
    )
    diagrams = [i for i in state.property_images if i.kind == "floor_plan_diagram"]
    assert len(diagrams) == MAX_FLOOR_PLAN_DIAGRAMS_PER_PROPERTY
