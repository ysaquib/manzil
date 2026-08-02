"""Offline pretrained-model benchmark for IMAGE_CLASSIFY.

This harness is intentionally separate from the production LLM seam. It makes
no provider calls and never reads the duplicate-heavy local human-label kit for
model selection. Public labels calibrate deterministic thresholds on training
splits and grade frozen models on held-out splits:

* MIT Indoor 67: kitchen-vs-rest and 67-way scene recognition.
* CubiCasa5K validation: Floor Plan diagram detection against MIT photographs.

Heavy libraries are imported lazily so ordinary worker installs and CI do not
acquire PyTorch/Transformers/PyArrow. Run with the ``vision-bench`` extra.
"""

from __future__ import annotations

import gc
import hashlib
import json
import math
import platform
import resource
import sys
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, Protocol

from PIL import Image

VISION_ML_BENCH_DIR = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "vision_benchmark"
)
DEFAULT_VISION_ML_REPORT = (
    Path(__file__).resolve().parents[3] / "evals" / "reports" / "vision-ml-benchmark.json"
)

MODEL_NAMES = (
    "siglip2",
    "clip",
    "clip-onnx",
    "clip-onnx-int8",
    "clip-onnx-uint8",
    "places365",
)
KITCHEN_LABELS = frozenset({"kitchen", "restaurant_kitchen"})
PLACES365_SHA256 = "2f4759217d470da2b803f8f66cd4488a066406b555a5fb95ee9a4663f9f05588"
CLASSIFIER_MAX_DIM = 384

_MODEL_PATHS = {
    "siglip2": "models/siglip2-base-patch16-224",
    "clip": "models/clip-vit-base-patch32",
    "clip-onnx": "models/clip-vision-onnx-fp32",
    "clip-onnx-int8": "models/clip-vision-onnx-int8",
    "clip-onnx-uint8": "models/clip-vision-onnx-uint8",
    "places365": "models/places365-resnet18",
}
_MODEL_DISPLAY_NAMES = {
    "siglip2": "google/siglip2-base-patch16-224",
    "clip": "openai/clip-vit-base-patch32",
    "clip-onnx": "CLIP ViT-B/32 vision-only ONNX FP32",
    "clip-onnx-int8": "CLIP ViT-B/32 vision-only ONNX int8",
    "clip-onnx-uint8": "CLIP ViT-B/32 vision-only ONNX uint8",
    "places365": "Places365 ResNet-18",
}
_REQUIRED_MODEL_FILES = {
    "siglip2": (
        "config.json",
        "model.safetensors",
        "preprocessor_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ),
    "clip": (
        "config.json",
        "pytorch_model.bin",
        "preprocessor_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
        "merges.txt",
    ),
    "clip-onnx": ("model.onnx", "manifest.json"),
    "clip-onnx-int8": ("model.onnx", "manifest.json"),
    "clip-onnx-uint8": ("model.onnx", "manifest.json"),
    "places365": (
        "resnet18_places365.pth.tar",
        "categories_places365.txt",
        "IO_places365.txt",
    ),
}


class VisionMLBenchError(ValueError):
    """The local artifacts or benchmark configuration are not usable."""


@dataclass(frozen=True)
class MITExample:
    image_id: str
    label: str
    path: Path


@dataclass(frozen=True)
class BinaryMetrics:
    threshold: float
    count: int
    positives: int
    negatives: int
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float | None
    recall: float | None
    specificity: float | None
    f1: float | None
    accuracy: float
    auroc: float | None


@dataclass(frozen=True)
class DiagramResult:
    supported: bool
    reason: str | None = None
    calibration_count: int = 0
    evaluation_count: int = 0
    metrics: BinaryMetrics | None = None


@dataclass(frozen=True)
class ModelResult:
    model: str
    artifact_bytes: int
    artifact_sha256: str
    device: str
    batch_size: int
    elapsed_seconds: float
    images_per_second: float
    peak_rss_mb: float
    kitchen_calibration_count: int
    kitchen_evaluation_count: int
    kitchen: BinaryMetrics
    scene_top1_accuracy: float
    scene_top1_correct: int
    diagram: DiagramResult


@dataclass(frozen=True)
class BenchmarkReport:
    schema_version: int
    run_at: str
    profile: str
    benchmark_root: str
    platform: dict[str, str]
    methodology: dict[str, Any]
    results: tuple[ModelResult, ...]


class ModelAdapter(Protocol):
    name: str
    device: str
    supports_diagram: bool

    def predict_scenes(self, images: Sequence[Image.Image]) -> tuple[list[float], list[str]]:
        """Return kitchen scores and predicted MIT-compatible scene names."""

    def predict_diagrams(self, images: Sequence[Image.Image]) -> list[float]:
        """Return a Floor Plan diagram score per image."""

    def close(self) -> None: ...


def _optional_import_error(error: ImportError) -> VisionMLBenchError:
    return VisionMLBenchError(
        "vision benchmark dependencies are missing; run with "
        "`uv run --package manzil-worker --extra vision-bench manzil vision-ml-bench` "
        f"({error})"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_files(path: Path) -> list[Path]:
    return sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and ".cache" not in candidate.relative_to(path).parts
    )


def _artifact_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for candidate in _artifact_files(path):
        relative = candidate.relative_to(path).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(_sha256(candidate)))
    return digest.hexdigest()


