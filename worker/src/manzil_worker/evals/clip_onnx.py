"""Build reproducible vision-only ONNX artifacts from the local CLIP checkpoint.

The production-shaped artifact contains only the image tower and fixed text
prototype embeddings. PyTorch and Transformers are export-time dependencies;
runtime inference needs Pillow, NumPy, and ONNX Runtime only.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from manzil_worker.evals.vision_ml_benchmark import (
    _artifact_digest,
    _display_label,
    load_mit_split,
)

CLIP_SOURCE_DIR = Path("models/clip-vit-base-patch32")
CLIP_ONNX_FP32_DIR = Path("models/clip-vision-onnx-fp32")
CLIP_ONNX_INT8_DIR = Path("models/clip-vision-onnx-int8")
CLIP_ONNX_UINT8_DIR = Path("models/clip-vision-onnx-uint8")
ONNX_FILENAME = "model.onnx"
MANIFEST_FILENAME = "manifest.json"
EXPORT_SCHEMA_VERSION = 1

DIAGRAM_PROMPTS = (
    "an architectural floor plan diagram or unit layout drawing",
    "a photograph of a real indoor room",
)


class ClipONNXExportError(ValueError):
    """The local CLIP checkpoint cannot be exported or validated."""


def _imports() -> tuple[Any, Any, Any, Any, Any]:
    try:
        import numpy as np
        import onnx
        import onnxruntime as ort
        import torch
        from transformers import AutoModel, AutoProcessor
    except ImportError as error:
        raise ClipONNXExportError(
            "ONNX export dependencies are missing; run with the worker's "
            f"`vision-bench` extra ({error})"
        ) from error
    return np, onnx, ort, torch, (AutoModel, AutoProcessor)


def _feature_tensor(features: Any) -> Any:
    pooled = getattr(features, "pooler_output", None)
    return pooled if pooled is not None else features


def _normalized_text_features(
    model: Any, processor: Any, prompts: Sequence[str]
) -> list[list[float]]:
    import torch

    max_length = int(model.config.text_config.max_position_embeddings)
    inputs = processor(
        text=list(prompts),
        padding="max_length",
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    with torch.inference_mode():
        features = _feature_tensor(model.get_text_features(**dict(inputs)))
        features = features / features.norm(dim=-1, keepdim=True)
    return features.detach().cpu().tolist()


def _write_manifest(
    destination: Path,
    *,
    variant: str,
    source_digest: str,
    preprocessor: dict[str, Any],
    scene_labels: Sequence[str],
    scene_features: list[list[float]],
    diagram_features: list[list[float]],
) -> None:
    scene_prompts = [f"a photograph of {_display_label(label)}" for label in scene_labels]
    manifest = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "variant": variant,
        "source_model": "openai/clip-vit-base-patch32",
        "source_artifact_sha256": source_digest,
        "onnx_opset": 17,
        "input_name": "pixel_values",
        "output_name": "image_features",
        "preprocessing": preprocessor,
        "prototypes": {
            "scene": {
                "labels": list(scene_labels),
                "prompts": scene_prompts,
                "features": scene_features,
            },
            "diagram": {
                "labels": ["floor_plan_diagram", "indoor_photograph"],
                "prompts": list(DIAGRAM_PROMPTS),
                "features": diagram_features,
            },
        },
    }
    destination.write_text(json.dumps(manifest, separators=(",", ":")) + "\n")


def export_clip_onnx(root: Path, *, overwrite: bool = False) -> dict[str, Any]:
    """Export FP32 and dynamic-int8 image towers plus fixed public-bench prototypes."""
    np, onnx, ort, torch, transformer_classes = _imports()
    AutoModel, AutoProcessor = transformer_classes
    source_dir = root / CLIP_SOURCE_DIR
    if not source_dir.is_dir():
        raise ClipONNXExportError(f"missing local CLIP checkpoint: {source_dir}")
    destinations = {
        "fp32": root / CLIP_ONNX_FP32_DIR,
        "int8": root / CLIP_ONNX_INT8_DIR,
        "uint8": root / CLIP_ONNX_UINT8_DIR,
    }
    existing = [destination for destination in destinations.values() if destination.exists()]
    if existing and not overwrite:
        raise ClipONNXExportError(
            f"output already exists: {existing[0]}; pass --overwrite to replace it"
        )
    for destination in destinations.values():
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)

    processor = AutoProcessor.from_pretrained(source_dir, local_files_only=True, use_fast=False)
    model = AutoModel.from_pretrained(source_dir, local_files_only=True).eval()
    scene_labels = sorted({example.label for example in load_mit_split(root, "train", per_class=1)})
    scene_prompts = [f"a photograph of {_display_label(label)}" for label in scene_labels]
    scene_features = _normalized_text_features(model, processor, scene_prompts)
    diagram_features = _normalized_text_features(model, processor, DIAGRAM_PROMPTS)

    class VisionProjection(torch.nn.Module):
        def __init__(self, clip: Any) -> None:
            super().__init__()
            self.vision_model = clip.vision_model
            self.visual_projection = clip.visual_projection

        def forward(self, pixel_values: Any) -> Any:
            pooled = self.vision_model(pixel_values=pixel_values).pooler_output
            features = self.visual_projection(pooled)
            return features / features.norm(dim=-1, keepdim=True)

    wrapper = VisionProjection(model).eval()
    sample = torch.zeros((1, 3, 224, 224), dtype=torch.float32)
    fp32_path = destinations["fp32"] / ONNX_FILENAME
    with torch.inference_mode():
        expected = wrapper(sample).detach().cpu().numpy()
        torch.onnx.export(
            wrapper,
            (sample,),
            fp32_path,
            input_names=["pixel_values"],
            output_names=["image_features"],
            dynamic_axes={
                "pixel_values": {0: "batch"},
                "image_features": {0: "batch"},
            },
            opset_version=17,
            dynamo=False,
        )
    onnx.checker.check_model(onnx.load(fp32_path))

    fp32_session = ort.InferenceSession(str(fp32_path), providers=["CPUExecutionProvider"])
    actual = fp32_session.run(["image_features"], {"pixel_values": sample.numpy()})[0]
    fp32_max_abs_error = float(np.max(np.abs(expected - actual)))
    if fp32_max_abs_error > 1e-4:
        raise ClipONNXExportError(f"FP32 ONNX parity error {fp32_max_abs_error:.6g} exceeds 1e-4")

    from onnxruntime.quantization import QuantType, quantize_dynamic

    int8_path = destinations["int8"] / ONNX_FILENAME
    quantize_dynamic(
        str(fp32_path),
        str(int8_path),
        weight_type=QuantType.QInt8,
        per_channel=True,
        op_types_to_quantize=["MatMul"],
    )
    onnx.checker.check_model(onnx.load(int8_path))
    int8_session = ort.InferenceSession(str(int8_path), providers=["CPUExecutionProvider"])
    quantized = int8_session.run(["image_features"], {"pixel_values": sample.numpy()})[0]
    int8_max_abs_error = float(np.max(np.abs(expected - quantized)))

    uint8_path = destinations["uint8"] / ONNX_FILENAME
    quantize_dynamic(
        str(fp32_path),
        str(uint8_path),
        weight_type=QuantType.QUInt8,
        per_channel=True,
        op_types_to_quantize=["MatMul"],
    )
    onnx.checker.check_model(onnx.load(uint8_path))
    uint8_session = ort.InferenceSession(str(uint8_path), providers=["CPUExecutionProvider"])
    unsigned = uint8_session.run(["image_features"], {"pixel_values": sample.numpy()})[0]
    uint8_max_abs_error = float(np.max(np.abs(expected - unsigned)))

    preprocessor = json.loads((source_dir / "preprocessor_config.json").read_text())
    source_digest = _artifact_digest(source_dir)
    for variant, destination in destinations.items():
        _write_manifest(
            destination / MANIFEST_FILENAME,
            variant=variant,
            source_digest=source_digest,
            preprocessor=preprocessor,
            scene_labels=scene_labels,
            scene_features=scene_features,
            diagram_features=diagram_features,
        )

    del fp32_session, int8_session, uint8_session, wrapper, model
    return {
        "fp32": {
            "path": str(fp32_path),
            "bytes": fp32_path.stat().st_size,
            "max_abs_error": fp32_max_abs_error,
        },
        "int8": {
            "path": str(int8_path),
            "bytes": int8_path.stat().st_size,
            "max_abs_error": int8_max_abs_error,
        },
        "uint8": {
            "path": str(uint8_path),
            "bytes": uint8_path.stat().st_size,
            "max_abs_error": uint8_max_abs_error,
        },
    }
