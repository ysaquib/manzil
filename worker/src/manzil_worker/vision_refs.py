"""Versioned reference-set gate for P3-7 VISION.

No reference assets are committed yet.  This loader deliberately requires a
complete manifest plus every named file before VISION can enter a live plan.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from manzil_worker.llm.prompt_loader import PROMPTS_DIR, PromptError, load_prompt

VISION_REFS_DIR = Path(__file__).resolve().parents[2] / "prompts" / "vision_refs"
VISION_CRITERIA = ("kitchen_quality", "flooring_quality")


def load_reference_manifest(root: Path = VISION_REFS_DIR) -> dict[str, Any] | None:
    path = root / "manifest.json"
    if not path.is_file():
        return None
    try:
        manifest = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if (
        not isinstance(manifest, dict)
        or not isinstance(manifest.get("version"), int)
        or not isinstance(manifest.get("prompt_version"), int)
        or manifest.get("status") != "approved"
    ):
        return None
    references = manifest.get("references")
    if not isinstance(references, list):
        return None
    coverage = {criterion: {rating: 0 for rating in range(1, 6)} for criterion in VISION_CRITERIA}
    for reference in references:
        if not isinstance(reference, dict):
            return None
        name, expected_hash, ratings = (
            reference.get("file"),
            reference.get("sha256"),
            reference.get("ratings"),
        )
        if not isinstance(name, str) or not isinstance(expected_hash, str):
            return None
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            return None
        if not isinstance(ratings, dict) or not ratings:
            return None
        for criterion, rating in ratings.items():
            if (
                criterion not in coverage
                or not isinstance(rating, int)
                or rating not in range(1, 6)
            ):
                return None
            coverage[criterion][rating] += 1
    if any(count not in range(3, 5) for levels in coverage.values() for count in levels.values()):
        return None
    return manifest


def vision_references_ready(
    root: Path = VISION_REFS_DIR, *, prompts_dir: Path = PROMPTS_DIR
) -> bool:
    manifest = load_reference_manifest(root)
    if manifest is None:
        return False
    try:
        prompt = load_prompt("vision", prompts_dir=prompts_dir)
    except PromptError:
        return False
    return prompt.version == manifest["prompt_version"]
