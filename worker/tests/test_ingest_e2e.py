"""P0-10 gate: the full spine end-to-end — real fetch ladder (fake transport),
real cleaner + classifier, fake LLM through the real schemas, real VERIFY and
the real engine. Prints nothing; asserts the breakdown the CLI would print."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from uuid import uuid4

from conftest import PAGES, FakeFetcher, FakeLLM, maple_extraction
from manzil_shared.models import JobState, JobType
from manzil_worker.fetching.registry import InMemoryRegistry
from manzil_worker.persistence import FilePersistence
from manzil_worker.phase0_rubric import PHASE0_RUBRIC_VERSION, phase0_rubric
from manzil_worker.runner import run_job
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import RunState

VALIDATE_YES = {
    "is_listing": True,
    "property_name": "Maple Court Apartments",
    "reason": "single property advertised with plans and rent",
}


def make_ctx(body: str, llm: FakeLLM, runs_dir: Path) -> StageCtx:
    return StageCtx(
        fetchers={1: FakeFetcher(1, body)},  # type: ignore[dict-item]
        registry=InMemoryRegistry(),
        call_structured=llm,
        rubric=phase0_rubric(),
        rubric_version=PHASE0_RUBRIC_VERSION,
        persistence=FilePersistence(runs_dir),
        today=lambda: date(2026, 7, 6),
    )


def make_state(url: str = "https://maplecourt.test/floorplans") -> RunState:
    return RunState(job_id=uuid4(), job_type=JobType.INGEST, url=url)


def test_ingest_end_to_end_prints_a_clean_breakdown(tmp_path: Path) -> None:
    body = (PAGES / "e2e_listing.html").read_text()
    llm = FakeLLM(
        {
            "validate": VALIDATE_YES,
            "extract": maple_extraction(),
            "verify": {"contradictions": []},
        }
    )
    persistence_dir = tmp_path / "runs"
    state = asyncio.run(run_job(make_state(), make_ctx(body, llm, persistence_dir)))

    assert state.status is JobState.DONE
    assert state.error is None
    assert [stage for stage, _ in llm.calls] == ["validate", "extract", "verify"]
    assert state.verify_flags == []  # every maple_extraction quote is really on the page

    (plan_score,) = state.scores
    assert plan_score.plan_name == "The Maple"
    breakdown = plan_score.breakdown
    assert breakdown["gates"] == []
    assert breakdown["total"] == 13.5
    assert state.display_score_index == 0

    # Persist-before-advance left a resumable run file behind.
    loaded = FilePersistence(persistence_dir).load(state.job_id)
    assert loaded.status is JobState.DONE
    assert loaded.cursor == 6  # validate_url, fetch, validate, extract, verify, score
    assert loaded.scores[0].breakdown == breakdown


def test_ingest_of_a_non_listing_page_fails_at_validate(tmp_path: Path) -> None:
    body = (PAGES / "not_listing_article.html").read_text()
    llm = FakeLLM({})  # heuristics must reject before any LLM call
    state = asyncio.run(
        run_job(make_state("https://blog.test/history"), make_ctx(body, llm, tmp_path))
    )

    assert state.status is JobState.FAILED
    assert state.error is not None and state.error.startswith("validate: not a listing")
    assert llm.calls == []
    assert state.scores == []


def test_ingest_of_a_bad_url_fails_before_any_fetch(tmp_path: Path) -> None:
    body = (PAGES / "e2e_listing.html").read_text()
    llm = FakeLLM({})
    state = asyncio.run(
        run_job(make_state("https://localhost/listings/4"), make_ctx(body, llm, tmp_path))
    )

    assert state.status is JobState.FAILED
    assert state.error is not None and state.error.startswith("validate_url: invalid url")
    assert state.sources == []  # the fetcher was never reached
    assert llm.calls == []


def test_ingest_of_a_blocked_page_fails_at_fetch(tmp_path: Path) -> None:
    body = (PAGES / "blocked_cloudflare.html").read_text()
    llm = FakeLLM({})
    state = asyncio.run(
        run_job(make_state("https://hostile.test/apt"), make_ctx(body, llm, tmp_path))
    )

    assert state.status is JobState.FAILED
    assert state.error is not None and "unfetchable: blocked" in state.error
    assert llm.calls == []
