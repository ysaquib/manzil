"""Optional local ONNX shadow classifier for IMAGE_CLASSIFY.

The parent API/worker process never imports ONNX Runtime. It invokes this
module in a short-lived subprocess so the 512 MB Render service can reclaim
model memory before a later Playwright Job. Shadow output is observational:
it never changes image kind, target selection, VISION, or SCORE.
"""

from __future__ import annotations

import asyncio
import base64
import gc
import hashlib
import json
import resource
import sys
import time
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import BaseModel, Field

ONNX_SHADOW_BACKEND = "clip-vit-b32-vision-uint8-onnx"
ONNX_SHADOW_ARTIFACT_SHA256 = "af06481c9b95daa042c9d89f7c2412c845f98aca3706e1cc2d23e7dad853a00b"
ONNX_SHADOW_KITCHEN_THRESHOLD = 0.7033675909042358
ONNX_SHADOW_DIAGRAM_THRESHOLD = 0.9717867374420166
ONNX_SHADOW_CACHE_KEY = f"{ONNX_SHADOW_BACKEND}:{ONNX_SHADOW_ARTIFACT_SHA256}:thresholds-v1"
ONNX_SHADOW_TIMEOUT_SECONDS = 60.0


class ONNXShadowError(ValueError):
    """The optional model artifact or subprocess result is unusable."""


class ONNXShadowPrediction(BaseModel):
    content_hash: str
    predicted_scene: str
    kitchen_score: float
    kitchen_predicted: bool
    diagram_score: float
    diagram_predicted: bool


class ONNXShadowBatch(BaseModel):
    cache_key: str
    backend: str
    artifact_sha256: str
    kitchen_threshold: float
    diagram_threshold: float
    elapsed_seconds: float
    peak_rss_mb: float | None = None
    predictions: list[ONNXShadowPrediction] = Field(default_factory=list)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_digest(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and ".cache" not in candidate.relative_to(path).parts
    )
    for candidate in files:
        relative = candidate.relative_to(path).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(_sha256(candidate)))
    return digest.hexdigest()


def clip_pixel_values(images: Sequence[Image.Image], config: dict[str, Any]) -> Any:
    try:
        import numpy as np
    except ImportError as error:
        raise ONNXShadowError(f"NumPy is unavailable: {error}") from error
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


