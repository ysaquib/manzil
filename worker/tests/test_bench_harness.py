"""P0-12/P0-13: eval harness grading + report, and the compare table.

Proven on the synthetic e2e page whose ground truth we authored
(fixtures/pages/e2e_listing.html + conftest.maple_extraction) — the real
bench swaps in human labels over real corpus pages, same machinery.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from manzil_worker.evals.compare import compare_table
from manzil_worker.evals.harness import (
    BenchReport,
    _corpus_as_of_date,
    gate_keys_from,
    report_text,
    run_bench,
)
from manzil_worker.evals.labels import BenchLabel
from manzil_worker.fetching.cleaner import clean_html
from manzil_worker.phase0_rubric import phase0_rubric
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.extract import AVAILABLE_NOW_SENTINEL
from worker_helpers import PAGES, FakeLLM, field_payload, maple_extraction

SLUG = "example.test--maple"
URL = "https://example.test/listing"
# Default freeze date for synthetic corpus pages (distinct from wall clock).
CORPUS_SAVED_AT = "2026-07-02T18:00:00+00:00"
CORPUS_AS_OF = "2026-07-02"

GATE_KEYS = gate_keys_from(phase0_rubric())


def _write_page(
    corpus: Path,
    slug: str,
    *,
    cleaned: str,
    saved_at: str | None = CORPUS_SAVED_AT,
    meta: dict[str, Any] | None = None,
) -> Path:
    page = corpus / slug
    page.mkdir(parents=True, exist_ok=True)
    (page / "cleaned.txt").write_text(cleaned)
    if meta is not None:
        (page / "meta.json").write_text(json.dumps(meta))
    elif saved_at is not None:
        (page / "meta.json").write_text(
            json.dumps({"url": URL, "saved_at": saved_at, "tier": 1})
        )
    return page


def make_corpus(tmp_path: Path, *, saved_at: str = CORPUS_SAVED_AT) -> Path:
    corpus = tmp_path / "corpus"
    cleaned = clean_html((PAGES / "e2e_listing.html").read_text()).text
    _write_page(corpus, SLUG, cleaned=cleaned, saved_at=saved_at)
    return corpus


def truth_label(**overrides: Any) -> BenchLabel:
    """The e2e page's ground truth, derived from the authored extraction:
    non-null values become criteria, not_found keys become unknown."""
    payload = maple_extraction()
    # Non-catalog blocks carry no {value, ...} wrapper — they are not criteria.
    non_catalog = {"floor_plans", "property_identity"}
    criteria = {
        key: field["value"]
        for key, field in payload.items()
        if key not in non_catalog and field["value"] is not None
    }
    unknown = [
        key for key, field in payload.items() if key not in non_catalog and field["value"] is None
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
    assert listing.as_of_date == CORPUS_AS_OF
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


def test_available_now_label_matches_corpus_saved_at_not_wall_clock(tmp_path: Path) -> None:
    """Phrase-only available_now resolves to corpus saved_at, not StageCtx.today."""
    payload = maple_extraction()
    payload["availability_date"] = field_payload(AVAILABLE_NOW_SENTINEL, "Available Now")
    payload["floor_plans"][0]["availability_date"] = AVAILABLE_NOW_SENTINEL
    payload["floor_plans"][0]["evidence_quote"] = "Available Now"
    # Deliberately wrong wall-clock today — harness must ignore it for bench.
    ctx = StageCtx(
        call_structured=FakeLLM({"extract": payload, "verify": {"contradictions": []}}),
        rubric=phase0_rubric(),
        today=lambda: date(2026, 7, 16),
    )
    label = truth_label()
    label.criteria["availability_date"] = AVAILABLE_NOW_SENTINEL
    label.floor_plans[0].availability_date = AVAILABLE_NOW_SENTINEL

    report = run([label], make_corpus(tmp_path, saved_at=CORPUS_SAVED_AT), ctx)
    [listing] = report.listings
    assert listing.error is None
    assert listing.as_of_date == CORPUS_AS_OF
    assert listing.criteria["availability_date"].ok is True
    assert listing.criteria["availability_date"].got == CORPUS_AS_OF
    assert listing.plans is not None
    assert listing.plans.field_ok == listing.plans.field_checks


def test_explicit_iso_availability_is_not_replaced_by_saved_at(tmp_path: Path) -> None:
    """Explicit dates stay page truth even when the UI also says Available Now."""
    payload = maple_extraction()
    # maple_extraction already emits 2026-08-01; keep it and grade against ISO.
    ctx = StageCtx(
        call_structured=FakeLLM({"extract": payload, "verify": {"contradictions": []}}),
        rubric=phase0_rubric(),
        today=lambda: date(2026, 7, 16),
    )
    report = run([truth_label()], make_corpus(tmp_path, saved_at=CORPUS_SAVED_AT), ctx)
    [listing] = report.listings
    assert listing.error is None
    assert listing.criteria["availability_date"].got == "2026-08-01"
    assert listing.criteria["availability_date"].ok is True
    assert listing.as_of_date == CORPUS_AS_OF  # clock still pinned, but unused for ISO


def test_per_listing_saved_at_clocks_do_not_leak(tmp_path: Path) -> None:
    cleaned = clean_html((PAGES / "e2e_listing.html").read_text()).text
    corpus = tmp_path / "corpus"
    slug_a = "example.test--a"
    slug_b = "example.test--b"
    _write_page(corpus, slug_a, cleaned=cleaned, saved_at="2026-07-01T12:00:00+00:00")
    _write_page(corpus, slug_b, cleaned=cleaned, saved_at="2026-07-10T12:00:00+00:00")

    payload = maple_extraction()
    payload["availability_date"] = field_payload(AVAILABLE_NOW_SENTINEL, "Available Now")
    payload["floor_plans"][0]["availability_date"] = AVAILABLE_NOW_SENTINEL
    payload["floor_plans"][0]["evidence_quote"] = "Available Now"
    ctx = StageCtx(
        call_structured=FakeLLM({"extract": payload, "verify": {"contradictions": []}}),
        rubric=phase0_rubric(),
        today=lambda: date(2099, 1, 1),
    )
    label_a = truth_label(slug=slug_a)
    label_a.criteria["availability_date"] = AVAILABLE_NOW_SENTINEL
    label_a.floor_plans[0].availability_date = AVAILABLE_NOW_SENTINEL
    label_b = truth_label(slug=slug_b)
    label_b.criteria["availability_date"] = AVAILABLE_NOW_SENTINEL
    label_b.floor_plans[0].availability_date = AVAILABLE_NOW_SENTINEL

    report = run([label_a, label_b], corpus, ctx)
    a, b = report.listings
    assert a.error is None and b.error is None
    assert a.as_of_date == "2026-07-01"
    assert b.as_of_date == "2026-07-10"
    assert a.criteria["availability_date"].got == "2026-07-01"
    assert b.criteria["availability_date"].got == "2026-07-10"
    assert a.criteria["availability_date"].ok is True
    assert b.criteria["availability_date"].ok is True


@pytest.mark.parametrize(
    "meta, match",
    [
        (None, "missing meta.json"),
        ({"url": URL}, "missing saved_at"),
        ({"saved_at": "not-a-date"}, "unparseable saved_at"),
        ({"saved_at": "2026-07-02T18:00:00"}, "timezone-aware"),
    ],
)
def test_invalid_corpus_metadata_fails_listing_only(
    tmp_path: Path, meta: dict[str, Any] | None, match: str
) -> None:
    cleaned = clean_html((PAGES / "e2e_listing.html").read_text()).text
    corpus = tmp_path / "corpus"
    bad_slug = "example.test--bad"
    if meta is None:
        page = corpus / bad_slug
        page.mkdir(parents=True)
        (page / "cleaned.txt").write_text(cleaned)
    else:
        _write_page(corpus, bad_slug, cleaned=cleaned, meta=meta)
    _write_page(corpus, SLUG, cleaned=cleaned, saved_at=CORPUS_SAVED_AT)

    report = run([truth_label(slug=bad_slug), truth_label()], corpus, perfect_ctx())
    bad, good = report.listings
    assert bad.error is not None
    assert "invalid corpus metadata" in bad.error
    assert match in bad.error
    assert bad.as_of_date is None
    assert good.error is None
    assert good.as_of_date == CORPUS_AS_OF
    assert report.summary["failed"] == 1


def test_corpus_as_of_date_accepts_offset_timestamps(tmp_path: Path) -> None:
    page = _write_page(
        tmp_path / "corpus",
        "x",
        cleaned="hi",
        saved_at="2026-07-02T20:00:00-04:00",  # → 2026-07-03 UTC
    )
    assert _corpus_as_of_date(page) == date(2026, 7, 3)


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
