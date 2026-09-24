"""Actual-cost tracing and read-back (IMPLEMENTATION §6).

The seam costs each Langfuse generation at OpenRouter's reported spend when it
has one; `llm.traces.session_cost` reads a session's total back, polling past
Langfuse's asynchronous ingestion; the bench harness makes that total its cost
of record and keeps the list-price tally beside it.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import test_bench_harness as bench
from manzil_worker.costs import CallUsage, active_tally
from manzil_worker.evals.compare import compare_table
from manzil_worker.evals.harness import run_bench
from manzil_worker.llm.client import (
    _actual_cost_usd,
    _agent_usage,
    _AgentTurnRaw,
    _cost_metadata,
)
from manzil_worker.llm.traces import SessionCost, session_cost
from manzil_worker.stages.base import StageCtx

SINCE = datetime(2026, 9, 24, tzinfo=UTC)


# ── seam: what a generation is costed at ─────────────────────────────────────


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


def test_agent_turn_cost_falls_back_to_list_price_plus_searches() -> None:
    raw = _AgentTurnRaw(
        tool_calls=[],
        text="done",
        stop_reason="stop",
        input_tokens=0,
        output_tokens=0,
        web_search_requests=2,
    )
    assert _agent_usage("openai/gpt-5.6-luna", raw).cost_usd == 0.02
    reported = _AgentTurnRaw(
        tool_calls=[],
        text="done",
        stop_reason="stop",
        input_tokens=0,
        output_tokens=0,
        reported_cost_usd=0.05,
        web_search_requests=2,
    )
    assert _agent_usage("openai/gpt-5.6-luna", reported).cost_usd == 0.05


# ── read-back: polling, pagination, partial ingestion ────────────────────────


@dataclass
class _Obs:
    total_cost: float | None


@dataclass
class _Meta:
    cursor: str | None


@dataclass
class _Page:
    data: list[_Obs]
    meta: _Meta


@dataclass
class _FakeObservations:
    """Serves one scripted snapshot per read; each snapshot is a list of pages."""

    snapshots: list[list[list[float | None]]]
    calls: list[dict[str, Any]] = field(default_factory=list)
    _read: int = 0

    async def get_many(self, **kwargs: Any) -> _Page:
        self.calls.append(kwargs)
        pages = self.snapshots[min(self._read, len(self.snapshots) - 1)]
        index = int(kwargs["cursor"] or 0)
        if index == len(pages) - 1:
            self._read += 1  # this read is complete
        cursor = str(index + 1) if index + 1 < len(pages) else None
        return _Page([_Obs(c) for c in pages[index]], _Meta(cursor))


@dataclass
class _FakeApi:
    observations: _FakeObservations


def _read(api: _FakeApi, expected: int, *, timeout_s: float = 5.0) -> SessionCost | None:
    return asyncio.run(
        session_cost(
            "job-1",
            expected_generations=expected,
            since=SINCE,
            api=api,
            timeout_s=timeout_s,
            poll_s=0,
        )
    )


def test_session_cost_sums_every_page_and_filters_to_the_session() -> None:
    api = _FakeApi(_FakeObservations([[[0.01, 0.02], [0.03]]]))

    assert _read(api, 3) == SessionCost(cost_usd=0.06, generations=3)
    first = api.observations.calls[0]
    filters = json.loads(first["filter"])
    assert {"type": "string", "column": "sessionId", "operator": "=", "value": "job-1"} in filters
    assert any(f["column"] == "type" and f["value"] == "GENERATION" for f in filters)
    assert any(f["column"] == "startTime" and f["value"] == SINCE.isoformat() for f in filters)
    assert "usage" in first["fields"]


def test_session_cost_polls_until_ingestion_catches_up() -> None:
    # First read: one generation ingested, one still uncosted. Second: both.
    api = _FakeApi(_FakeObservations([[[0.01, None]], [[0.01, 0.02]]]))

    assert _read(api, 2) == SessionCost(cost_usd=0.03, generations=2)
    assert len(api.observations.calls) == 2


def test_session_cost_returns_none_rather_than_a_partial_sum() -> None:
    api = _FakeApi(_FakeObservations([[[0.01]]]))

    assert _read(api, 2, timeout_s=0) is None


def test_session_cost_with_no_calls_needs_no_read() -> None:
    api = _FakeApi(_FakeObservations([[[]]]))

    assert _read(api, 0) == SessionCost(cost_usd=0.0, generations=0)
    assert api.observations.calls == []


# ── harness: Langfuse is the cost of record ──────────────────────────────────


class _TallyingLLM:
    """Wraps the bench FakeLLM so each call bills the ambient tally, the way
    the real seam does."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def __call__(self, stage: str, schema: type[Any], content: str) -> Any:
        tally = active_tally()
        assert tally is not None
        tally.add(CallUsage("google/gemini-3-flash-preview", 100, 10, 0, 0, 0.001))
        return await self._inner(stage, schema, content)


def _ctx() -> StageCtx:
    ctx = bench.perfect_ctx()
    return dataclasses.replace(ctx, call_structured=_TallyingLLM(ctx.call_structured))


def _run(tmp_path: Path, cost_reader: Any = None) -> Any:
    return asyncio.run(
        run_bench(
            [bench.truth_label()],
            corpus_dir=bench.make_corpus(tmp_path),
            ctx=_ctx(),
            gate_keys=bench.GATE_KEYS,
            cost_reader=cost_reader,
        )
    )


def test_harness_reports_langfuse_cost_and_keeps_list_price(tmp_path: Path) -> None:
    seen: list[tuple[str, int]] = []

    async def reader(session_id: str, *, expected_generations: int, since: datetime) -> Any:
        seen.append((session_id, expected_generations))
        return SessionCost(cost_usd=0.0123, generations=expected_generations)

    report = _run(tmp_path, reader)

    [listing] = report.listings
    assert seen == [(listing.job_id, listing.calls)] and listing.calls > 0
    assert listing.cost_source == "langfuse"
    assert listing.cost_usd == 0.0123
    assert listing.list_price_cost_usd == round(0.001 * listing.calls, 6)
    assert report.summary["cost_source"] == "langfuse"
    assert report.summary["total_cost_usd"] == 0.0123
    table = compare_table({"run": report})
    assert "| cost source | langfuse |" in table
    assert "| list-price cost $ |" in table


def test_harness_labels_a_timed_out_read_as_in_process(tmp_path: Path) -> None:
    async def reader(session_id: str, *, expected_generations: int, since: datetime) -> Any:
        return None

    report = _run(tmp_path, reader)

    [listing] = report.listings
    assert listing.cost_source == "in_process"
    assert listing.cost_usd == listing.list_price_cost_usd > 0
    assert report.summary["cost_source"] == "in_process"


def test_harness_without_a_reader_is_in_process(tmp_path: Path) -> None:
    report = _run(tmp_path)

    assert report.summary["cost_source"] == "in_process"
    assert report.summary["total_cost_usd"] == report.summary["total_list_price_cost_usd"]
