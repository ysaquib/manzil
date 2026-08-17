"""P0-11: bench label schema, catalog validation, skeleton scaffolding.

The labels themselves are human-only; this tests the machinery that keeps a
typo'd or unfinished label from ever silently mis-grading a bench run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from manzil_worker.evals.labels import (
    BenchLabel,
    IncompleteLabelError,
    LabelError,
    load_label,
    load_labels,
    load_labels_split,
    scoped_coverage_audit,
    scoped_tranche_coverage_audit,
    skeleton_payload,
    write_skeleton,
)
from manzil_worker.stages.schema_gen import extractable_entries


def valid_payload() -> dict[str, object]:
    return {
        "slug": "rent.com--example",
        "url": "https://www.rent.com/example",
        "labeled_at": "2026-07-07",
        "criteria": {"min_lease_months": 12, "pets_policy": "cats_and_dogs"},
        "unknown": ["dishwasher"],
        "floor_plans": [{"plan_name": "A1", "beds": 2, "baths": 1.0, "rent_min": 1500.0}],
    }


def write_label(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload))
    return path


def test_valid_label_loads(tmp_path: Path) -> None:
    label = load_label(write_label(tmp_path / "x.json", valid_payload()))
    assert label.criteria["min_lease_months"] == 12
    assert label.graded_keys() == {"min_lease_months", "pets_policy", "dishwasher"}
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
        ({"criteria": {"min_lease_months": "twelve"}}, "violates the catalog schema"),
        ({"criteria": {"min_lease_months": None}}, "null"),
        (
            {"criteria": {"min_lease_months": 12}, "unknown": ["min_lease_months"]},
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
    assert load_labels(labels_dir=tmp_path / "missing") == []
    write_label(tmp_path / "b.json", valid_payload() | {"slug": "b"})
    write_label(tmp_path / "a.json", valid_payload() | {"slug": "a"})
    assert [label.slug for label in load_labels(labels_dir=tmp_path)] == ["a", "b"]


# ── skeleton labels are skipped, not fatal (bench-run) ───────────────────────


@pytest.mark.parametrize(
    "mutation",
    [
        {"criteria": {"min_lease_months": None}},  # a null criteria value
        {"labeled_at": None},  # undated = unfinished skeleton
    ],
)
def test_incomplete_label_raises_incomplete_subclass(
    tmp_path: Path, mutation: dict[str, object]
) -> None:
    """A skeleton/unfinished label raises IncompleteLabelError — still a
    LabelError (existing callers unchanged) but distinguishable so bench-run can
    skip it instead of aborting."""
    payload = valid_payload() | mutation
    with pytest.raises(IncompleteLabelError):
        load_label(write_label(tmp_path / "x.json", payload))


def test_load_labels_split_partitions_skeletons_from_gradeable(tmp_path: Path) -> None:
    write_label(tmp_path / "good.json", valid_payload() | {"slug": "good"})
    write_label(tmp_path / "skel.json", valid_payload() | {"slug": "skel", "labeled_at": None})
    write_label(
        tmp_path / "nullcrit.json",
        valid_payload() | {"slug": "nullcrit", "criteria": {"min_lease_months": None}},
    )

    loaded, skipped = load_labels_split(labels_dir=tmp_path)

    assert [label.slug for label in loaded] == ["good"]
    assert {s.slug for s in skipped} == {"skel", "nullcrit"}
    assert all("null" in s.reason for s in skipped)


def test_load_labels_split_still_raises_on_broken_labels(tmp_path: Path) -> None:
    """A typo'd catalog key is a trust failure, never a skip — it must still
    abort the run loudly rather than be silently partitioned away."""
    write_label(tmp_path / "typo.json", valid_payload() | {"criteria": {"kitchen_vibes": 5}})
    with pytest.raises(LabelError, match="not an extractable catalog key"):
        load_labels_split(labels_dir=tmp_path)


def test_load_labels_split_validates_all_labels_before_partitioning(tmp_path: Path) -> None:
    write_label(tmp_path / "good.json", valid_payload() | {"slug": "good"})
    write_label(
        tmp_path / "bad-a.json",
        valid_payload() | {"slug": "bad-a", "criteria": {"kitchen_vibes": 5}},
    )
    write_label(
        tmp_path / "bad-b.json",
        valid_payload() | {"slug": "bad-b", "criteria": {"kitchen_vibes": 6}},
    )

    with pytest.raises(LabelError) as error:
        load_labels_split(labels_dir=tmp_path)

    message = str(error.value)
    assert "bad-a" in message
    assert "bad-b" in message
    assert "kitchen_vibes" in message


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
    scoped = {
        "patio_balcony",
        "private_entry",
        "in_unit_laundry",
        "parking",
        "cooling",
        "dishwasher",
        "walk_in_closets",
        "pantry",
        "disposal",
        "fireplace",
        "ceiling_fans",
        "stainless_steel_appliances",
        "is_renovated",
        "flooring_materials",
        "heating_type",
    }
    assert set(payload["criteria"]) == {e.key for e in extractable_entries()} - (
        scoped - {"heating_type"}
    )
    assert all(v is None for v in payload["criteria"].values())
    assert set(payload["scoped_claims"]) == scoped
    assert all(claims == [] for claims in payload["scoped_claims"].values())
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


def test_scoped_label_validates_targets_and_claim_schema(tmp_path: Path) -> None:
    payload = valid_payload()
    payload["unknown"] = []
    payload["floor_plans"] = [
        {
            "response_key": "a1",
            "plan_name": "A1",
            "beds": 2,
            "baths": 1.0,
            "rent_min": 1500.0,
        }
    ]
    payload["scoped_claims"] = {
        "dishwasher": [
            {
                "value": True,
                "applicability": "specific_floor_plans",
                "floor_plan_refs": ["a1"],
            }
        ]
    }
    label = load_label(write_label(tmp_path / "x.json", payload))
    assert label.scoped_claims["dishwasher"][0].floor_plan_refs == ["a1"]

    payload["scoped_claims"]["dishwasher"][0]["floor_plan_refs"] = ["invented"]
    with pytest.raises(LabelError, match="unknown label Floor Plans"):
        load_label(write_label(tmp_path / "x.json", payload))


def _scoped_claim_payload(scoped_claims: dict[str, object]) -> dict[str, object]:
    payload = valid_payload()
    payload["unknown"] = []
    payload["floor_plans"] = [
        {
            "response_key": "a1",
            "plan_name": "A1",
            "beds": 2,
            "baths": 1.0,
            "rent_min": 1500.0,
        }
    ]
    payload["scoped_claims"] = scoped_claims
    return payload


def test_multi_claim_parking_allows_distinct_values_at_generalized_scope(tmp_path: Path) -> None:
    payload = _scoped_claim_payload(
        {
            "parking": [
                {"value": "carport", "applicability": "unit_scope_unspecified"},
                {"value": "garage", "applicability": "all_units"},
                {"value": "dedicated_lot", "applicability": "unit_scope_unspecified"},
            ]
        },
    )
    label = load_label(write_label(tmp_path / "x.json", payload))
    assert len(label.scoped_claims["parking"]) == 3


def test_multi_claim_parking_rejects_duplicate_value_at_same_target(tmp_path: Path) -> None:
    payload = _scoped_claim_payload(
        {
            "parking": [
                {"value": "carport", "applicability": "unit_scope_unspecified"},
                {"value": "carport", "applicability": "all_units"},
            ]
        },
    )
    with pytest.raises(LabelError, match="duplicates the same value"):
        load_label(write_label(tmp_path / "x.json", payload))


def test_multi_claim_parking_rejects_none_with_positive_at_same_target(tmp_path: Path) -> None:
    payload = _scoped_claim_payload(
        {
            "parking": [
                {"value": "carport", "applicability": "unit_scope_unspecified"},
                {"value": "none", "applicability": "all_units"},
            ]
        },
    )
    with pytest.raises(LabelError, match="none cannot coexist"):
        load_label(write_label(tmp_path / "x.json", payload))


def test_boolean_scoped_claim_allows_only_one_value_per_target(tmp_path: Path) -> None:
    payload = _scoped_claim_payload(
        {
            "dishwasher": [
                {"value": True, "applicability": "unit_scope_unspecified"},
                {"value": True, "applicability": "all_units"},
            ]
        },
    )
    with pytest.raises(LabelError, match="duplicates a concrete claim target"):
        load_label(write_label(tmp_path / "x.json", payload))


def test_multi_claim_parking_allows_exact_and_generalized_targets(tmp_path: Path) -> None:
    payload = _scoped_claim_payload(
        {
            "parking": [
                {"value": "carport", "applicability": "unit_scope_unspecified"},
                {
                    "value": "garage",
                    "applicability": "specific_floor_plans",
                    "floor_plan_refs": ["a1"],
                },
            ]
        },
    )
    label = load_label(write_label(tmp_path / "x.json", payload))
    assert len(label.scoped_claims["parking"]) == 2


def test_scoped_heating_label_uses_utility_claim_vocabulary(tmp_path: Path) -> None:
    payload = valid_payload()
    payload["unknown"] = []
    payload["scoped_claims"] = {
        "heating_type": [
            {
                "value": "gas",
                "applicability": "all_units",
                "floor_plan_refs": [],
            }
        ]
    }
    label = load_label(write_label(tmp_path / "x.json", payload))
    assert label.scoped_claims["heating_type"][0].value == "gas"

    payload["scoped_claims"]["heating_type"][0]["value"] = "oil"
    with pytest.raises(LabelError, match="must be gas or electric"):
        load_label(write_label(tmp_path / "x.json", payload))


def test_ambiguous_diagram_label_cannot_name_a_plan(tmp_path: Path) -> None:
    payload = valid_payload()
    payload["floor_plans"] = [
        {
            "response_key": "a1",
            "plan_name": "A1",
            "beds": 2,
            "baths": 1.0,
            "rent_min": 1500.0,
        }
    ]
    payload["diagram_associations"] = [
        {"candidate_ref": "diagram-1", "ambiguous": True, "floor_plan_refs": ["a1"]}
    ]
    with pytest.raises(LabelError, match="ambiguous"):
        load_label(write_label(tmp_path / "x.json", payload))


def test_scoped_coverage_audit_reports_only_human_label_cases() -> None:
    label = BenchLabel.model_validate(
        {
            "slug": "coverage",
            "url": "https://example.test",
            "labeled_at": "2026-07-27",
            "floor_plans": [
                {"response_key": "a1", "plan_name": "A1"},
                {"response_key": "a2", "plan_name": "A2"},
            ],
            "scoped_claims": {
                "dishwasher": [
                    {
                        "value": False,
                        "applicability": "specific_floor_plans",
                        "floor_plan_refs": ["a1", "a2"],
                    }
                ],
                "parking": [],
            },
            "diagram_associations": [
                {"candidate_ref": "ambiguous", "ambiguous": True},
                {
                    "candidate_ref": "a1-diagram",
                    "ambiguous": False,
                    "floor_plan_refs": ["a1"],
                },
            ],
        }
    )
    coverage = scoped_coverage_audit([label])
    assert coverage["exact"] == ["coverage"]
    assert coverage["negative"] == ["coverage"]
    assert coverage["missing"] == ["coverage"]
    assert coverage["shared_plan"] == ["coverage"]
    assert coverage["diagram_ambiguous"] == ["coverage"]
    assert coverage["diagram_unambiguous"] == ["coverage"]
    assert coverage["all_units"] == []


def test_scoped_tranche_audit_is_per_criterion_and_requires_explicit_missing() -> None:
    label = BenchLabel.model_validate(
        {
            "slug": "tranche",
            "url": "https://example.test",
            "labeled_at": "2026-07-29",
            "floor_plans": [{"response_key": "a1", "plan_name": "A1"}],
            "scoped_claims": {
                "fireplace": [
                    {
                        "value": True,
                        "applicability": "select_units",
                        "floor_plan_refs": [],
                    },
                    {
                        "value": False,
                        "applicability": "unit_scope_unspecified",
                        "floor_plan_refs": [],
                    },
                ],
                "pantry": [],
                "flooring_materials": [
                    {
                        "value": ["hardwood", "tile"],
                        "applicability": "specific_floor_plans",
                        "floor_plan_refs": ["a1"],
                    }
                ],
            },
        }
    )

    coverage = scoped_tranche_coverage_audit([label])
    assert coverage["fireplace"]["positive"] == ["tranche"]
    assert coverage["fireplace"]["negative"] == ["tranche"]
    assert coverage["fireplace"]["select_units"] == ["tranche"]
    assert coverage["fireplace"]["unit_scope_unspecified"] == ["tranche"]
    assert coverage["pantry"]["missing"] == ["tranche"]
    assert coverage["flooring_materials"]["exact"] == ["tranche"]
    assert coverage["walk_in_closets"]["missing"] == []
