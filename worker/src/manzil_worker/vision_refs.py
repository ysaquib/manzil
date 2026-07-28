"""Criterion-specific, hash-validated VISION reference profiles."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image

from manzil_worker.llm.config import model_for_stage
from manzil_worker.llm.prompt_loader import PROMPTS_DIR, PromptError, load_prompt

VISION_REFS_DIR = Path(__file__).resolve().parents[2] / "prompts" / "vision_refs"
SHEET_SIZE = 1024
CELL_SIZE = SHEET_SIZE // 3


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_reference_manifest(
    root: Path = VISION_REFS_DIR, *, criterion: str = "kitchen_quality"
) -> dict[str, Any] | None:
    path = root / "manifest.json"
    if not path.is_file():
        return None
    try:
        manifest = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    profiles = manifest.get("profiles") if isinstance(manifest, dict) else None
    profile = profiles.get(criterion) if isinstance(profiles, dict) else None
    if (
        not isinstance(profile, dict)
        or profile.get("status") != "approved"
        or not isinstance(profile.get("version"), int)
        or not isinstance(profile.get("prompt_version"), int)
    ):
        return None
    anchors = profile.get("anchors")
    sheets = profile.get("sheets")
    if not isinstance(anchors, list) or not isinstance(sheets, dict):
        return None
    by_level = {rating: [] for rating in range(1, 6)}
    for anchor in anchors:
        if not isinstance(anchor, dict):
            return None
        name = anchor.get("file")
        expected_hash = anchor.get("sha256")
        rating = anchor.get("rating")
        if (
            not isinstance(name, str)
            or not isinstance(expected_hash, str)
            or not isinstance(rating, int)
            or rating not in by_level
        ):
            return None
        asset = root / name
        if not asset.is_file() or _sha(asset) != expected_hash:
            return None
        by_level[rating].append(name)
    if any(len(names) not in range(3, 6) for names in by_level.values()):
        return None
    for rating, names in by_level.items():
        sheet = sheets.get(str(rating))
        if not isinstance(sheet, dict) or sheet.get("members") != names:
            return None
        sheet_path = root / str(sheet.get("file", ""))
        if not sheet_path.is_file() or _sha(sheet_path) != sheet.get("sha256"):
            return None
    return manifest


def build_reference_sheets(
    root: Path = VISION_REFS_DIR, *, criterion: str = "kitchen_quality"
) -> dict[str, dict[str, Any]]:
    """Build deterministic 3-by-2 contain-fitted sheets from normalized WebPs."""
    raw = json.loads((root / "manifest.json").read_text())
    profile = raw["profiles"][criterion]
    anchors = profile["anchors"]
    output: dict[str, dict[str, Any]] = {}
    for rating in range(1, 6):
        members = [a["file"] for a in anchors if a["rating"] == rating]
        canvas = Image.new("RGB", (SHEET_SIZE, SHEET_SIZE), (232, 230, 224))
        for index, name in enumerate(members[:5]):
            with Image.open(root / name) as opened:
                image = opened.convert("RGB")
                image.thumbnail((CELL_SIZE - 16, SHEET_SIZE // 2 - 16), Image.Resampling.LANCZOS)
                column, row = index % 3, index // 3
                x = column * CELL_SIZE + (CELL_SIZE - image.width) // 2
                y = row * (SHEET_SIZE // 2) + (SHEET_SIZE // 2 - image.height) // 2
                canvas.paste(image, (x, y))
        target = root / f"{criterion}-rating-{rating}.webp"
        buffer = io.BytesIO()
        canvas.save(buffer, format="WEBP", quality=82, method=6)
        target.write_bytes(buffer.getvalue())
        output[str(rating)] = {
            "file": target.name,
            "sha256": _sha(target),
            "members": members,
        }
    return output


def vision_references_ready(
    root: Path = VISION_REFS_DIR,
    *,
    prompts_dir: Path = PROMPTS_DIR,
    criterion: str = "kitchen_quality",
) -> bool:
    """Return whether an approved reference profile is released for live VISION.

    Anchor approval and quality release are separate manifest decisions. The
    current kitchen profile was released by an explicit Owner benchmark override
    (DESIGN §20 2026-07-28).
    """
    manifest = load_reference_manifest(root, criterion=criterion)
    if manifest is None:
        return False
    profile = manifest["profiles"][criterion]
    if profile.get("quality_status") != "approved":
        return False
    if profile.get("quality_model") != model_for_stage("vision"):
        return False
    try:
        prompt = load_prompt("vision", prompts_dir=prompts_dir)
    except PromptError:
        return False
    return prompt.version == profile["prompt_version"]
