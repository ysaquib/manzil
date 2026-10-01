"""Billed-spend accounting and the Langfuse trace check (DESIGN §20 v3.111).

The seam tallies OpenRouter's reported `usage.cost` for every call — so Job
cost, stage cost and the bench all carry billed spend — falling back to the
`MODEL_PRICES` estimate only when a response (or an older recording) has none.
Recordings keep the billed figure, so replay reproduces it. Langfuse is no
longer a cost source; `llm.traces.session_generations` checks that every call
reached it.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import test_bench_harness as bench
from manzil_worker.costs import CallUsage, CostTally, active_tally
from manzil_worker.evals.compare import compare_table
from manzil_worker.evals.harness import run_bench
from manzil_worker.llm import client as client_mod
from manzil_worker.llm.client import (
    ProviderResponse,
    _actual_cost_usd,
    _agent_usage,
    _AgentTurnRaw,
    _cost_metadata,
    call_structured,
    cost_tally,
)
from manzil_worker.llm.config import cost_usd, model_for_stage
from manzil_worker.llm.smoke import SmokeResult
from manzil_worker.llm.traces import session_generations
from manzil_worker.stages.base import StageCtx

SINCE = datetime(2026, 9, 24, tzinfo=UTC)


# ── seam: billed first, list price as the fallback ───────────────────────────


def test_actual_cost_prefers_openrouter_reported_cost() -> None:
    assert _actual_cost_usd(0.004, 0.0031) == 0.0031
    assert _actual_cost_usd(0.004, 0.0) == 0.0  # a reported zero is still a report
    assert _actual_cost_usd(0.004, None) == 0.004


def test_cost_metadata_names_its_source_and_keeps_both_figures() -> None:
    reported = _cost_metadata({"mode": "workflow"}, 0.004, 0.0031)
    assert reported == {
        "mode": "workflow",
        "list_price_cost_usd": 0.004,
        "cost_source": "openrouter",
        "openrouter_cost_usd": 0.0031,
    }
    estimated = _cost_metadata({}, 0.004, None)
    assert estimated == {"list_price_cost_usd": 0.004, "cost_source": "list_price"}


def _turn(**overrides: Any) -> _AgentTurnRaw:
    base: dict[str, Any] = {
        "tool_calls": [],
        "text": "done",
        "stop_reason": "stop",
        "input_tokens": 0,
        "output_tokens": 0,
        "web_search_requests": 2,
    }
    return _AgentTurnRaw(**(base | overrides))


def test_agent_turn_is_billed_when_reported_and_list_priced_otherwise() -> None:
    estimated = _agent_usage("openai/gpt-5.6-luna", _turn())
    assert (estimated.cost_usd, estimated.list_price, estimated.billed) == (0.02, 0.02, False)

    billed = _agent_usage("openai/gpt-5.6-luna", _turn(reported_cost_usd=0.05))
    assert (billed.cost_usd, billed.list_price, billed.billed) == (0.05, 0.02, True)


def test_tally_keeps_billed_list_price_and_fallback_count_through_merge() -> None:
    tally = CostTally()
    tally.add(CallUsage("m", 1, 1, 0, 0, 0.003, list_price_cost_usd=0.004, billed=True))
    tally.add(CallUsage("m", 1, 1, 0, 0, 0.002))  # unbilled: list price is the cost
    retry = CostTally()
    retry.add(CallUsage("m", 1, 1, 0, 0, 0.001, list_price_cost_usd=0.001, billed=True))
    tally.merge(retry)

    assert tally.cost_usd == pytest.approx(0.006)
    assert tally.list_price_cost_usd == pytest.approx(0.007)
    assert tally.list_price_fallback_calls == 1
    assert tally.calls == 3


def _stub_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reported_cost_usd: float | None
) -> None:
    monkeypatch.setenv("MANZIL_RECORDED_DIR", str(tmp_path))
    stub = ProviderResponse(
        output={"echo": "billed", "model_family": "stub"},
        input_tokens=100,
        output_tokens=20,
        reported_cost_usd=reported_cost_usd,
    )

    async def fake_traced_live_call(plan: object, schema: object) -> ProviderResponse:
        return stub

    monkeypatch.setattr(client_mod, "_traced_live_call", fake_traced_live_call)
    monkeypatch.setenv("MANZIL_LLM_MODE", "record")
    asyncio.run(call_structured("smoke", SmokeResult, "Token: billed"))
    monkeypatch.setattr(client_mod, "_traced_live_call", None)
    monkeypatch.setenv("MANZIL_LLM_MODE", "replay")


def _list_price() -> float:
    return cost_usd(model_for_stage("smoke"), input_tokens=100, output_tokens=20)


def test_recorded_billed_cost_is_replayed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_record(monkeypatch, tmp_path, reported_cost_usd=0.0042)
    [fixture] = tmp_path.glob("smoke--*.json")
    assert json.loads(fixture.read_text())["reported_cost_usd"] == 0.0042

    with cost_tally() as tally:
        asyncio.run(call_structured("smoke", SmokeResult, "Token: billed"))

    assert tally.cost_usd == 0.0042
    assert tally.list_price_cost_usd == pytest.approx(_list_price())
    assert tally.list_price_fallback_calls == 0


def test_recording_without_billed_cost_falls_back_to_list_price(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_record(monkeypatch, tmp_path, reported_cost_usd=None)

    with cost_tally() as tally:
        asyncio.run(call_structured("smoke", SmokeResult, "Token: billed"))

    assert tally.cost_usd == pytest.approx(_list_price())
    assert tally.list_price_cost_usd == pytest.approx(_list_price())
    assert tally.list_price_fallback_calls == 1


# ── trace check: counting, polling, pagination ───────────────────────────────


@dataclass
class _Meta:
    cursor: str | None


@dataclass
class _Page:
    data: list[object]
    meta: _Meta


@dataclass
class _FakeObservations:
    """Serves one scripted snapshot per read; a snapshot lists page sizes."""

    snapshots: list[list[int]]
    calls: list[dict[str, Any]] = field(default_factory=list)
    _read: int = 0

    async def get_many(self, **kwargs: Any) -> _Page:
        self.calls.append(kwargs)
        pages = self.snapshots[min(self._read, len(self.snapshots) - 1)]
        index = int(kwargs["cursor"] or 0)
        if index == len(pages) - 1:
            self._read += 1  # this read is complete
        cursor = str(index + 1) if index + 1 < len(pages) else None
        return _Page([object()] * pages[index], _Meta(cursor))


@dataclass
class _FakeApi:
    observations: _FakeObservations


def _check(api: _FakeApi, expected: int, *, timeout_s: float = 5.0) -> int | None:
    return asyncio.run(
        session_generations(
            "job-1",
            expected_generations=expected,
            since=SINCE,
            api=api,
            timeout_s=timeout_s,
            poll_s=0,
        )
    )


def test_trace_check_counts_every_page_and_filters_to_the_session() -> None:
    api = _FakeApi(_FakeObservations([[2, 1]]))

    assert _check(api, 3) == 3
    filters = json.loads(api.observations.calls[0]["filter"])
    assert {"type": "string", "column": "sessionId", "operator": "=", "value": "job-1"} in filters
    assert any(f["column"] == "type" and f["value"] == "GENERATION" for f in filters)
    assert any(f["column"] == "startTime" and f["value"] == SINCE.isoformat() for f in filters)


def test_trace_check_polls_until_ingestion_catches_up() -> None:
    api = _FakeApi(_FakeObservations([[1], [2]]))

    assert _check(api, 2) == 2
    assert len(api.observations.calls) == 2


def test_trace_check_reports_missing_generations_as_none() -> None:
    assert _check(_FakeApi(_FakeObservations([[1]])), 2, timeout_s=0) is None


def test_trace_check_with_no_calls_needs_no_read() -> None:
    api = _FakeApi(_FakeObservations([[0]]))

    assert _check(api, 0) == 0
    assert api.observations.calls == []


# ── harness: billed cost of record, trace completeness beside it ─────────────


class _TallyingLLM:
    """Wraps the bench FakeLLM so each call bills the ambient tally, the way
    the real seam does: $0.0008 billed against a $0.001 list price."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def __call__(self, stage: str, schema: type[Any], content: str) -> Any:
        tally = active_tally()
        assert tally is not None
        tally.add(
            CallUsage(
                "google/gemini-3-flash-preview",
                100,
                10,
                0,
                0,
                0.0008,
                list_price_cost_usd=0.001,
                billed=True,
            )
        )
        return await self._inner(stage, schema, content)


