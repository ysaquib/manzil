"""P0-12/P0-13: eval harness grading + report, and the compare table.

Proven on the synthetic e2e page whose ground truth we authored
(fixtures/pages/e2e_listing.html + conftest.maple_extraction) — the real
bench swaps in human labels over real corpus pages, same machinery."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from conftest import PAGES, FakeLLM, maple_extraction
from manzil_worker.evals.compare import compare_table
from manzil_worker.evals.harness import (
    BenchReport,
    gate_keys_from,
    report_text,
    run_bench,
)
from manzil_worker.evals.labels import BenchLabel
from manzil_worker.fetching.cleaner import clean_html
from manzil_worker.phase0_rubric import phase0_rubric
from manzil_worker.stages.base import StageCtx

SLUG = "example.test--maple"
URL = "https://example.test/listing"

GATE_KEYS = gate_keys_from(phase0_rubric())


def make_corpus(tmp_path: Path) -> Path:
    corpus = tmp_path / "corpus"
    page = corpus / SLUG
    page.mkdir(parents=True)
    cleaned = clean_html((PAGES / "e2e_listing.html").read_text()).text
    (page / "cleaned.txt").write_text(cleaned)
    return corpus


def truth_label(**overrides: Any) -> BenchLabel:
    """The e2e page's ground truth, derived from the authored extraction:
    non-null values become criteria, not_found keys become unknown."""
    payload = maple_extraction()
    criteria = {
        key: field["value"]
        for key, field in payload.items()
        if key != "floor_plans" and field["value"] is not None
    }
    unknown = [
        key for key, field in payload.items() if key != "floor_plans" and field["value"] is None
    ]
    data: dict[str, Any] = {
        "slug": SLUG,
        "url": URL,
        "labeled_at": "2026-07-07",
        "criteria": criteria,
        "unknown": unknown,
        "floor_plans": payload["floor_plans"],
    }
    data.update(overrides)
    return BenchLabel.model_validate(data)


def perfect_ctx() -> StageCtx:
    return StageCtx(
        call_structured=FakeLLM({"extract": maple_extraction(), "verify": {"contradictions": []}}),
        rubric=phase0_rubric(),
    )


def run(labels: list[BenchLabel], corpus: Path, ctx: StageCtx) -> BenchReport:
    return asyncio.run(run_bench(labels, corpus_dir=corpus, ctx=ctx, gate_keys=GATE_KEYS))


def test_perfect_extraction_grades_perfectly(tmp_path: Path) -> None:
    report = run([truth_label()], make_corpus(tmp_path), perfect_ctx())

    [listing] = report.listings
    assert listing.error is None
    assert listing.criterion_accuracy == 1.0
    assert listing.gate_accuracy == 1.0
    assert listing.evidence_flags == 0
    assert listing.plans is not None
    assert listing.plans.matched == 1 and not listing.plans.missing
    assert listing.plans.field_ok == listing.plans.field_checks > 0
    assert report.summary["criterion_accuracy"] == 1.0
    assert report.summary["failed"] == 0
    assert report.models["extract"]  # pins recorded for compare provenance


def test_wrong_value_and_invented_unknown_both_lose_points(tmp_path: Path) -> None:
    # Truth disagrees with the model on beds (label says 3) and claims the
    # page doesn't state pets_policy (model extracted a value -> invented).
    label = truth_label()
    label.criteria["beds"] = 3
    label.unknown.append("pets_policy")
    del label.criteria["pets_policy"]

    report = run([label], make_corpus(tmp_path), perfect_ctx())
    [listing] = report.listings
    assert listing.criteria["beds"].ok is False
    assert listing.criteria["beds"].got == 2
    assert listing.criteria["pets_policy"].kind == "unknown"
    assert listing.criteria["pets_policy"].ok is False  # value where truth says none
    # beds and pets_policy are both gate keys under the Phase 0 rubric.
    assert listing.gate_accuracy is not None and listing.gate_accuracy < 1.0


def test_not_found_where_truth_has_value_is_wrong_not_crash(tmp_path: Path) -> None:
    payload = maple_extraction()
    payload["beds"] = {"value": None, "confidence": "not_found", "evidence_quote": None}
    ctx = StageCtx(
        call_structured=FakeLLM({"extract": payload, "verify": {"contradictions": []}}),
        rubric=phase0_rubric(),
    )
    report = run([truth_label()], make_corpus(tmp_path), ctx)
    assert report.listings[0].criteria["beds"].ok is False
    assert report.listings[0].criteria["beds"].got is None


def test_plan_grading_flags_missing_and_extra_plans(tmp_path: Path) -> None:
    label = truth_label(
        floor_plans=[
            {"plan_name": "The Maple", "beds": 2, "rent_min": 1700.0},
            {"plan_name": "The Oak", "beds": 3},  # truth has a plan the model missed
        ]
    )
    report = run([label], make_corpus(tmp_path), perfect_ctx())
    plans = report.listings[0].plans
    assert plans is not None
    assert plans.matched == 1
    assert plans.missing == ["The Oak"]
    assert plans.extra == []


def test_missing_corpus_page_fails_that_listing_only(tmp_path: Path) -> None:
    ghost = truth_label(slug="rent.com--ghost")
    report = run([ghost, truth_label()], make_corpus(tmp_path), perfect_ctx())

    ghost_result, maple_result = report.listings
    assert ghost_result.error is not None and "save-page" in ghost_result.error
    assert maple_result.error is None
    assert report.summary["failed"] == 1
    assert "FAILED" in report_text(report)


def test_compare_table_lines_up_reports_side_by_side(tmp_path: Path) -> None:
    corpus = make_corpus(tmp_path)
    good = run([truth_label()], corpus, perfect_ctx())

    label = truth_label()
    label.criteria["beds"] = 3  # degrade one answer for a visible delta
    worse = run([label], corpus, perfect_ctx())

    table = compare_table({"haiku": good, "flash-lite": worse})
    assert "| metric | haiku | flash-lite |" in table
    assert "| extract model |" in table
    assert "| gate accuracy | 1.0 |" in table
    assert "| total cost $ |" in table
