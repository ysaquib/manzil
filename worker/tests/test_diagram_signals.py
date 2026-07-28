"""P3-SC5 deterministic diagram detection: evidence, never resemblance."""

from __future__ import annotations

import pytest
from manzil_worker.enrich.diagram_signals import looks_like_diagram
from manzil_worker.state import ImageCandidateIn


def _candidate(**over: object) -> ImageCandidateIn:
    base: dict[str, object] = {
        "url": "https://img.test/a.jpg",
        "page_order": 0,
        "discovery_mechanism": "markup",
    }
    base.update(over)
    return ImageCandidateIn.model_validate(base)


@pytest.mark.parametrize(
    "over",
    [
        {"source_native_plan_id": "FP-2B2B"},
        {"containing_floor_plan_card": True},
        {"alt": "The Winslow floor plan"},
        {"title": "Floorplan — 2 bed"},
        {"caption": "Floor-plan diagram"},
        {"alt": "Unit plan"},
        {"alt": "2 bed layout"},
        {"caption": "Schematic"},
    ],
)
def test_page_stated_evidence_identifies_a_diagram(over: dict[str, object]) -> None:
    assert looks_like_diagram(_candidate(**over)) is True


@pytest.mark.parametrize(
    "over",
    [
        {},
        {"alt": "Sunny living room"},
        # Filename resemblance alone is explicitly insufficient (workbook §7.2).
        {"url": "https://img.test/floorplan-hero.jpg"},
        # "plan" in ordinary prose is not a claim about the asset.
        {"caption": "Plan your visit to our leasing office today"},
        {"alt": "Our residents enjoy an open layout with natural light throughout"},
        {"title": "Site plan your next move"},
    ],
)
def test_absent_or_incidental_wording_is_not_evidence(over: dict[str, object]) -> None:
    assert looks_like_diagram(_candidate(**over)) is False


def test_accepts_a_plain_mapping_as_well_as_the_model() -> None:
    assert looks_like_diagram({"alt": "Floor plan"}) is True
    assert looks_like_diagram({"alt": "Kitchen"}) is False
    assert looks_like_diagram({}) is False
