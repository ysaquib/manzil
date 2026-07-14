"""P3-7b's reference asset is an executable, fail-closed gate."""

from __future__ import annotations

import hashlib
import json

from manzil_worker.vision_refs import load_reference_manifest, vision_references_ready


def _write_complete_set(root):  # type: ignore[no-untyped-def]
    references = []
    for rating in range(1, 6):
        for index in range(3):
            name = f"level-{rating}-{index}.webp"
            content = f"reference {rating} {index}".encode()
            (root / name).write_bytes(content)
            references.append(
                {
                    "file": name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "ratings": {"kitchen_quality": rating, "flooring_quality": rating},
                }
            )
    manifest = {
        "version": 1,
        "prompt_version": 1,
        "status": "approved",
        "references": references,
    }
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
    manifest["status"] = "draft"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert not vision_references_ready(tmp_path, prompts_dir=prompts)


def test_prompt_version_must_match_manifest(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _write_complete_set(tmp_path)
    prompts = tmp_path / "prompts"
    _write_prompt(prompts, version=2)
    assert not vision_references_ready(tmp_path, prompts_dir=prompts)