class ClipONNXRuntime:
    """Low-memory CPU runtime shared by the public benchmark and shadow child."""

    def __init__(
        self,
        model_dir: Path,
        *,
        expected_digest: str | None = None,
        expected_variant: str | None = None,
    ) -> None:
        try:
            import numpy as np
            import onnxruntime as ort
        except ImportError as error:
            raise ONNXShadowError(
                "ONNX runtime dependencies are missing; install the `vision-onnx` extra"
            ) from error
        if expected_digest is not None:
            actual_digest = artifact_digest(model_dir)
            if actual_digest != expected_digest:
                raise ONNXShadowError(
                    "ONNX artifact digest mismatch: "
                    f"expected {expected_digest}, got {actual_digest}"
                )
        try:
            manifest = json.loads((model_dir / "manifest.json").read_text())
        except (OSError, ValueError) as error:
            raise ONNXShadowError(
                f"cannot read ONNX manifest under {model_dir}: {error}"
            ) from error
        if manifest.get("schema_version") != 1:
            raise ONNXShadowError("unsupported ONNX manifest schema")
        if expected_variant is not None and manifest.get("variant") != expected_variant:
            raise ONNXShadowError(
                f"expected ONNX variant {expected_variant}, got {manifest.get('variant')}"
            )
        scene = manifest["prototypes"]["scene"]
        self.scene_labels = list(scene["labels"])
        self._scene_features = np.asarray(scene["features"], dtype=np.float32)
        self._diagram_features = np.asarray(
            manifest["prototypes"]["diagram"]["features"], dtype=np.float32
        )
        self._preprocessing = manifest["preprocessing"]
        self._np = np
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        options.add_session_config_entry("session.disable_prepacking", "1")
        self._session = ort.InferenceSession(
            str(model_dir / "model.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )

    def image_features(self, images: Sequence[Image.Image]) -> Any:
        pixels = clip_pixel_values(images, self._preprocessing)
        return self._session.run(["image_features"], {"pixel_values": pixels})[0]

    def probabilities(self, features: Any, prototypes: Any) -> Any:
        logits = 100.0 * features @ prototypes.T
        logits -= logits.max(axis=-1, keepdims=True)
        exponentials = self._np.exp(logits)
        return exponentials / exponentials.sum(axis=-1, keepdims=True)

    def scene_probabilities(self, features: Any) -> Any:
        return self.probabilities(features, self._scene_features)

    def diagram_probabilities(self, features: Any) -> Any:
        return self.probabilities(features, self._diagram_features)

    def close(self) -> None:
        del self._session
        gc.collect()


def classify_shadow_images(model_dir: Path, images: Sequence[tuple[str, bytes]]) -> ONNXShadowBatch:
    started = time.monotonic()
    runtime = ClipONNXRuntime(
        model_dir,
        expected_digest=ONNX_SHADOW_ARTIFACT_SHA256,
        expected_variant="uint8",
    )
    kitchen_indices = [
        index
        for index, label in enumerate(runtime.scene_labels)
        if label in {"kitchen", "restaurant_kitchen"}
    ]
    predictions: list[ONNXShadowPrediction] = []
    try:
        for content_hash, encoded in images:
            try:
                with Image.open(BytesIO(encoded)) as image:
                    rgb = image.convert("RGB")
            except (OSError, ValueError) as error:
                raise ONNXShadowError(
                    f"cannot decode shadow image {content_hash}: {error}"
                ) from error
            features = runtime.image_features([rgb])
            scene = runtime.scene_probabilities(features)[0]
            diagram = runtime.diagram_probabilities(features)[0]
            kitchen_score = float(scene[kitchen_indices].sum())
            diagram_score = float(diagram[0])
            predictions.append(
                ONNXShadowPrediction(
                    content_hash=content_hash,
                    predicted_scene=runtime.scene_labels[int(scene.argmax())],
                    kitchen_score=kitchen_score,
                    kitchen_predicted=kitchen_score >= ONNX_SHADOW_KITCHEN_THRESHOLD,
                    diagram_score=diagram_score,
                    diagram_predicted=diagram_score >= ONNX_SHADOW_DIAGRAM_THRESHOLD,
                )
            )
    finally:
        runtime.close()
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB; Darwin reports bytes. Production Docker is Linux, but
    # normalize macOS so development and production logs use the same unit.
    peak_rss_mb = peak_rss / (1024 * 1024) if sys.platform == "darwin" else peak_rss / 1024
    return ONNXShadowBatch(
        cache_key=ONNX_SHADOW_CACHE_KEY,
        backend=ONNX_SHADOW_BACKEND,
        artifact_sha256=ONNX_SHADOW_ARTIFACT_SHA256,
        kitchen_threshold=ONNX_SHADOW_KITCHEN_THRESHOLD,
        diagram_threshold=ONNX_SHADOW_DIAGRAM_THRESHOLD,
        elapsed_seconds=time.monotonic() - started,
        peak_rss_mb=peak_rss_mb,
        predictions=predictions,
    )


async def run_shadow_subprocess(
    model_dir: Path,
    images: Sequence[tuple[str, bytes]],
    *,
    timeout_seconds: float = ONNX_SHADOW_TIMEOUT_SECONDS,
) -> ONNXShadowBatch:
    started = time.monotonic()
    payload = {
        "model_dir": str(model_dir),
        "images": [
            {"content_hash": content_hash, "data": base64.b64encode(data).decode("ascii")}
            for content_hash, data in images
        ],
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "manzil_worker.vision_onnx",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(json.dumps(payload, separators=(",", ":")).encode()),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ONNXShadowError(f"ONNX shadow exceeded {timeout_seconds:g}s") from None
    if process.returncode != 0:
        detail = stderr.decode(errors="replace").strip()[-1000:]
        raise ONNXShadowError(
            f"ONNX shadow subprocess exited {process.returncode}: {detail or 'no stderr'}"
        )
    try:
        batch = ONNXShadowBatch.model_validate_json(stdout)
    except ValueError as error:
        raise ONNXShadowError(f"invalid ONNX shadow subprocess output: {error}") from error
    return batch.model_copy(update={"elapsed_seconds": time.monotonic() - started})


def _child_main() -> None:
    try:
        payload = json.load(sys.stdin)
        images = [
            (str(item["content_hash"]), base64.b64decode(item["data"], validate=True))
            for item in payload["images"]
        ]
        result = classify_shadow_images(Path(payload["model_dir"]), images)
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    sys.stdout.write(result.model_dump_json())


if __name__ == "__main__":
    _child_main()
