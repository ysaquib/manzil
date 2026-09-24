"""Read-back of traced spend from Langfuse (IMPLEMENTATION §6).

The seam writes one Langfuse generation per model call and stamps it with the
call's **actual** cost — OpenRouter's reported `usage.cost` when the response
carries it, the `MODEL_PRICES` list-price estimate only when it does not (see
`_actual_cost_usd` in `llm/client.py`). This module reads those generations
back so the eval harness reports what the calls actually billed, from the same
store that production traces live in.

It lives in `llm/` because Langfuse is initialized inside the seam only.

Langfuse ingests asynchronously: a generation flushed by the SDK is not
queryable the instant the call returns. `session_cost` therefore polls until
it sees every costed generation it expects, and returns `None` rather than a
partial sum when the deadline passes — a short read must never masquerade as
a cheap run.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from manzil_shared.config import LANGFUSE_COST_POLL_SECONDS, LANGFUSE_COST_READ_TIMEOUT_SECONDS

from manzil_worker.llm.client import _langfuse, _require_langfuse_configured

if TYPE_CHECKING:
    from datetime import datetime

_PAGE_LIMIT = 1000  # the v2 observations endpoint's maximum page size


@dataclass(frozen=True)
class SessionCost:
    """Summed spend of one Langfuse session (session = `job_id`)."""

    cost_usd: float
    generations: int


def _session_filter(session_id: str, since: datetime) -> str:
    # The structured `filter` overrides the endpoint's individual query
    # parameters (fromStartTime included), so the time bound lives here too.
    return json.dumps(
        [
            {"type": "string", "column": "sessionId", "operator": "=", "value": session_id},
            {"type": "string", "column": "type", "operator": "=", "value": "GENERATION"},
            {
                "type": "datetime",
                "column": "startTime",
                "operator": ">=",
                "value": since.isoformat(),
            },
        ]
    )


async def _read_once(api: Any, session_id: str, since: datetime) -> SessionCost:
    """Sum every *costed* generation in the session, following the cursor."""
    total = 0.0
    costed = 0
    cursor: str | None = None
    filter_ = _session_filter(session_id, since)
    while True:
        page = await api.observations.get_many(
            fields="core,usage", filter=filter_, limit=_PAGE_LIMIT, cursor=cursor
        )
        for observation in page.data:
            # A generation Langfuse has not finished costing is not yet a read.
            if observation.total_cost is not None:
                total += observation.total_cost
                costed += 1
        cursor = page.meta.cursor
        if not cursor:
            return SessionCost(cost_usd=total, generations=costed)


async def session_cost(
    session_id: str,
    *,
    expected_generations: int,
    since: datetime,
    api: Any | None = None,
    timeout_s: float = LANGFUSE_COST_READ_TIMEOUT_SECONDS,
    poll_s: float = LANGFUSE_COST_POLL_SECONDS,
) -> SessionCost | None:
    """Actual spend of `session_id`, once Langfuse holds at least
    `expected_generations` costed generations; `None` on timeout.

    `api` is injectable for tests; by default it is the configured client's
    async API (which requires the Langfuse keys, like every live call)."""
    if expected_generations <= 0:
        return SessionCost(cost_usd=0.0, generations=0)
    if api is None:
        _require_langfuse_configured()
        api = _langfuse().async_api
    deadline = time.monotonic() + timeout_s
    while True:
        read = await _read_once(api, session_id, since)
        if read.generations >= expected_generations:
            return read
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(poll_s)