def validate_artifacts(root: Path, models: Sequence[str]) -> None:
    unknown = sorted(set(models) - set(MODEL_NAMES))
    if unknown:
        raise VisionMLBenchError(f"unknown benchmark model(s): {', '.join(unknown)}")
    for model_name in models:
        model_dir = root / _MODEL_PATHS[model_name]
        missing = [
            name for name in _REQUIRED_MODEL_FILES[model_name] if not (model_dir / name).is_file()
        ]
        if missing:
            raise VisionMLBenchError(
                f"{model_name}: missing downloaded file(s) under {model_dir}: " + ", ".join(missing)
            )
    places_checkpoint = root / _MODEL_PATHS["places365"] / "resnet18_places365.pth.tar"
    if "places365" in models and _sha256(places_checkpoint) != PLACES365_SHA256:
        raise VisionMLBenchError("Places365 checkpoint SHA-256 does not match the pinned artifact")

    mit_dir = root / "datasets" / "mit-indoor-67"
    cubi_dir = root / "datasets" / "cubicasa5k"
    for required in (mit_dir / "Images", mit_dir / "TrainImages.txt", mit_dir / "TestImages.txt"):
        if not required.exists():
            raise VisionMLBenchError(f"missing MIT Indoor 67 artifact: {required}")
    if not list((cubi_dir / "data").glob("train-*.parquet")):
        raise VisionMLBenchError(f"missing CubiCasa5K training shards under {cubi_dir / 'data'}")
    if not list((cubi_dir / "data").glob("valid-*.parquet")):
        raise VisionMLBenchError(f"missing CubiCasa5K validation shards under {cubi_dir / 'data'}")


def load_mit_split(
    root: Path, split: Literal["train", "test"], *, per_class: int | None = None
) -> list[MITExample]:
    """Read the published split deterministically, optionally capped per class."""
    split_file = (
        root
        / "datasets"
        / "mit-indoor-67"
        / ("TrainImages.txt" if split == "train" else "TestImages.txt")
    )
    image_root = split_file.parent / "Images"
    try:
        relative_paths = [
            line.strip() for line in split_file.read_text().splitlines() if line.strip()
        ]
    except OSError as error:
        raise VisionMLBenchError(f"cannot read MIT split {split_file}: {error}") from error
    counts: dict[str, int] = {}
    examples: list[MITExample] = []
    for relative in relative_paths:
        label, separator, _ = relative.partition("/")
        if not separator:
            raise VisionMLBenchError(f"invalid MIT split entry: {relative!r}")
        if per_class is not None and counts.get(label, 0) >= per_class:
            continue
        path = image_root / relative
        if not path.is_file():
            raise VisionMLBenchError(f"MIT split references missing image: {path}")
        counts[label] = counts.get(label, 0) + 1
        examples.append(MITExample(image_id=f"mit:{split}:{relative}", label=label, path=path))
    if len(counts) != 67:
        raise VisionMLBenchError(f"MIT {split} split has {len(counts)} classes, expected 67")
    if per_class is not None and any(count != per_class for count in counts.values()):
        raise VisionMLBenchError(f"MIT {split} split cannot supply {per_class} images per class")
    return examples


