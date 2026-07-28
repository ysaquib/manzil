"""P3-7b criterion-specific reference assets are an executable fail-closed gate."""

from __future__ import annotations

import hashlib
import io
import json

from manzil_worker.vision_refs import (
    build_reference_sheets,
    load_reference_manifest,
    vision_references_ready,
)
from PIL import Image


def _webp(rating: int, index: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (80, 60), (rating * 35, index * 50, 100)).save(
        output, format="WEBP", quality=82, method=6
    )
    return output.getvalue()


def _write_complete_set(root):  # type: ignore[no-untyped-def]
    anchors = []
    for rating in range(1, 6):
        for index in range(5):
            name = f"level-{rating}-{index}.webp"
            content = _webp(rating, index)
            (root / name).write_bytes(content)
            anchors.append(
                {
                    "file": name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "rating": rating,
                }
            )
    manifest = {
        "version": 1,
        "profiles": {
            "kitchen_quality": {
                "version": 1,
                "prompt_version": 1,
                "status": "approved",
                "quality_status": "approved",
                "quality_model": "anthropic/claude-sonnet-4.6",
                "anchors": anchors,
                "sheets": {},
            }
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    manifest["profiles"]["kitchen_quality"]["sheets"] = build_reference_sheets(root)
    (root / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def _write_prompt(root, version: int = 1):  # type: ignore[no-untyped-def]
    root.mkdir(exist_ok=True)
    (root / "vision.md").write_text(f"---\nid: vision\nversion: {version}\n---\nAnchored.\n")


def test_complete_approved_hashed_set_is_ready(tmp_path) -> None:  # type: ignore[no-untyped-def]
    expected = _write_complete_set(tmp_path)
    prompts = tmp_path / "prompts"
    _write_prompt(prompts)
    assert load_reference_manifest(tmp_path) == expected
    assert vision_references_ready(tmp_path, prompts_dir=prompts)


def test_repository_kitchen_profile_is_released() -> None:
    manifest = load_reference_manifest()
    assert manifest is not None
    profile = manifest["profiles"]["kitchen_quality"]
    assert profile["quality_status"] == "approved"
    assert profile["quality_benchmark_status"] == "deferred_owner_override"
    assert profile["quality_model"] == "anthropic/claude-sonnet-4.6"
    assert vision_references_ready()


def test_changed_asset_hash_fails_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _write_complete_set(tmp_path)
    prompts = tmp_path / "prompts"
    _write_prompt(prompts)
    (tmp_path / "level-3-1.webp").write_bytes(b"changed")
    assert not vision_references_ready(tmp_path, prompts_dir=prompts)


def test_unapproved_or_incomplete_set_fails_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    manifest = _write_complete_set(tmp_path)
    prompts = tmp_path / "prompts"
    _write_prompt(prompts)
    manifest["profiles"]["kitchen_quality"]["status"] = "draft"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert not vision_references_ready(tmp_path, prompts_dir=prompts)


def test_reference_approval_without_bench_release_stays_fail_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    manifest = _write_complete_set(tmp_path)
    prompts = tmp_path / "prompts"
    _write_prompt(prompts)
    manifest["profiles"]["kitchen_quality"]["quality_status"] = "pending_external_bench"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert load_reference_manifest(tmp_path) == manifest
    assert not vision_references_ready(tmp_path, prompts_dir=prompts)


def test_prompt_version_must_match_manifest(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _write_complete_set(tmp_path)
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, version=2)
    assert not vision_references_ready(tmp_path, prompts_dir=prompts)


def test_quality_model_must_match_manifest(tmp_path) -> None:  # type: ignore[no-untyped-def]
    manifest = _write_complete_set(tmp_path)
    prompts = tmp_path / "prompts"
    _write_prompt(prompts)
    manifest["profiles"]["kitchen_quality"]["quality_model"] = "google/gemini-3-flash-preview"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert not vision_references_ready(tmp_path, prompts_dir=prompts)
