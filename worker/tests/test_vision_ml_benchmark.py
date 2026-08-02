"""Pure contracts for the pretrained IMAGE_CLASSIFY benchmark."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from manzil_worker.evals.vision_ml_benchmark import (
    CLASSIFIER_MAX_DIM,
    BinaryMetrics,
    TransformersAdapter,
    VisionMLBenchError,
    _auroc,
    _classifier_rgb,
    _clip_onnx_pixels,
    binary_metrics,
    calibrate_threshold,
    load_mit_split,
    validate_artifacts,
)


def test_binary_metrics_and_auroc() -> None:
    labels = [False, False, True, True]
    scores = [0.1, 0.4, 0.7, 0.9]

    metrics = binary_metrics(labels, scores, threshold=0.7)

    assert metrics == BinaryMetrics(
        threshold=0.7,
        count=4,
        positives=2,
        negatives=2,
        true_positive=2,
        false_positive=0,
        true_negative=2,
        false_negative=0,
        precision=1.0,
        recall=1.0,
        specificity=1.0,
        f1=1.0,
        accuracy=1.0,
        auroc=1.0,
    )
    assert _auroc([False, True], [0.5, 0.5]) == 0.5


def test_calibration_uses_public_labels_and_separates_scores() -> None:
    labels = [False, False, True, True]
    scores = [0.1, 0.3, 0.6, 0.9]
    threshold = calibrate_threshold(labels, scores)

    assert threshold == 0.6
    assert binary_metrics(labels, scores, threshold=threshold).f1 == 1.0


def test_load_mit_split_is_balanced_and_path_checked(tmp_path) -> None:  # type: ignore[no-untyped-def]
    mit = tmp_path / "datasets" / "mit-indoor-67"
    images = mit / "Images"
    rows = []
    for class_index in range(67):
        label = f"class_{class_index:02d}"
        (images / label).mkdir(parents=True)
        for image_index in range(2):
            relative = f"{label}/{image_index}.jpg"
            (images / relative).write_bytes(b"not decoded by this loader")
            rows.append(relative)
    (mit / "TrainImages.txt").write_text("\n".join(rows))

    examples = load_mit_split(tmp_path, "train", per_class=1)

    assert len(examples) == 67
    assert len({example.label for example in examples}) == 67


def test_validate_artifacts_rejects_unknown_model(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(VisionMLBenchError, match="unknown benchmark"):
        validate_artifacts(tmp_path, ["not-a-model"])


def test_metrics_are_json_serializable() -> None:
    metrics = binary_metrics([False, True], [0.1, 0.9], threshold=0.5)
    assert json.loads(json.dumps(metrics.__dict__))["f1"] == 1.0


def test_transformers_adapter_accepts_tensor_and_pooled_output_shapes() -> None:
    tensor = object()

    class Output:
        pooler_output = tensor

    assert TransformersAdapter._feature_tensor(tensor) is tensor
    assert TransformersAdapter._feature_tensor(Output()) is tensor


def test_classifier_rgb_bounds_large_images() -> None:
    from PIL import Image

    resized = _classifier_rgb(Image.new("RGB", (1000, 500), "white"))

    assert resized.size == (CLASSIFIER_MAX_DIM, CLASSIFIER_MAX_DIM // 2)


def test_clip_onnx_preprocessing_shape_and_normalization() -> None:
    np = pytest.importorskip("numpy")
    from PIL import Image

    pixels = _clip_onnx_pixels(
        [Image.new("RGB", (320, 200), (128, 64, 32))],
        {
            "size": 224,
            "crop_size": 224,
            "image_mean": [0.48145466, 0.4578275, 0.40821073],
            "image_std": [0.26862954, 0.26130258, 0.27577711],
            "resample": 3,
        },
    )

    assert pixels.shape == (1, 3, 224, 224)
    assert pixels.dtype == np.float32
    assert np.isfinite(pixels).all()


def test_clip_onnx_manifest_is_compact_and_self_describing(tmp_path: Path) -> None:
    from manzil_worker.evals.clip_onnx import _write_manifest

    destination = tmp_path / "manifest.json"
    _write_manifest(
        destination,
        variant="int8",
        source_digest="a" * 64,
        preprocessor={"size": 224},
        scene_labels=["kitchen"],
        scene_features=[[0.1, 0.2]],
        diagram_features=[[0.3, 0.4], [0.5, 0.6]],
    )

    manifest = json.loads(destination.read_text())
    assert manifest["schema_version"] == 1
    assert manifest["variant"] == "int8"
    assert manifest["prototypes"]["scene"]["prompts"] == ["a photograph of kitchen"]