def _classifier_rgb(image: Image.Image) -> Image.Image:
    """Mirror IMAGE_CLASSIFY's bounded thumbnail geometry before model resize."""
    image.draft("RGB", (CLASSIFIER_MAX_DIM, CLASSIFIER_MAX_DIM))
    rgb = image.convert("RGB")
    rgb.thumbnail(
        (CLASSIFIER_MAX_DIM, CLASSIFIER_MAX_DIM),
        Image.Resampling.LANCZOS,
        reducing_gap=3.0,
    )
    return rgb


def _load_rgb(path: Path) -> Image.Image:
    try:
        with Image.open(path) as image:
            return _classifier_rgb(image)
    except (OSError, ValueError) as error:
        raise VisionMLBenchError(f"cannot decode benchmark image {path}: {error}") from error


def _cubi_image_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, dict) and isinstance(value.get("bytes"), bytes):
        return value["bytes"]
    raise VisionMLBenchError("CubiCasa Parquet image column does not contain embedded bytes")


def iter_cubicasa(
    root: Path, split: Literal["train", "valid"], *, limit: int
) -> Iterator[tuple[str, Image.Image]]:
    """Stream embedded CubiCasa images without extracting a second dataset copy."""
    try:
        import pyarrow.parquet as pq
    except ImportError as error:
        raise _optional_import_error(error) from error
    emitted = 0
    shards = sorted((root / "datasets" / "cubicasa5k" / "data").glob(f"{split}-*.parquet"))
    for shard in shards:
        parquet = pq.ParquetFile(shard)
        for record_batch in parquet.iter_batches(batch_size=32, columns=["image_id", "image"]):
            ids = record_batch.column(0).to_pylist()
            images = record_batch.column(1).to_pylist()
            for image_id, encoded in zip(ids, images, strict=True):
                try:
                    with Image.open(BytesIO(_cubi_image_bytes(encoded))) as image:
                        rgb = _classifier_rgb(image)
                except (OSError, ValueError) as error:
                    raise VisionMLBenchError(
                        f"cannot decode CubiCasa image {image_id}: {error}"
                    ) from error
                yield f"cubicasa:{split}:{image_id}", rgb
                emitted += 1
                if emitted >= limit:
                    return
    if emitted < limit:
        raise VisionMLBenchError(f"CubiCasa {split} supplied {emitted} images, expected {limit}")


