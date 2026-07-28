"""§7.5 real-listing smoke: one saved page with explicitly labelled diagrams.

The corpus is the local eval kit and is gitignored (AGENTS.md, DESIGN §20 v2.8),
so this skips in CI and runs for whoever has the corpus checked out. It is the
only test here that exercises real listing markup rather than a synthetic
fixture — everything upstream of `image_fetch_stage` is real: the DOM, the
`alt` text, the candidate ordering.

Plan names are the ones EXTRACT produces for this page. Downloads are stubbed;
what is under test is discovery, classification, and association, not HTTP.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from uuid import uuid4

import pytest
from manzil_shared.config import DIAGRAM_MAX_DIM, DIAGRAM_NORMALIZATION_PROFILE
from manzil_shared.models import JobType
from manzil_worker.enrich.images import discover_images
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.image_fetch import image_fetch_stage
from manzil_worker.state import FloorPlanIn, PlanManifest, RunState, SourceState
from PIL import Image

PAGE = (
    Path(__file__).parent
    / "fixtures"
    / "corpus"
    / "realtor.com--springs-at-canton"
    / "raw.html"
)

# Exactly as EXTRACT names them for this Property.
PLAN_NAMES = [
    "Studio",
    "1 BR Designer Courtyard",
    "1 BR Designer Overlook",
    "2 BR Grand Overlook",
    "2 BR Grand Courtyard",
]

pytestmark = pytest.mark.skipif(
    not PAGE.exists(), reason="local eval corpus not present (gitignored)"
)


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, path: str, content: bytes) -> None:
        self.objects[path] = content


def _png(seed: str) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (2400, 1700), f"#{abs(hash(seed)) % 0xFFFFFF:06x}").save(output, "PNG")
    return output.getvalue()


def test_a_real_listing_page_links_every_labelled_diagram_to_its_plan() -> None:
    html = PAGE.read_text(encoding="utf-8", errors="ignore")
    candidates = [image.__dict__ for image in discover_images(html, "https://realtor.com")]

    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url="https://realtor.com/x")
    state.property_id = uuid4()
    state.sources = [SourceState(url=state.url, image_candidates=candidates)]
    state.floor_plans = [
        FloorPlanIn(response_key=f"fp{index}", plan_name=name, beds=1, baths=1)
        for index, name in enumerate(PLAN_NAMES)
    ]
    state.plan = PlanManifest(
        job_type="ingest",
        trigger="user:submit",
        source_policy="tiers_1_2_3",
        stages=["IMAGE_FETCH"],
        skipped={},
        est_cost_usd=0.01,
    )

    async def fetch(url: str) -> bytes:
        return _png(url)

    async def previous(property_id):  # type: ignore[no-untyped-def]
        return set()

    out = asyncio.run(
        image_fetch_stage(
            state,
            StageCtx(
                download_image=fetch,
                image_store=MemoryStore(),
                existing_image_hashes=previous,
            ),
        )
    )

    name_by_ref = {plan.response_key: plan.plan_name for plan in state.floor_plans}
    diagrams = [image for image in out.property_images if image.kind == "floor_plan_diagram"]
    linked = {
        name_by_ref[ref]
        for image in diagrams
        for ref in image.exact_floor_plan_refs
    }

    # The page carries four labelled diagrams; each names exactly one plan.
    assert len(diagrams) == 4
    assert linked == {
        "Studio",
        "1 BR Designer Courtyard",
        "1 BR Designer Overlook",
        "2 BR Grand Overlook",
    }
    # No diagram claims more than one plan, and none is left guessing.
    assert all(len(image.exact_floor_plan_refs) == 1 for image in diagrams)
    # All four are stored at the legible profile, not the photo profile.
    assert all(image.normalization_profile == DIAGRAM_NORMALIZATION_PROFILE for image in diagrams)
    assert all(image.width == DIAGRAM_MAX_DIM for image in diagrams)
    # The unlabelled photos on the same page stay photos.
    assert any(image.kind == "listing_photo" for image in out.property_images)
