"""P3-7a2 classifier-bench metrics use the production target selector."""

from __future__ import annotations

from manzil_worker.evals.vision_classifier import ImageLabel, evaluate_classifier
from manzil_worker.llm.client import CostTally
from manzil_worker.stages.image_classify import ImageClassification
from PIL import Image


def _assessment(content_hash: str, *, kitchen: str, diagram: bool = False) -> ImageClassification:
    return ImageClassification(
        content_hash=content_hash,
        primary_scene="diagram" if diagram else "kitchen",
        kitchen_visibility=kitchen,
        flooring_assessability="not_visible",
        bathroom_visibility="not_visible",
        framing="full_room",
        confidence="high",
        irrelevant=False,
        diagram=diagram,
    )


def test_scores_selector_precision_recall_and_diagram_safety(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "images").mkdir()
    for filename, color in (("one.webp", (200, 10, 10)), ("two.webp", (10, 200, 10))):
        Image.new("RGB", (32, 24), color).save(tmp_path / "images" / filename, format="WEBP")
    labels = [
        ImageLabel(
            "one", "p1", "One", "a" * 64, "images/one.webp", True, True, "listing_photo", None
        ),
        ImageLabel(
            "two",
            "p2",
            "Two",
            "b" * 64,
            "images/two.webp",
            False,
            False,
            "floor_plan_diagram",
            None,
        ),
    ]
    assessments = {
        "a" * 64: _assessment("a" * 64, kitchen="assessable"),
        "b" * 64: _assessment("b" * 64, kitchen="assessable", diagram=True),
    }
    tally = CostTally(calls=2, cost_usd=0.002)

    result = evaluate_classifier(
        model="google/gemini-2.5-flash-lite",
        prompt_version=1,
        labels=labels,
        assessments=assessments,
        labels_dir=tmp_path,
        tally=tally,
        latency_seconds=1.0,
    )

    assert result.selected_target_count == 1
    assert result.selected_kitchen_precision == 1.0
    assert result.kitchen_property_recall == 1.0
    assert result.selected_floor_plan_diagrams == 0
    assert result.no_kitchen_properties_with_selection == 0
    assert result.passed