def _run(tmp_path: Path, trace_checker: Any = None) -> Any:
    ctx = bench.perfect_ctx()
    ctx = dataclasses.replace(ctx, call_structured=_TallyingLLM(ctx.call_structured))
    assert isinstance(ctx, StageCtx)
    return asyncio.run(
        run_bench(
            [bench.truth_label()],
            corpus_dir=bench.make_corpus(tmp_path),
            ctx=ctx,
            gate_keys=bench.GATE_KEYS,
            trace_checker=trace_checker,
        )
    )


def test_harness_reports_billed_cost_with_list_price_beside_it(tmp_path: Path) -> None:
    report = _run(tmp_path)

    [listing] = report.listings
    assert listing.calls > 0
    assert listing.cost_usd == pytest.approx(0.0008 * listing.calls)
    assert listing.list_price_cost_usd == pytest.approx(0.001 * listing.calls)
    assert listing.list_price_fallback_calls == 0
    assert listing.traced is None  # unchecked without a checker (replay)
    assert report.summary["untraced_listings"] is None
    table = compare_table({"run": report})
    assert "| list-price cost $ |" in table
    assert "| list-price fallback calls | 0 |" in table


def test_harness_checks_every_listing_reached_langfuse(tmp_path: Path) -> None:
    seen: list[tuple[str, int]] = []

    async def complete(session_id: str, *, expected_generations: int, since: datetime) -> Any:
        seen.append((session_id, expected_generations))
        return expected_generations

    report = _run(tmp_path, complete)

    [listing] = report.listings
    assert seen == [(listing.job_id, listing.calls)]
    assert listing.traced is True
    assert report.summary["untraced_listings"] == 0


def test_harness_flags_a_listing_whose_calls_never_reached_langfuse(tmp_path: Path) -> None:
    async def missing(session_id: str, *, expected_generations: int, since: datetime) -> Any:
        return None

    report = _run(tmp_path, missing)

    [listing] = report.listings
    assert listing.traced is False
    assert listing.cost_usd == pytest.approx(0.0008 * listing.calls)  # cost is unaffected
    assert report.summary["untraced_listings"] == 1
    assert "| untraced listings | 1 |" in compare_table({"run": report})
