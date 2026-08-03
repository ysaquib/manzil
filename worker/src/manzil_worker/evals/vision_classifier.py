"""Human-labeled benchmark for IMAGE_CLASSIFY (P3-7a2)."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from manzil_shared.config import MAX_IMAGE_CLASSIFY_IMAGES

from manzil_worker.enrich.images import classification_thumbnail, difference_hash
from manzil_worker.evals.vision_label_kit import VISION_LABELS_DIR
from manzil_worker.llm import VisionImage, call_vision
from manzil_worker.llm.client import CostTally, RunContext, cost_tally, run_context
from manzil_worker.llm.config import MODEL_PRICES
from manzil_worker.llm.prompt_loader import load_prompt
from manzil_worker.stages.image_classify import ImageClassification, ImageClassificationBatch
from manzil_worker.state import PropertyImageIn

DEFAULT_CLASSIFIER_BENCH_MODELS = (
    "google/gemini-2.5-flash-lite",
    "google/gemini-3.1-flash-lite",
    "google/gemini-3-flash-preview",
)


class ClassifierBenchError(ValueError):
    """The local label set cannot support a trustworthy classifier bench."""


@dataclass(frozen=True)
class ImageLabel:
    image_id: str
    property_id: str
    property_name: str
    content_hash: str
    asset_file: str
    kitchen_visible: bool
    kitchen_assessable: bool
    content_kind: Literal["listing_photo", "floor_plan_diagram", "irrelevant"]
    duplicate_group: str | None


@dataclass(frozen=True)
class ClassifierBenchResult:
    model: str
    prompt_version: int
    image_count: int
    property_count: int
    calls: int
    latency_seconds: float
    cost_usd: float
    cost_per_property_usd: float
    selected_target_count: int
    selected_kitchen_precision: float | None
    selected_assessable_precision: float | None
    kitchen_property_recall: float | None
    no_kitchen_properties: int
    no_kitchen_properties_with_selection: int
    selected_floor_plan_diagrams: int
    duplicate_target_violations: int
    passed: bool
    selected_image_ids: tuple[str, ...]


CallVision = Callable[
    [str, type[ImageClassificationBatch], list[VisionImage]], Awaitable[ImageClassificationBatch]
]


def _bool(value: str | None, *, row: int, field: str) -> bool:
    normalized = (value or "").strip().casefold()
    if normalized in {"true", "yes"}:
        return True
    if normalized in {"false", "no"}:
        return False
    raise ClassifierBenchError(f"labels.csv row {row}: {field} must be true/false or yes/no")


def load_classifier_labels(labels_dir: Path = VISION_LABELS_DIR) -> list[ImageLabel]:
    """Load fully completed human ground truth plus stable local asset paths."""
    manifest_path = labels_dir / "manifest.json"
    labels_path = labels_dir / "labels.csv"
    try:
        manifest = json.loads(manifest_path.read_text())
        with labels_path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, json.JSONDecodeError) as error:
        raise ClassifierBenchError(f"cannot read local classifier labels: {error}") from error
    assets = {
        image["image_id"]: image["asset_file"]
        for image in manifest.get("images", [])
        if isinstance(image, dict)
        and isinstance(image.get("image_id"), str)
        and isinstance(image.get("asset_file"), str)
    }
    labels: list[ImageLabel] = []
    seen: set[str] = set()
    for row_number, row in enumerate(rows, 2):
        image_id = (row.get("image_id") or "").strip()
        content_kind = (row.get("content_kind") or "").strip()
        if not image_id or image_id in seen or image_id not in assets:
            raise ClassifierBenchError(
                f"labels.csv row {row_number}: invalid image_id {image_id!r}"
            )
        if content_kind not in {"listing_photo", "floor_plan_diagram", "irrelevant"}:
            raise ClassifierBenchError(f"labels.csv row {row_number}: invalid content_kind")
        kitchen_visible = _bool(row.get("kitchen_visible"), row=row_number, field="kitchen_visible")
        kitchen_assessable = _bool(
            row.get("kitchen_assessable"), row=row_number, field="kitchen_assessable"
        )
        if kitchen_assessable and not kitchen_visible:
            raise ClassifierBenchError(
                f"labels.csv row {row_number}: kitchen_assessable cannot be true "
                "when kitchen_visible is false"
            )
        asset = labels_dir / assets[image_id]
        if not asset.is_file():
            raise ClassifierBenchError(
                f"labels.csv row {row_number}: missing asset {assets[image_id]}"
            )
        seen.add(image_id)
        labels.append(
            ImageLabel(
                image_id=image_id,
                property_id=(row.get("property_id") or "").strip(),
                property_name=(row.get("property_name") or "").strip(),
                content_hash=(row.get("content_hash") or "").strip(),
                asset_file=assets[image_id],
                kitchen_visible=kitchen_visible,
                kitchen_assessable=kitchen_assessable,
                content_kind=content_kind,  # type: ignore[arg-type]
                duplicate_group=(row.get("duplicate_group") or "").strip() or None,
            )
        )
    if len(labels) < 1:
        raise ClassifierBenchError("labels.csv contains no completed image labels")
    if len(labels) != len(assets):
        raise ClassifierBenchError("labels.csv and manifest.json do not cover the same images")
    return labels


def _model_images(labels: Sequence[ImageLabel], labels_dir: Path) -> list[VisionImage]:
    blocks: list[VisionImage] = []
    for label in labels:
        data = (labels_dir / label.asset_file).read_bytes()
        thumbnail = classification_thumbnail(data)
        blocks.append(
            VisionImage(
                content_hash=hashlib.sha256(thumbnail).hexdigest(),
                data=thumbnail,
                label=f"target:{label.content_hash}",
            )
        )
    return blocks


def _property_images(
    labels: Sequence[ImageLabel], assessments: dict[str, ImageClassification], labels_dir: Path
) -> list[PropertyImageIn]:
    images: list[PropertyImageIn] = []
    for label in labels:
        asset = labels_dir / label.asset_file
        image = PropertyImageIn(
            source_url="local-benchmark",
            storage_path=label.asset_file,
            content_hash=label.content_hash,
            width=0,
            height=0,
            byte_size=asset.stat().st_size,
            perceptual_hash=difference_hash(asset.read_bytes()),
            vision_assessment={
                "classification": {"assessment": assessments[label.content_hash].model_dump()}
            },
        )
        images.append(image)
    return images


def evaluate_classifier(
    *,
    model: str,
    prompt_version: int,
    labels: Sequence[ImageLabel],
    assessments: dict[str, ImageClassification],
    labels_dir: Path,
    tally: CostTally,
    latency_seconds: float,
) -> ClassifierBenchResult:
    """Score historical LLM outputs with the retained pre-v3.52 selector."""
    from manzil_worker.stages.image_classify import select_kitchen_targets_llm_legacy

    by_property: dict[str, list[ImageLabel]] = defaultdict(list)
    for label in labels:
        by_property[label.property_id].append(label)
    selected: list[ImageLabel] = []
    for property_labels in by_property.values():
        property_assessments = {
            label.content_hash: assessments[label.content_hash] for label in property_labels
        }
        selected_hashes = {
            image.content_hash
            for image in select_kitchen_targets_llm_legacy(
                _property_images(property_labels, property_assessments, labels_dir)
            )
        }
        selected.extend(label for label in property_labels if label.content_hash in selected_hashes)

    selected_kitchens = sum(label.kitchen_visible for label in selected)
    selected_assessable = sum(label.kitchen_assessable for label in selected)
    kitchen_properties = [
        property_labels
        for property_labels in by_property.values()
        if any(label.kitchen_visible for label in property_labels)
    ]
    recalled_properties = sum(
        any(label.kitchen_visible for label in property_labels if label in selected)
        for property_labels in kitchen_properties
    )
    no_kitchen_properties = [
        property_labels
        for property_labels in by_property.values()
        if not any(label.kitchen_visible for label in property_labels)
    ]
    selected_by_property: dict[str, list[ImageLabel]] = defaultdict(list)
    for label in selected:
        selected_by_property[label.property_id].append(label)
    no_kitchen_selected = sum(
        bool(selected_by_property[property_labels[0].property_id])
        for property_labels in no_kitchen_properties
    )
    duplicate_violations = 0
    for property_labels in selected_by_property.values():
        groups = [label.duplicate_group for label in property_labels if label.duplicate_group]
        duplicate_violations += len(groups) - len(set(groups))
    diagrams = sum(label.content_kind == "floor_plan_diagram" for label in selected)
    precision = selected_kitchens / len(selected) if selected else None
    assessable_precision = selected_assessable / len(selected) if selected else None
    recall = recalled_properties / len(kitchen_properties) if kitchen_properties else None
    cost_per_property = tally.cost_usd / len(by_property)
    passed = (
        precision is not None
        and precision >= 0.95
        and recall is not None
        and recall >= 0.90
        and no_kitchen_selected == 0
        and diagrams == 0
        and duplicate_violations == 0
        and cost_per_property < 0.005
    )
    return ClassifierBenchResult(
        model=model,
        prompt_version=prompt_version,
        image_count=len(labels),
        property_count=len(by_property),
        calls=tally.calls,
        latency_seconds=latency_seconds,
        cost_usd=tally.cost_usd,
        cost_per_property_usd=cost_per_property,
        selected_target_count=len(selected),
        selected_kitchen_precision=precision,
        selected_assessable_precision=assessable_precision,
        kitchen_property_recall=recall,
        no_kitchen_properties=len(no_kitchen_properties),
        no_kitchen_properties_with_selection=no_kitchen_selected,
        selected_floor_plan_diagrams=diagrams,
        duplicate_target_violations=duplicate_violations,
        passed=passed,
        selected_image_ids=tuple(label.image_id for label in selected),
    )


async def run_classifier_bench(
    *,
    labels_dir: Path = VISION_LABELS_DIR,
    models: Sequence[str] = DEFAULT_CLASSIFIER_BENCH_MODELS,
    vision_call: CallVision = call_vision,
) -> list[ClassifierBenchResult]:
    """Run a sequential, traced, 30-image-batched model sweep."""
    labels = load_classifier_labels(labels_dir)
    grouped: dict[str, list[ImageLabel]] = defaultdict(list)
    for label in labels:
        grouped[label.property_id].append(label)
    if any(
        len(property_labels) > MAX_IMAGE_CLASSIFY_IMAGES for property_labels in grouped.values()
    ):
        raise ClassifierBenchError("a Property exceeds the IMAGE_CLASSIFY batch limit")
    for model in models:
        if model not in MODEL_PRICES:
            raise ClassifierBenchError(f"unpriced classifier model {model!r}")

    results: list[ClassifierBenchResult] = []
    original_model = os.environ.get("MANZIL_MODEL_IMAGE_CLASSIFY")
    try:
        for model in models:
            os.environ["MANZIL_MODEL_IMAGE_CLASSIFY"] = model
            assessments: dict[str, ImageClassification] = {}
            started = time.monotonic()
            with (
                run_context(
                    RunContext(
                        job_type="bench", job_id=str(uuid.uuid4()), listing_slug="vision-classifier"
                    )
                ),
                cost_tally() as tally,
            ):
                for property_labels in grouped.values():
                    blocks = _model_images(property_labels, labels_dir)
                    result = await vision_call("image_classify", ImageClassificationBatch, blocks)
                    returned = [assessment.content_hash for assessment in result.assessments]
                    requested = [block.content_hash for block in blocks]
                    if len(returned) != len(set(returned)) or set(returned) != set(requested):
                        missing = sorted(set(requested) - set(returned))
                        unknown = sorted(set(returned) - set(requested))
                        duplicate_count = len(returned) - len(set(returned))
                        raise ClassifierBenchError(
                            f"{model}: invalid response for {len(requested)} requested images "
                            f"(returned={len(returned)}, missing={len(missing)}, "
                            f"unknown={len(unknown)}, duplicates={duplicate_count})"
                        )
                    by_thumbnail = {
                        assessment.content_hash: assessment for assessment in result.assessments
                    }
                    for label, block in zip(property_labels, blocks, strict=True):
                        assessments[label.content_hash] = by_thumbnail[
                            block.content_hash
                        ].model_copy(update={"content_hash": label.content_hash})
            results.append(
                evaluate_classifier(
                    model=model,
                    prompt_version=load_prompt("image_classify").version,
                    labels=labels,
                    assessments=assessments,
                    labels_dir=labels_dir,
                    tally=tally,
                    latency_seconds=time.monotonic() - started,
                )
            )
    finally:
        if original_model is None:
            os.environ.pop("MANZIL_MODEL_IMAGE_CLASSIFY", None)
        else:
            os.environ["MANZIL_MODEL_IMAGE_CLASSIFY"] = original_model
    return results


def report_json(results: Sequence[ClassifierBenchResult]) -> str:
    return json.dumps([asdict(result) for result in results], indent=2) + "\n"
