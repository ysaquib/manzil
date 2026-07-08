"""P0-11: bench label schema, catalog validation, skeleton scaffolding.

The labels themselves are human-only; this tests the machinery that keeps a
typo'd or unfinished label from ever silently mis-grading a bench run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from manzil_worker.evals.labels import (
    BenchLabel,
    LabelError,
    load_label,
    load_labels,
    skeleton_payload,
    write_skeleton,
)
from manzil_worker.stages.schema_gen import extractable_entries


def valid_payload() -> dict[str, object]:
    return {
        "slug": "rent.com--example",
        "url": "https://www.rent.com/example",
        "labeled_at": "2026-07-07",
        "criteria": {"beds": 2, "pets_policy": "cats_and_dogs"},
        "unknown": ["dishwasher"],
        "floor_plans": [{"plan_name": "A1", "beds": 2, "baths": 1.0, "rent_min": 1500.0}],
    }


def write_label(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload))
    return path


def test_valid_label_loads(tmp_path: Path) -> None:
    label = load_label(write_label(tmp_path / "x.json", valid_payload()))
    assert label.criteria["beds"] == 2
    assert label.graded_keys() == {"beds", "pets_policy", "dishwasher"}
    assert label.floor_plans is not None and label.floor_plans[0].plan_name == "A1"


def test_omitted_floor_plans_means_plans_not_graded(tmp_path: Path) -> None:
    payload = valid_payload()
    del payload["floor_plans"]
    assert load_label(write_label(tmp_path / "x.json", payload)).floor_plans is None


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"criteria": {"kitchen_vibes": 5}}, "not an extractable catalog key"),
        ({"unknown": ["kitchen_vibes"]}, "not an extractable catalog key"),
        ({"criteria": {"pets_policy": "gerbils_only"}}, "violates the catalog schema"),
        ({"criteria": {"beds": "two"}}, "violates the catalog schema"),
        ({"criteria": {"beds": None}}, "null"),
        (
            {"criteria": {"beds": 2}, "unknown": ["beds"]},
            "both criteria and unknown",
        ),
    ],
)
def test_untrustworthy_labels_fail_loudly(
    tmp_path: Path, mutation: dict[str, object], match: str
) -> None:
    payload = valid_payload() | mutation
    with pytest.raises(LabelError, match=match):
        load_label(write_label(tmp_path / "x.json", payload))


def test_vision_and_composed_keys_are_not_labelable(tmp_path: Path) -> None:
    """Labels grade page-text extraction only: kitchen_quality needs vision,
    all_in_monthly is pipeline-composed (§9.5) — both refused."""
    for key in ("kitchen_quality", "all_in_monthly"):
        payload = valid_payload() | {"criteria": {key: 1}}
        with pytest.raises(LabelError, match="not an extractable catalog key"):
            load_label(write_label(tmp_path / "x.json", payload))


def test_load_labels_sorted_and_empty_dir_is_empty(tmp_path: Path) -> None:
    assert load_labels(tmp_path / "missing") == []
    write_label(tmp_path / "b.json", valid_payload() | {"slug": "b"})
    write_label(tmp_path / "a.json", valid_payload() | {"slug": "a"})
    assert [label.slug for label in load_labels(tmp_path)] == ["a", "b"]


# ── skeleton scaffolding ─────────────────────────────────────────────────────


def make_corpus_page(corpus: Path, slug: str, url: str) -> None:
    page = corpus / slug
    page.mkdir(parents=True)
    (page / "meta.json").write_text(json.dumps({"url": url}))
    (page / "cleaned.txt").write_text("cleaned")


def test_skeleton_prefills_every_extractable_key_as_null(tmp_path: Path) -> None:
    corpus, labels = tmp_path / "corpus", tmp_path / "labels"
    make_corpus_page(corpus, "rent.com--x", "https://rent.com/x")
    path = write_skeleton("rent.com--x", corpus_dir=corpus, labels_dir=labels)

    payload = json.loads(path.read_text())
    assert payload["url"] == "https://rent.com/x"
    assert set(payload["criteria"]) == {e.key for e in extractable_entries()}
    assert all(v is None for v in payload["criteria"].values())
    # An unfilled skeleton must never pass as a finished label.
    with pytest.raises(LabelError, match="null"):
        load_label(path)


def test_skeleton_appends_manifest_row_with_slug_site_tier(tmp_path: Path) -> None:
    corpus, labels = tmp_path / "corpus", tmp_path / "labels"
    page = corpus / "rent.com--x"
    page.mkdir(parents=True)
    (page / "meta.json").write_text(json.dumps({"url": "https://rent.com/x", "tier": 2}))
    write_skeleton("rent.com--x", corpus_dir=corpus, labels_dir=labels)

    manifest = (labels.parent / "manifest.md").read_text()
    assert "| rent.com--x | rent.com | 2 | | | |" in manifest


def test_skeleton_manifest_row_is_idempotent_and_preserves_edits(tmp_path: Path) -> None:
    corpus, labels = tmp_path / "corpus", tmp_path / "labels"
    make_corpus_page(corpus, "rent.com--x", "https://rent.com/x")
    write_skeleton("rent.com--x", corpus_dir=corpus, labels_dir=labels)

    # Human fills in the trait columns on the scaffolded row.
    manifest_path = labels.parent / "manifest.md"
    lines = [
        "| rent.com--x | rent.com |  | sparse page | tier-1 shell | 2026-07-07 |\n"
        if line.startswith("| rent.com--x |")
        else line
        for line in manifest_path.read_text().splitlines(keepends=True)
    ]
    manifest_path.write_text("".join(lines))

    # A --force re-scaffold must not duplicate the row or clobber the edits.
    write_skeleton("rent.com--x", corpus_dir=corpus, labels_dir=labels, force=True)
    final = manifest_path.read_text()
    assert sum(line.startswith("| rent.com--x |") for line in final.splitlines()) == 1
    assert "sparse page" in final


def test_skeleton_refuses_overwrite_without_force(tmp_path: Path) -> None:
    corpus, labels = tmp_path / "corpus", tmp_path / "labels"
    make_corpus_page(corpus, "rent.com--x", "https://rent.com/x")
    write_skeleton("rent.com--x", corpus_dir=corpus, labels_dir=labels)
    with pytest.raises(LabelError, match="--force"):
        write_skeleton("rent.com--x", corpus_dir=corpus, labels_dir=labels)
    write_skeleton("rent.com--x", corpus_dir=corpus, labels_dir=labels, force=True)


def test_skeleton_requires_a_saved_corpus_page(tmp_path: Path) -> None:
    with pytest.raises(LabelError, match="save-page"):
        write_skeleton("ghost--page", corpus_dir=tmp_path / "corpus", labels_dir=tmp_path / "l")


def test_skeleton_payload_is_a_valid_benchlabel_shape() -> None:
    # Shape-valid (parses as BenchLabel) even though content-invalid (nulls).
    label = BenchLabel.model_validate(skeleton_payload("s", "https://x.test"))
    assert label.labeled_at is None
