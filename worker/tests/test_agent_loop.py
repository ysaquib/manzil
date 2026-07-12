"""P3-3: the §10.2 bounded loop — budget exhaustion, a clean non-tool stop, and
`tool_called` job events for every executed tool (in-memory and DB-backed)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from manzil_shared.errors import AgentBudgetExceeded
from manzil_worker.fetching.registry import InMemoryRegistry
from manzil_worker.fetching.results import FetchResult
from manzil_worker.llm.tools import (
    ToolCall,
    ToolContext,
    TurnResponse,
    run_agent_loop,
    tool_context,
)
from manzil_worker.postgres_persistence import make_tool_event_sink

PAGES = Path(__file__).parent / "fixtures" / "pages"
SUCCESS_BODY = (PAGES / "success_text.html").read_text()
FETCH_URL = "https://example.test/listing"


class FakeFetcher:
    def __init__(self, tier: int, body: str) -> None:
        self.tier = tier
        self._body = body
        self.calls = 0

    async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
        self.calls += 1
        return FetchResult(url=url, final_url=url, status_code=200, body=self._body, tier=self.tier)


def _fetch_ctx(event_sink=None) -> tuple[ToolContext, FakeFetcher]:
    fetcher = FakeFetcher(1, SUCCESS_BODY)
    ctx = ToolContext(fetchers={1: fetcher}, registry=InMemoryRegistry(), event_sink=event_sink)
    return ctx, fetcher


async def test_non_tool_stop_returns_the_final_message() -> None:
    async def turn_fn(messages, specs):  # type: ignore[no-untyped-def]
        return TurnResponse(tool_calls=[], text="here is the answer")

    from manzil_worker.llm.tools import fetch_page

    result = await run_agent_loop(
        stage="discover", task="go", tools=[fetch_page], turn_fn=turn_fn, max_turns=8
    )
    assert result.final_text == "here is the answer"
    assert result.turns == 1


async def test_budget_exhaustion_raises_after_exactly_max_turns() -> None:
    from manzil_worker.llm.tools import fetch_page

    turns = 0

    async def turn_fn(messages, specs):  # type: ignore[no-untyped-def]
        nonlocal turns
        turns += 1
        return TurnResponse(tool_calls=[ToolCall(name="fetch_page", input={"url": FETCH_URL})])

    events: list[tuple] = []

    async def sink(stage, tool, tool_input, summary):  # type: ignore[no-untyped-def]
        events.append((stage, tool, tool_input, summary))

    ctx, fetcher = _fetch_ctx(event_sink=sink)
    with tool_context(ctx):  # noqa: SIM117
        with pytest.raises(AgentBudgetExceeded, match="3-turn budget"):
            await run_agent_loop(
                stage="discover", task="go", tools=[fetch_page], turn_fn=turn_fn, max_turns=3
            )

    assert turns == 3  # exactly max_turns model turns
    assert fetcher.calls == 3  # one fetch per turn
    # Every executed tool left a tool_called event.
    assert len(events) == 3
    assert all(e[1] == "fetch_page" for e in events)


async def test_executed_tool_writes_a_tool_called_job_event(pg_pool: asyncpg.Pool) -> None:
    from manzil_worker.llm.tools import fetch_page

    hunt_id, listing_id, job_id = uuid4(), uuid4(), uuid4()
    property_id = uuid4()
    await pg_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 't', $2)", hunt_id, uuid4()
    )
    await pg_pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'P', 'A')", property_id
    )
    await pg_pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1,$2,$3,$4)",
        listing_id,
        hunt_id,
        property_id,
        uuid4(),
    )
    await pg_pool.execute(
        "insert into jobs (id, hunt_id, hunt_listing_id, type, state) "
        "values ($1,$2,$3,'ingest','running')",
        job_id,
        hunt_id,
        listing_id,
    )
    try:
        one = [0]

        async def turn_fn(messages, specs):  # type: ignore[no-untyped-def]
            one[0] += 1
            if one[0] == 1:
                return TurnResponse(
                    tool_calls=[ToolCall(name="fetch_page", input={"url": FETCH_URL})]
                )
            return TurnResponse(tool_calls=[], text="done")

        ctx, _ = _fetch_ctx(event_sink=make_tool_event_sink(pg_pool, job_id))
        with tool_context(ctx):
            result = await run_agent_loop(
                stage="discover", task="go", tools=[fetch_page], turn_fn=turn_fn, max_turns=8
            )
        assert result.final_text == "done"

        rows = await pg_pool.fetch(
            "select stage, event, detail from job_events "
            "where job_id = $1 and event = 'tool_called'",
            job_id,
        )
        assert len(rows) == 1
        assert rows[0]["stage"] == "discover"
        import json

        detail = json.loads(rows[0]["detail"])
        assert detail["tool"] == "fetch_page"
        assert detail["input"] == {"url": FETCH_URL}
        assert detail["result"]  # a non-empty cleaned-text summary
    finally:
        await pg_pool.execute("delete from jobs where id = $1", job_id)
        await pg_pool.execute("delete from hunt_listings where id = $1", listing_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