def _chunks[T](values: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _iter_chunks[T](values: Iterable[T], size: int) -> Iterator[list[T]]:
    batch: list[T] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _normalize_label(value: str) -> str:
    aliases = {
        "living_room": "livingroom",
        "restaurant_kitchen": "restaurant_kitchen",
        "staircase": "stairscase",  # spelling used by MIT Indoor 67
        "childs_room": "children_room",
        "kindergarten_classroom": "kindergarden",
        "bowling_alley": "bowling",
        "indoor_swimming_pool": "poolinside",
    }
    normalized = value.rsplit("/", 1)[-1].strip().replace(" ", "_")
    return aliases.get(normalized, normalized)


def _display_label(label: str) -> str:
    replacements = {
        "livingroom": "living room",
        "restaurant_kitchen": "restaurant kitchen",
        "stairscase": "staircase",
        "kindergarden": "kindergarten",
        "poolinside": "indoor swimming pool",
    }
    return replacements.get(label, label.replace("_", " "))


class TransformersAdapter:
    supports_diagram = True

    def __init__(
        self, name: str, model_dir: Path, scene_labels: Sequence[str], *, device: str
    ) -> None:
        try:
            import torch
            from transformers import AutoModel, AutoProcessor
        except ImportError as error:
            raise _optional_import_error(error) from error
        self.name = name
        self.device = device
        self._torch = torch
        # Pin the saved slow processor explicitly. Transformers otherwise plans
        # to flip this default, which would silently change benchmark pixels.
        self._processor = AutoProcessor.from_pretrained(
            model_dir, local_files_only=True, use_fast=False
        )
        self._model = AutoModel.from_pretrained(model_dir, local_files_only=True).to(device).eval()
        self._text_max_length = int(self._model.config.text_config.max_position_embeddings)
        self._scene_labels = list(scene_labels)
        scene_prompts = [f"a photograph of {_display_label(label)}" for label in scene_labels]
        self._scene_features = self._text_features(scene_prompts)
        self._diagram_features = self._text_features(
            [
                "an architectural floor plan diagram or unit layout drawing",
                "a photograph of a real indoor room",
            ]
        )

    def _to_device(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {key: value.to(self.device) for key, value in inputs.items()}

    @staticmethod
    def _feature_tensor(features: Any) -> Any:
        """Normalize Transformers 4.x tensor and 5.x pooled-output APIs."""
        pooled = getattr(features, "pooler_output", None)
        return pooled if pooled is not None else features

    def _text_features(self, prompts: Sequence[str]) -> Any:
        torch = self._torch
        inputs = self._processor(
            text=list(prompts),
            padding="max_length",
            truncation=True,
            max_length=self._text_max_length,
            return_tensors="pt",
        )
        with torch.inference_mode():
            features = self._feature_tensor(
                self._model.get_text_features(**self._to_device(dict(inputs)))
            )
            features = features / features.norm(dim=-1, keepdim=True)
        return features

    def _image_features(self, images: Sequence[Image.Image]) -> Any:
        torch = self._torch
        inputs = self._processor(images=list(images), return_tensors="pt")
        with torch.inference_mode():
            features = self._feature_tensor(
                self._model.get_image_features(**self._to_device(dict(inputs)))
            )
            return features / features.norm(dim=-1, keepdim=True)

    def predict_scenes(self, images: Sequence[Image.Image]) -> tuple[list[float], list[str]]:
        similarities = 100.0 * self._image_features(images) @ self._scene_features.T
        probabilities = similarities.softmax(dim=-1)
        kitchen_indices = [
            index for index, label in enumerate(self._scene_labels) if label in KITCHEN_LABELS
        ]
        scores = probabilities[:, kitchen_indices].sum(dim=-1).detach().cpu().tolist()
        predicted_indices = probabilities.argmax(dim=-1).detach().cpu().tolist()
        predicted = [self._scene_labels[index] for index in predicted_indices]
        return [float(score) for score in scores], predicted

    def predict_diagrams(self, images: Sequence[Image.Image]) -> list[float]:
        similarities = 100.0 * self._image_features(images) @ self._diagram_features.T
        return [float(score) for score in similarities.softmax(dim=-1)[:, 0].detach().cpu()]

    def close(self) -> None:
        del self._model
        gc.collect()
        if self.device == "cuda":
            self._torch.cuda.empty_cache()
        elif self.device == "mps":
            self._torch.mps.empty_cache()


class Places365Adapter:
    supports_diagram = False

    def __init__(self, model_dir: Path, *, device: str) -> None:
        try:
            import torch
            from torchvision import models, transforms
        except ImportError as error:
            raise _optional_import_error(error) from error
        self.name = "places365"
        self.device = device
        self._torch = torch
        categories = []
        for line in (model_dir / "categories_places365.txt").read_text().splitlines():
            raw, _, _index = line.rpartition(" ")
            categories.append(_normalize_label(raw.lstrip("/")))
        if len(categories) != 365:
            raise VisionMLBenchError(f"Places365 category file has {len(categories)} rows")
        self._categories = categories
        self._kitchen_indices = [
            index for index, label in enumerate(categories) if label in KITCHEN_LABELS
        ]
        model = models.resnet18(weights=None, num_classes=365)
        checkpoint = torch.load(
            model_dir / "resnet18_places365.pth.tar", map_location="cpu", weights_only=True
        )
        state = checkpoint.get("state_dict", checkpoint)
        state = {key.removeprefix("module."): value for key, value in state.items()}
        model.load_state_dict(state)
        self._model = model.to(device).eval()
        self._transform = transforms.Compose(
            [
                transforms.Resize(256),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )

    def predict_scenes(self, images: Sequence[Image.Image]) -> tuple[list[float], list[str]]:
        torch = self._torch
        batch = torch.stack([self._transform(image) for image in images]).to(self.device)
        with torch.inference_mode():
            probabilities = self._model(batch).softmax(dim=-1)
        scores = probabilities[:, self._kitchen_indices].sum(dim=-1).detach().cpu().tolist()
        predicted_indices = probabilities.argmax(dim=-1).detach().cpu().tolist()
        return (
            [float(score) for score in scores],
            [self._categories[index] for index in predicted_indices],
        )

    def predict_diagrams(self, images: Sequence[Image.Image]) -> list[float]:
        raise VisionMLBenchError("Places365 has no Floor Plan diagram class")

    def close(self) -> None:
        del self._model
        gc.collect()
        if self.device == "cuda":
            self._torch.cuda.empty_cache()
        elif self.device == "mps":
            self._torch.mps.empty_cache()


def _clip_onnx_pixels(images: Sequence[Image.Image], config: dict[str, Any]) -> Any:
    try:
        import numpy as np
    except ImportError as error:
        raise _optional_import_error(error) from error
    size_value = config.get("size", 224)
    size = int(size_value.get("shortest_edge", 224) if isinstance(size_value, dict) else size_value)
    crop_value = config.get("crop_size", 224)
    if isinstance(crop_value, dict):
        crop_height = int(crop_value.get("height", 224))
        crop_width = int(crop_value.get("width", 224))
    else:
        crop_height = crop_width = int(crop_value)
    mean = np.asarray(config["image_mean"], dtype=np.float32).reshape(3, 1, 1)
    std = np.asarray(config["image_std"], dtype=np.float32).reshape(3, 1, 1)
    resample = Image.Resampling(int(config.get("resample", Image.Resampling.BICUBIC)))
    pixels = []
    for image in images:
        width, height = image.size
        if width <= height:
            resized_width = size
            resized_height = int(size * height / width)
        else:
            resized_height = size
            resized_width = int(size * width / height)
        resized = image.resize((resized_width, resized_height), resample=resample)
        left = max(0, (resized_width - crop_width) // 2)
        top = max(0, (resized_height - crop_height) // 2)
        cropped = resized.crop((left, top, left + crop_width, top + crop_height))
        array = np.asarray(cropped, dtype=np.float32) / np.float32(255.0)
        chw = np.transpose(array, (2, 0, 1))
        pixels.append((chw - mean) / std)
    return np.stack(pixels).astype(np.float32, copy=False)


class ClipONNXAdapter:
    supports_diagram = True

    def __init__(
        self, name: str, model_dir: Path, scene_labels: Sequence[str], *, device: str
    ) -> None:
        if device != "cpu":
            raise VisionMLBenchError("CLIP ONNX benchmark currently supports only --device cpu")
        try:
            import numpy as np
            import onnxruntime as ort
        except ImportError as error:
            raise _optional_import_error(error) from error
        self.name = name
        self.device = device
        self._np = np
        manifest = json.loads((model_dir / "manifest.json").read_text())
        if manifest.get("schema_version") != 1:
            raise VisionMLBenchError(f"{name}: unsupported ONNX manifest schema")
        scene = manifest["prototypes"]["scene"]
        if list(scene_labels) != scene["labels"]:
            raise VisionMLBenchError(f"{name}: prototype labels do not match the MIT split")
        self._scene_labels = list(scene_labels)
        self._scene_features = np.asarray(scene["features"], dtype=np.float32)
        self._diagram_features = np.asarray(
            manifest["prototypes"]["diagram"]["features"], dtype=np.float32
        )
        self._preprocessing = manifest["preprocessing"]
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # One thread is deliberate for the shared 0.5-CPU Render target and
        # prevents local benchmarks from hiding deployment contention.
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        # ORT otherwise creates prepacked copies of large MatMul weights. The
        # small Render target values peak memory more than a modest warm-speed
        # gain, and the original ONNX initializers remain memory-mapped.
        options.add_session_config_entry("session.disable_prepacking", "1")
        self._session = ort.InferenceSession(
            str(model_dir / "model.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )

    def _image_features(self, images: Sequence[Image.Image]) -> Any:
        pixels = _clip_onnx_pixels(images, self._preprocessing)
        return self._session.run(["image_features"], {"pixel_values": pixels})[0]

    def _probabilities(self, images: Sequence[Image.Image], prototypes: Any) -> Any:
        logits = 100.0 * self._image_features(images) @ prototypes.T
        logits -= logits.max(axis=-1, keepdims=True)
        exponentials = self._np.exp(logits)
        return exponentials / exponentials.sum(axis=-1, keepdims=True)

    def predict_scenes(self, images: Sequence[Image.Image]) -> tuple[list[float], list[str]]:
        probabilities = self._probabilities(images, self._scene_features)
        kitchen_indices = [
            index for index, label in enumerate(self._scene_labels) if label in KITCHEN_LABELS
        ]
        scores = probabilities[:, kitchen_indices].sum(axis=-1).tolist()
        predicted = [self._scene_labels[index] for index in probabilities.argmax(axis=-1)]
        return [float(score) for score in scores], predicted

    def predict_diagrams(self, images: Sequence[Image.Image]) -> list[float]:
        probabilities = self._probabilities(images, self._diagram_features)
        return [float(score) for score in probabilities[:, 0].tolist()]

    def close(self) -> None:
        del self._session
        gc.collect()


def create_adapter(
    model_name: str, root: Path, scene_labels: Sequence[str], *, device: str
) -> ModelAdapter:
    model_dir = root / _MODEL_PATHS[model_name]
    if model_name in {"siglip2", "clip"}:
        return TransformersAdapter(model_name, model_dir, scene_labels, device=device)
    if model_name in {"clip-onnx", "clip-onnx-int8", "clip-onnx-uint8"}:
        return ClipONNXAdapter(model_name, model_dir, scene_labels, device=device)
    if model_name == "places365":
        return Places365Adapter(model_dir, device=device)
    raise VisionMLBenchError(f"unknown benchmark model: {model_name}")


def _auroc(labels: Sequence[bool], scores: Sequence[float]) -> float | None:
    positives = sum(labels)
    negatives = len(labels) - positives
    if not positives or not negatives:
        return None
    ordered = sorted(zip(scores, labels, strict=True), key=lambda item: item[0])
    rank_sum = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        average_rank = ((index + 1) + end) / 2
        rank_sum += average_rank * sum(label for _, label in ordered[index:end])
        index = end
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def binary_metrics(
    labels: Sequence[bool], scores: Sequence[float], *, threshold: float
) -> BinaryMetrics:
    if len(labels) != len(scores) or not labels:
        raise VisionMLBenchError("binary metrics require equally sized, non-empty labels/scores")
    predictions = [score >= threshold for score in scores]
    tp = sum(want and got for want, got in zip(labels, predictions, strict=True))
    fp = sum(not want and got for want, got in zip(labels, predictions, strict=True))
    tn = sum(not want and not got for want, got in zip(labels, predictions, strict=True))
    fn = sum(want and not got for want, got in zip(labels, predictions, strict=True))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return BinaryMetrics(
        threshold=threshold,
        count=len(labels),
        positives=sum(labels),
        negatives=len(labels) - sum(labels),
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        precision=precision,
        recall=recall,
        specificity=specificity,
        f1=f1,
        accuracy=(tp + tn) / len(labels),
        auroc=_auroc(labels, scores),
    )


def calibrate_threshold(labels: Sequence[bool], scores: Sequence[float]) -> float:
    """Maximize public-training F1; ties prefer recall, then precision, then margin."""
    if len(labels) != len(scores) or not labels:
        raise VisionMLBenchError("threshold calibration requires equally sized labels/scores")
    unique = sorted(set(float(score) for score in scores))
    thresholds = [
        math.nextafter(unique[0], -math.inf),
        *unique,
        math.nextafter(unique[-1], math.inf),
    ]

    def key(threshold: float) -> tuple[float, float, float, float]:
        metrics = binary_metrics(labels, scores, threshold=threshold)
        return (
            metrics.f1 or 0.0,
            metrics.recall or 0.0,
            metrics.precision or 0.0,
            threshold,
        )

    return max(thresholds, key=key)


def _score_mit(
    adapter: ModelAdapter, examples: Sequence[MITExample], *, batch_size: int
) -> tuple[list[float], list[str]]:
    scores: list[float] = []
    predicted: list[str] = []
    for chunk in _chunks(examples, batch_size):
        images = [_load_rgb(example.path) for example in chunk]
        chunk_scores, chunk_predicted = adapter.predict_scenes(images)
        scores.extend(chunk_scores)
        predicted.extend(chunk_predicted)
    return scores, predicted


def _score_diagram_stream(
    adapter: ModelAdapter,
    examples: Iterable[tuple[str, Image.Image]],
    *,
    batch_size: int,
) -> list[float]:
    scores: list[float] = []
    for chunk in _iter_chunks(examples, batch_size):
        scores.extend(adapter.predict_diagrams([image for _, image in chunk]))
    return scores


def _mit_diagram_negatives(examples: Sequence[MITExample]) -> Iterator[tuple[str, Image.Image]]:
    for example in examples:
        yield example.image_id, _load_rgb(example.path)


def _peak_rss_mb() -> float:
    peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # Linux reports KiB; macOS/BSD reports bytes.
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def _artifact_stats(root: Path, model_name: str) -> tuple[int, str]:
    model_dir = root / _MODEL_PATHS[model_name]
    files = _artifact_files(model_dir)
    return sum(path.stat().st_size for path in files), _artifact_digest(model_dir)


def _profile_sizes(profile: Literal["quick", "full"]) -> tuple[int, int | None, int, int]:
    if profile == "quick":
        return 5, 5, 100, 100
    return 20, None, 748, 748


def run_model_benchmark(
    *,
    root: Path,
    model_name: str,
    profile: Literal["quick", "full"],
    device: str,
    batch_size: int,
) -> ModelResult:
    calibration_per_class, test_per_class, diagram_cal_limit, diagram_eval_limit = _profile_sizes(
        profile
    )
    mit_train = load_mit_split(root, "train", per_class=calibration_per_class)
    mit_test = load_mit_split(root, "test", per_class=test_per_class)
    scene_labels = sorted({example.label for example in mit_train + mit_test})
    adapter = create_adapter(model_name, root, scene_labels, device=device)
    started = time.monotonic()
    images_scored = 0
    try:
        train_scores, _ = _score_mit(adapter, mit_train, batch_size=batch_size)
        images_scored += len(mit_train)
        threshold = calibrate_threshold(
            [example.label in KITCHEN_LABELS for example in mit_train], train_scores
        )
        test_scores, test_predicted = _score_mit(adapter, mit_test, batch_size=batch_size)
        images_scored += len(mit_test)
        kitchen = binary_metrics(
            [example.label in KITCHEN_LABELS for example in mit_test],
            test_scores,
            threshold=threshold,
        )
        scene_correct = sum(
            example.label == predicted
            for example, predicted in zip(mit_test, test_predicted, strict=True)
        )
        if adapter.supports_diagram:
            cubi_cal_scores = _score_diagram_stream(
                adapter,
                iter_cubicasa(root, "train", limit=diagram_cal_limit),
                batch_size=batch_size,
            )
            mit_cal_negatives = mit_train[:diagram_cal_limit]
            mit_cal_scores = _score_diagram_stream(
                adapter,
                _mit_diagram_negatives(mit_cal_negatives),
                batch_size=batch_size,
            )
            diagram_threshold = calibrate_threshold(
                [True] * len(cubi_cal_scores) + [False] * len(mit_cal_scores),
                cubi_cal_scores + mit_cal_scores,
            )
            cubi_eval_scores = _score_diagram_stream(
                adapter,
                iter_cubicasa(root, "valid", limit=diagram_eval_limit),
                batch_size=batch_size,
            )
            mit_eval_negatives = mit_test[:diagram_eval_limit]
            mit_eval_scores = _score_diagram_stream(
                adapter,
                _mit_diagram_negatives(mit_eval_negatives),
                batch_size=batch_size,
            )
            diagram_labels = [True] * len(cubi_eval_scores) + [False] * len(mit_eval_scores)
            diagram = DiagramResult(
                supported=True,
                calibration_count=len(cubi_cal_scores) + len(mit_cal_scores),
                evaluation_count=len(diagram_labels),
                metrics=binary_metrics(
                    diagram_labels,
                    cubi_eval_scores + mit_eval_scores,
                    threshold=diagram_threshold,
                ),
            )
            images_scored += (
                len(cubi_cal_scores)
                + len(mit_cal_scores)
                + len(cubi_eval_scores)
                + len(mit_eval_scores)
            )
        else:
            diagram = DiagramResult(
                supported=False,
                reason="closed Places365 taxonomy has no Floor Plan diagram class",
            )
    finally:
        adapter.close()
    elapsed = time.monotonic() - started
    artifact_bytes, artifact_sha = _artifact_stats(root, model_name)
    return ModelResult(
        model=_MODEL_DISPLAY_NAMES[model_name],
        artifact_bytes=artifact_bytes,
        artifact_sha256=artifact_sha,
        device=device,
        batch_size=batch_size,
        elapsed_seconds=elapsed,
        images_per_second=images_scored / elapsed,
        peak_rss_mb=_peak_rss_mb(),
        kitchen_calibration_count=len(mit_train),
        kitchen_evaluation_count=len(mit_test),
        kitchen=kitchen,
        scene_top1_accuracy=scene_correct / len(mit_test),
        scene_top1_correct=scene_correct,
        diagram=diagram,
    )


def run_benchmark(
    *,
    root: Path = VISION_ML_BENCH_DIR,
    models: Sequence[str] = MODEL_NAMES,
    profile: Literal["quick", "full"] = "full",
    device: str = "cpu",
    batch_size: int = 16,
) -> BenchmarkReport:
    if batch_size < 1:
        raise VisionMLBenchError("batch_size must be positive")
    validate_artifacts(root, models)
    results = tuple(
        run_model_benchmark(
            root=root,
            model_name=model_name,
            profile=profile,
            device=device,
            batch_size=batch_size,
        )
        for model_name in models
    )
    calibration_per_class, test_per_class, diagram_cal_limit, diagram_eval_limit = _profile_sizes(
        profile
    )
    return BenchmarkReport(
        schema_version=1,
        run_at=datetime.now(UTC).isoformat(),
        profile=profile,
        benchmark_root=str(root.resolve()),
        platform={
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "device": device,
        },
        methodology={
            "weights": "frozen; no fine-tuning",
            "kitchen_positive_labels": sorted(KITCHEN_LABELS),
            "mit_calibration_images_per_class": calibration_per_class,
            "mit_test_scope": (
                f"{test_per_class} images per class"
                if test_per_class is not None
                else "complete official 1,340-image TestImages.txt split"
            ),
            "classifier_max_dimension": CLASSIFIER_MAX_DIM,
            "diagram_calibration_positive_limit": diagram_cal_limit,
            "diagram_evaluation_positive_limit": diagram_eval_limit,
            "threshold_rule": "maximum calibration F1; ties recall, precision, threshold",
            "important_limit": (
                "public datasets do not label kitchen quality assessability; "
                "this benchmark grades room routing and Floor Plan rejection only"
            ),
        },
        results=results,
    )


def report_json(report: BenchmarkReport) -> str:
    return json.dumps(asdict(report), indent=2) + "\n"


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def report_markdown(report: BenchmarkReport) -> str:
    lines = [
        "# Pretrained image-classifier benchmark",
        "",
        f"- Run: `{report.run_at}`",
        f"- Profile: `{report.profile}`",
        f"- Platform: `{report.platform['system']} {report.platform['machine']}`",
        f"- Device: `{report.platform['device']}`",
        "- Weights: frozen; public training labels calibrate thresholds only",
        "",
        "| Model | Kitchen precision | Kitchen recall | Kitchen F1 | Scene top-1 | "
        "Diagram F1 | Images/s | Peak RSS | Artifact |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in report.results:
        diagram_f1 = result.diagram.metrics.f1 if result.diagram.metrics else None
        lines.append(
            f"| {result.model} | {_percent(result.kitchen.precision)} | "
            f"{_percent(result.kitchen.recall)} | {_percent(result.kitchen.f1)} | "
            f"{_percent(result.scene_top1_accuracy)} | {_percent(diagram_f1)} | "
            f"{result.images_per_second:.2f} | {result.peak_rss_mb:.0f} MB | "
            f"{result.artifact_bytes / 1_000_000:.0f} MB |"
        )
    lines.extend(
        [
            "",
            "The diagram cell is `n/a` for Places365 because its closed scene taxonomy "
            "has no Floor Plan class.",
            "This benchmark does not validate kitchen-quality assessability; no public "
            "dataset supplies that label.",
            "",
        ]
    )
    return "\n".join(lines)
