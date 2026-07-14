"""P3-7a IMAGE_FETCH: cap/dedupe/storage and content-hash spend gate."""

from __future__ import annotations

import asyncio
import io
from uuid import uuid4

from manzil_shared.models import JobType
from manzil_worker.enrich.images import normalize_image
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.image_fetch import image_fetch_stage
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


def test_same_normalized_hashes_mark_vision_skipped() -> None:
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
    assert state.plan.skipped == {"VISION": "images_unchanged"}
    assert state.property_images[0].content_hash == expected
    assert store.objects == {}  # content-addressed object already exists


def test_partial_download_set_preserves_prior_rows_and_skips_vision() -> None:
    async def fetch(url: str) -> bytes:
        if url.endswith("bad"):
            return b"not an image"
        return _bytes("blue")

    state = asyncio.run(
        image_fetch_stage(
            _state(["https://img.test/good", "https://img.test/bad"]),
            StageCtx(download_image=fetch, image_store=MemoryStore()),
        )
    )
    assert not state.image_fetch_completed
    assert state.property_images == []
    assert state.plan is not None
    assert state.plan.skipped == {"VISION": "image_set_incomplete"}
