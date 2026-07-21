"""Eval harness L0 (P0-12, DESIGN §19, FR11): workflow mode vs bench labels.

Per bench listing: load the saved corpus page (no refetch — the bench grades
extraction, not networking), run EXTRACT → VERIFY through the real stages,
and grade against the hand label. Emits a JSON report plus a printable
summary. Trace identity per IMPLEMENTATION §6: job_type "bench", session =
job_id, `listing_slug` metadata on every span; the report carries each
listing's job_id so spend/latency can be audited in Langfuse (replay runs are
untraced by design and carry tally figures only — same price table either
way, `llm/config.py`).

Phrase-only `available_now` normalizes against the corpus page's
`meta.json.saved_at` (UTC date), not the wall-clock bench run day — DESIGN
§20 2026-07-16 follow-up. Live ingest still uses wall-clock `StageCtx.today`.

Model choice rides the normal pins; a P0-13 sweep is three runs with
`MANZIL_MODEL_EXTRACT` / `MANZIL_MODEL_VERIFY` overrides and `bench-compare`
over the reports.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import structlog
from manzil_shared.errors import CheckpointRaised, ManzilError
from manzil_shared.models import Confidence, FetchOutcome, JobType, RubricCriterion
from pydantic import BaseModel, Field

from manzil_worker.evals.labels import BenchLabel, SkippedLabel
from manzil_worker.llm.client import RunContext, cost_tally, llm_mode, run_context
from manzil_worker.llm.config import model_for_stage
from manzil_worker.llm.prompt_loader import load_prompt
from manzil_worker.llm.recording import ReplayMissError
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.extract import AVAILABLE_NOW_SENTINEL, extract_stage
from manzil_worker.stages.verify import verify_stage
from manzil_worker.state import FloorPlanIn, RunState, SourceState

log = structlog.get_logger()

BENCH_STAGES = ("extract", "verify")


class CriterionResult(BaseModel):
    kind: Literal["value", "unknown"]
    expected: Any = None  # None when kind == "unknown"
    got: Any = None
    got_confidence: Confidence | None = None
    ok: bool


class PlanGrade(BaseModel):
    """Floor plans matched by normalized plan_name; only fields the label
    actually states are compared (a label may omit e.g. sqft)."""

    expected: int
    matched: int
    missing: list[str] = Field(default_factory=list)
    extra: list[str] = Field(default_factory=list)
    field_checks: int = 0
    field_ok: int = 0


class ListingResult(BaseModel):
    slug: str
    job_id: str  # Langfuse session id for live/record runs
    error: str | None = None
    # UTC date of corpus meta.saved_at — the clock EXTRACT/VERIFY/grading used.
    as_of_date: str | None = None
    criteria: dict[str, CriterionResult] = Field(default_factory=dict)
    gate_keys: list[str] = Field(default_factory=list)
    criterion_accuracy: float | None = None
    gate_accuracy: float | None = None
    evidence_flags: int = 0
    verify_flags: int = 0
    plans: PlanGrade | None = None
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0


class BenchReport(BaseModel):
    run_at: str
    llm_mode: str
    models: dict[str, str]
    prompt_versions: dict[str, int]
    listings: list[ListingResult]
    skipped: list[SkippedLabel] = Field(default_factory=list)
    summary: dict[str, Any]


def gate_keys_from(rubric: list[RubricCriterion]) -> list[str]:
    """Extractable keys the rubric gates on. `all_in_monthly` is composed from
    floor-plan rents (§9.5), so its gate correctness is graded through the
    plan rent fields, not here."""
    return [c.catalog_key for c in rubric if c.non_negotiable is not None and c.catalog_key]


def _corpus_as_of_date(page_dir: Path) -> date:
    """UTC calendar date of the corpus page's freeze time (`meta.json.saved_at`).

    Fail closed: missing meta, missing/unparseable `saved_at`, or a timezone-
    naive timestamp are listing errors — never fall back to wall clock.
    """
    meta_path = page_dir / "meta.json"
    if not meta_path.exists():
        raise ValueError(f"invalid corpus metadata at {meta_path}: missing meta.json")
    try:
        meta = json.loads(meta_path.read_text())
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid corpus metadata at {meta_path}: {error}") from error
    if not isinstance(meta, dict):
        raise ValueError(f"invalid corpus metadata at {meta_path}: expected a JSON object")
    raw = meta.get("saved_at")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"invalid corpus metadata at {meta_path}: missing saved_at")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise ValueError(
            f"invalid corpus metadata at {meta_path}: unparseable saved_at {raw!r}"
        ) from error
    if parsed.utcoffset() is None:
        raise ValueError(f"invalid corpus metadata at {meta_path}: saved_at must be timezone-aware")
    return parsed.astimezone(UTC).date()


def _values_equal(expected: Any, got: Any, *, today: date | None = None) -> bool:
    # Labels use available_now for phrase-only immediate availability; EXTRACT
    # rewrites the sentinel to the corpus as-of date before grading sees it.
    if expected == AVAILABLE_NOW_SENTINEL and today is not None:
        return got == today.isoformat()
    if isinstance(expected, bool) or isinstance(got, bool):
        return expected == got
    if isinstance(expected, int | float) and isinstance(got, int | float):
        return abs(float(expected) - float(got)) < 1e-6
    return expected == got


def _norm_name(name: str | None) -> str:
    return (name or "").strip().casefold()


# Plan fields compared when the label states them (availability compared as
# the ISO string, or available_now → corpus as-of date; evidence_quote is
# provenance, never graded).
_PLAN_FIELDS = (
    "beds",
    "baths",
    "sqft_min",
    "sqft_max",
    "rent_min",
    "rent_max",
    "deposit",
    "availability_date",
)


def _grade_plans(expected: list[FloorPlanIn], got: list[FloorPlanIn], *, today: date) -> PlanGrade:
    got_by_name = {_norm_name(p.plan_name): p for p in got}
    grade = PlanGrade(expected=len(expected), matched=0)
    for want in expected:
        have = got_by_name.pop(_norm_name(want.plan_name), None)
        if have is None:
            grade.missing.append(want.plan_name or "<unnamed>")
            continue
        grade.matched += 1
        for field in _PLAN_FIELDS:
            want_value = getattr(want, field)
            if want_value is None:
                continue
            grade.field_checks += 1
            if _values_equal(want_value, getattr(have, field), today=today):
                grade.field_ok += 1
    grade.extra = [p.plan_name or "<unnamed>" for p in got_by_name.values()]
    return grade


def _grade(
    state: RunState, label: BenchLabel, gate_keys: list[str], *, today: date
) -> ListingResult:
    result = ListingResult(
        slug=label.slug,
        job_id=str(state.job_id),
        gate_keys=gate_keys,
        as_of_date=today.isoformat(),
    )
    for key, expected in label.criteria.items():
        extraction = state.extractions.get(key, [None])[0]
        got = extraction.value if extraction else None
        result.criteria[key] = CriterionResult(
            kind="value",
            expected=expected,
            got=got,
            got_confidence=extraction.confidence if extraction else None,
            ok=got is not None and _values_equal(expected, got, today=today),
        )
    for key in label.unknown:
        extraction = state.extractions.get(key, [None])[0]
        got = extraction.value if extraction else None
        result.criteria[key] = CriterionResult(
            kind="unknown",
            got=got,
            got_confidence=extraction.confidence if extraction else None,
            ok=got is None,  # truth: the page doesn't say — any value is invented
        )

    graded = result.criteria
    if graded:
        result.criterion_accuracy = sum(r.ok for r in graded.values()) / len(graded)
    gated = {k: r for k, r in graded.items() if k in gate_keys}
    if gated:
        result.gate_accuracy = sum(r.ok for r in gated.values()) / len(gated)

    result.verify_flags = len(state.verify_flags)
    result.evidence_flags = sum(1 for f in state.verify_flags if f.check == "evidence")
    if label.floor_plans is not None:
        result.plans = _grade_plans(label.floor_plans, state.floor_plans, today=today)
    return result


async def _run_listing(
    label: BenchLabel,
    cleaned_text: str,
    ctx: StageCtx,
    gate_keys: list[str],
    *,
    as_of: date,
) -> ListingResult:
    # Freeze EXTRACT/VERIFY to the corpus snapshot date without mutating the
    # shared StageCtx the caller passed into run_bench.
    listing_ctx = dataclasses.replace(ctx, today=lambda: as_of)
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url=label.url)
    state.sources = [
        SourceState(
            url=label.url,
            tier_used=1,
            outcome=FetchOutcome.SUCCESS,
            cleaned_text=cleaned_text,
        )
    ]
    trace = RunContext(job_type="bench", job_id=str(state.job_id), listing_slug=label.slug)
    started = time.perf_counter()
    with run_context(trace), cost_tally() as tally:
        state = await extract_stage(state, listing_ctx)
        # The bench has no human to answer a gate-relevant confirm_value
        # checkpoint (§10.10). At raise time EXTRACT's values and every VERIFY
        # flag are already on `state` (all checks run before the raise, single
        # pass — no double-counting), so grading it as-is is exactly "accept at
        # low confidence": the extracted value is graded against the label and
        # the flag still surfaces via verify_flags/evidence_flags. Dropping the
        # listing instead would bias the bench toward whichever model
        # checkpoints least and grade each model over a different subset.
        # Genuine stage errors (schema validation, replay miss) still propagate
        # and fail the listing. (P0-12 gap surfaced by the gate-heavy 10-label
        # set; DESIGN §20.)
        with contextlib.suppress(CheckpointRaised):
            state = await verify_stage(state, listing_ctx)
    result = _grade(state, label, gate_keys, today=as_of)
    result.latency_s = round(time.perf_counter() - started, 3)
    result.calls = tally.calls
    result.input_tokens = tally.input_tokens + tally.cache_read_tokens + tally.cache_write_tokens
    result.output_tokens = tally.output_tokens
    result.cost_usd = tally.cost_usd
    return result


def _summarize(listings: list[ListingResult], skipped: list[SkippedLabel]) -> dict[str, Any]:
    graded = [r for r in listings if r.error is None]
    checks = [c for r in graded for c in r.criteria.values()]
    gate_checks = [c for r in graded for k, c in r.criteria.items() if k in r.gate_keys]
    unknown_checks = [c for c in checks if c.kind == "unknown"]
    values_extracted = sum(1 for r in graded for c in r.criteria.values() if c.got is not None)
    plan_checks = sum(r.plans.field_checks for r in graded if r.plans)
    plan_ok = sum(r.plans.field_ok for r in graded if r.plans)

    def rate(ok: int, total: int) -> float | None:
        return round(ok / total, 4) if total else None

    return {
        "listings": len(listings),
        "failed": len(listings) - len(graded),
        "skipped": len(skipped),
        "criterion_accuracy": rate(sum(c.ok for c in checks), len(checks)),
        "gate_accuracy": rate(sum(c.ok for c in gate_checks), len(gate_checks)),
        "unknown_accuracy": rate(sum(c.ok for c in unknown_checks), len(unknown_checks)),
        "evidence_flag_rate": rate(sum(r.evidence_flags for r in graded), values_extracted),
        "plan_field_accuracy": rate(plan_ok, plan_checks),
        "total_cost_usd": round(sum(r.cost_usd for r in graded), 6),
        "total_input_tokens": sum(r.input_tokens for r in graded),
        "total_output_tokens": sum(r.output_tokens for r in graded),
        "mean_latency_s": (
            round(sum(r.latency_s for r in graded) / len(graded), 3) if graded else None
        ),
    }


async def run_bench(
    labels: list[BenchLabel],
    *,
    corpus_dir: Path,
    ctx: StageCtx,
    gate_keys: list[str],
    skipped: list[SkippedLabel] | None = None,
) -> BenchReport:
    """One harness run. Per-listing failures (replay miss, missing corpus
    page, stage error) are recorded on the listing and never abort the run —
    a partial report beats no report. A gate-relevant VERIFY confirm_value
    checkpoint is NOT a failure: with no human to answer it the listing is
    graded accept-at-low-confidence (see `_run_listing`), so every model is
    graded over the same listings. `skipped` carries unfinished-skeleton
    labels the loader partitioned out: reported and counted, never graded."""
    skipped = skipped or []
    for s in skipped:
        log.warning("bench_label_skipped", slug=s.slug, reason=s.reason)
    listings: list[ListingResult] = []
    for label in labels:
        page_dir = corpus_dir / label.slug
        cleaned_path = page_dir / "cleaned.txt"
        if not cleaned_path.exists():
            listings.append(
                ListingResult(
                    slug=label.slug,
                    job_id="",
                    error=f"no corpus page at {page_dir} — run `manzil save-page`",
                )
            )
            continue
        try:
            as_of = _corpus_as_of_date(page_dir)
        except ValueError as error:
            listings.append(ListingResult(slug=label.slug, job_id="", error=str(error)))
            log.info("bench_listing", slug=label.slug, error=listings[-1].error)
            continue
        try:
            listings.append(
                await _run_listing(label, cleaned_path.read_text(), ctx, gate_keys, as_of=as_of)
            )
        except ReplayMissError as error:
            listings.append(
                ListingResult(
                    slug=label.slug,
                    job_id="",
                    error="replay miss — record this listing first "
                    f"(MANZIL_LLM_MODE=record): {error}",
                )
            )
        except ManzilError as error:
            listings.append(ListingResult(slug=label.slug, job_id="", error=str(error)))
        log.info("bench_listing", slug=label.slug, error=listings[-1].error)

    return BenchReport(
        run_at=datetime.now(UTC).isoformat(),
        llm_mode=llm_mode(),
        models={stage: model_for_stage(stage) for stage in BENCH_STAGES},
        prompt_versions={stage: load_prompt(stage).version for stage in BENCH_STAGES},
        listings=listings,
        skipped=skipped,
        summary=_summarize(listings, skipped),
    )


def report_text(report: BenchReport) -> str:
    """Human-readable summary (also what bench-run prints)."""
    lines = [
        f"bench run {report.run_at} — mode {report.llm_mode}, "
        + ", ".join(f"{s}={m}" for s, m in report.models.items()),
        "",
        "| slug | crit acc | gate acc | ev flags | cost $ | latency s |",
        "|---|---|---|---|---|---|",
    ]

    for r in report.listings:
        if r.error:
            lines.append(f"| {r.slug} | FAILED: {r.error} | | | | |")
            continue

        def fmt(value: float | None) -> str:
            return "—" if value is None else f"{value:.2f}"

        lines.append(
            f"| {r.slug} | {fmt(r.criterion_accuracy)} | {fmt(r.gate_accuracy)} "
            f"| {r.evidence_flags} | {r.cost_usd:.4f} | {r.latency_s:.1f} |"
        )
    for s in report.skipped:
        lines.append(f"| {s.slug} | SKIPPED: {s.reason} | | | | |")
    lines.append("")
    lines.append("summary: " + ", ".join(f"{k}={v}" for k, v in report.summary.items()))
    return "\n".join(lines)
