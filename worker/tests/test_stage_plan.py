"""P3-2: PLAN stage — golden manifests (§10.4 pinned shape), the hash-fresh skip
decision + FETCH honoring it, and manifest-driven resume (§2.1).

Golden manifests get exact-JSON treatment like score breakdowns (§15): the
manifest is a pinned contract, so its shape is asserted verbatim.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from manzil_shared.models import JobType
from manzil_worker.runner import INGEST_STAGE_NAMES, STAGE_REGISTRY, run_job
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.fetch import fetch_stage
from manzil_worker.stages.plan import plan_stage
from manzil_worker.state import PlanManifest, RunState, SourceFreshness

URL = "https://maplecourt.test/floorplans"
LIVE_STAGES = [
    "PLAN",
    "VALIDATE_URL",
    "FETCH",
    "VALIDATE",
    "EXTRACT",
    "DEDUPE",
    "VERIFY",
    "SCORE",
]


def _state(source_policy: str = "tiers_1_2_3") -> RunState:
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url=URL, source_policy=source_policy)
    state.property_id = uuid4()
    return state


def _fresh_lookup(row: SourceFreshness | None):  # type: ignore[no-untyped-def]
    async def lookup(property_id, url):  # type: ignore[no-untyped-def]
        return row

    return lookup


# ── golden manifests ─────────────────────────────────────────────────────────


def test_manifest_new_submission() -> None:
    state = asyncio.run(plan_stage(_state(), StageCtx()))

    assert state.plan is not None
    assert state.plan.model_dump(mode="json", exclude_none=True) == {
        "job_type": "ingest",
        "trigger": "user:submit",
        "source_policy": "tiers_1_2_3",
        "sources": [{"url": URL, "action": "fetch", "tier": 1}],
        "stages": LIVE_STAGES,
        "skipped": {},
        "est_cost_usd": 0.035,
    }
    # Nothing pre-loaded — FETCH will fetch.
    assert state.sources == []


def test_manifest_same_property_reingest_skips_on_fresh_hash() -> None:
    fresh = SourceFreshness(
        cleaned_text_hash="abc123",
        cleaned_text="cached page text",
        last_success_at=datetime.now(UTC) - timedelta(hours=1),
    )
    ctx = StageCtx(fresh_source_lookup=_fresh_lookup(fresh))
    state = asyncio.run(plan_stage(_state(), ctx))

    assert state.plan is not None
    assert state.plan.model_dump(mode="json", exclude_none=True) == {
        "job_type": "ingest",
        "trigger": "user:submit",
        "source_policy": "tiers_1_2_3",
        "sources": [{"url": URL, "action": "skip", "why": "hash_fresh"}],
        "stages": LIVE_STAGES,
        "skipped": {},
        "est_cost_usd": 0.035,
    }
    # PLAN handed FETCH the persisted cleaned text so it skips the network.
    assert len(state.sources) == 1
    assert state.sources[0].cleaned_text == "cached page text"
    assert state.sources[0].cleaned_hash == "abc123"


def test_manifest_stale_hash_falls_back_to_fetch() -> None:
    stale = SourceFreshness(
        cleaned_text_hash="abc123",
        cleaned_text="old text",
        last_success_at=datetime.now(UTC) - timedelta(hours=48),  # past PLAN_FRESH_TTL_HOURS
    )
    ctx = StageCtx(fresh_source_lookup=_fresh_lookup(stale))
    state = asyncio.run(plan_stage(_state(), ctx))

    assert state.plan is not None
    assert state.plan.sources[0].action == "fetch"
    assert state.sources == []


def test_manifest_trust_link_policy_carried_through() -> None:
    state = asyncio.run(plan_stage(_state(source_policy="trust_link"), StageCtx()))

    assert state.plan is not None
    # Policy recorded; no DISCOVER exists yet, so stages are unchanged (§10.4/P3-5).
    assert state.plan.source_policy == "trust_link"
    assert state.plan.stages == LIVE_STAGES


def test_manifest_retry_trigger() -> None:
    ctx = StageCtx(plan_trigger="user:retry")
    state = asyncio.run(plan_stage(_state(), ctx))

    assert state.plan is not None
    assert state.plan.trigger == "user:retry"


# ── FETCH honors the skip ────────────────────────────────────────────────────


def test_fetch_uses_persisted_text_when_plan_skips() -> None:
    # PLAN decided skip and pre-loaded the cleaned text; FETCH must not touch the
    # ladder (ctx has no registry — a fetch attempt would raise StageFatal).
    fresh = SourceFreshness(
        cleaned_text_hash="deadbeef",
        cleaned_text="persisted body",
        last_success_at=datetime.now(UTC) - timedelta(minutes=30),
    )
    state = asyncio.run(plan_stage(_state(), StageCtx(fresh_source_lookup=_fresh_lookup(fresh))))
    out = asyncio.run(fetch_stage(state, StageCtx()))  # registry=None on purpose

    assert out.sources[0].cleaned_text == "persisted body"


# ── manifest-driven resume (§2.1) ────────────────────────────────────────────


def _recording_stages(log: list[str]):  # type: ignore[no-untyped-def]
    def make(name: str):  # type: ignore[no-untyped-def]
        async def stage(state: RunState, ctx: StageCtx) -> RunState:
            log.append(name)
            return state

        return stage

    return {name: make(name) for name in ("x1", "x2", "x3", "x4")}


def _plan(stages: list[str]) -> PlanManifest:
    return PlanManifest(
        job_type="ingest",
        trigger="user:submit",
        source_policy="tiers_1_2_3",
        sources=[],
        stages=stages,
        skipped={},
        est_cost_usd=0.0,
    )


def test_manifest_walk_runs_all_stages_from_start(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    for name, stage in _recording_stages(log).items():
        monkeypatch.setitem(STAGE_REGISTRY, name, stage)
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url=URL)
    state.plan = _plan(["x1", "x2", "x3"])

    asyncio.run(run_job(state, StageCtx()))
    assert log == ["x1", "x2", "x3"]


def test_manifest_resume_skips_completed_stages_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    for name, stage in _recording_stages(log).items():
        monkeypatch.setitem(STAGE_REGISTRY, name, stage)
    # A parked job carries a two-stage manifest and resumes at cursor 1. Even
    # though the registry ALSO knows x3/x4 (a later-added stage), the job walks
    # ITS OWN manifest — so nothing new is injected and no stage re-runs.
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url=URL, plan=_plan(["x1", "x2"]))
    state.cursor = 1

    asyncio.run(run_job(state, StageCtx()))
    assert log == ["x2"]  # x1 already done, x3/x4 not in this job's manifest


def test_legacy_fallback_when_plan_is_none() -> None:
    # A pre-P3 snapshot (plan=None) resumes through the caller's fixed list.
    log: list[str] = []

    async def a(state: RunState, ctx: StageCtx) -> RunState:
        log.append("a")
        return state

    async def b(state: RunState, ctx: StageCtx) -> RunState:
        log.append("b")
        return state

    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url=URL)
    state.cursor = 1
    asyncio.run(run_job(state, StageCtx(), [("a", a), ("b", b)]))
    assert log == ["b"]  # legacy index cursor, plan never consulted


def test_est_cost_matches_live_stage_estimates() -> None:
    # 0.005 (VALIDATE) + 0.02 (EXTRACT) + 0.01 (VERIFY); the rest are 0.
    state = asyncio.run(plan_stage(_state(), StageCtx()))
    assert state.plan is not None
    assert state.plan.est_cost_usd == 0.035
    assert state.plan.stages == list(INGEST_STAGE_NAMES)


def test_ingest_stages_walk_runs_plan_first_then_the_spine(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # The real INGEST_STAGES walk (PLAN first) must produce a scored run exactly
    # like the legacy PHASE0 walk — PLAN inserts a manifest without disturbing the
    # spine, and the manifest ends up with every live stage.
    from datetime import date
    from pathlib import Path

    from manzil_shared.models import JobState
    from manzil_worker.fetching.registry import InMemoryRegistry
    from manzil_worker.persistence import FilePersistence
    from manzil_worker.phase0_rubric import PHASE0_RUBRIC_VERSION, phase0_rubric
    from manzil_worker.runner import INGEST_STAGES
    from manzil_worker.state import GeocodeIn
    from worker_helpers import PAGES, FakeFetcher, FakeLLM, maple_extraction

    async def _fake_geocode(address: str) -> GeocodeIn:
        # DEDUPE now runs in the INGEST walk; inject the geocode seam so CI never
        # touches Google. No candidates (default seam) → decision `no_candidates`,
        # so the run keeps its own property and scores exactly as the legacy walk.
        return GeocodeIn(place_id="fake", lat=42.3, lng=-83.0, formatted_address=address)

    body = (Path(PAGES) / "e2e_listing.html").read_text()
    llm = FakeLLM(
        {
            "validate": {
                "is_listing": True,
                "property_name": "Maple Court Apartments",
                "reason": "single property advertised with plans and rent",
            },
            "extract": maple_extraction(),
            "verify": {"contradictions": []},
        }
    )
    ctx = StageCtx(
        fetchers={1: FakeFetcher(1, body)},  # type: ignore[dict-item]
        registry=InMemoryRegistry(),
        call_structured=llm,
        rubric=phase0_rubric(),
        rubric_version=PHASE0_RUBRIC_VERSION,
        persistence=FilePersistence(tmp_path / "runs"),
        today=lambda: date(2026, 7, 6),
        geocode_address=_fake_geocode,
    )
    state = RunState(
        job_id=uuid4(), job_type=JobType.INGEST, url="https://maplecourt.test/floorplans"
    )

    out = asyncio.run(run_job(state, ctx, INGEST_STAGES))

    assert out.status is JobState.DONE
    assert out.plan is not None and out.plan.stages == LIVE_STAGES
    assert out.plan.sources[0].action == "fetch"  # no DB → fresh lookup None
    assert [stage for stage, _ in llm.calls] == ["validate", "extract", "verify"]
    (plan_score,) = out.scores
    assert plan_score.breakdown["total"] == 13.5  # identical to the PHASE0 e2e
