"""Trace-completeness check against Langfuse (NFR6, IMPLEMENTATION §6).

Cost no longer comes from here: the seam tallies OpenRouter's billed spend
in-process (DESIGN §20 v3.111). What Langfuse can uniquely answer is whether
every call actually reached it — "an untraced call is a bug" is otherwise an
assertion nobody checks. `session_generations` counts a session's generations
so the eval harness can compare that with the calls it made.

It lives in `llm/` because Langfuse is initialized inside the seam only.

Langfuse ingests asynchronously: a flushed generation is not queryable the
instant the call returns. The check therefore polls until it sees at least the
expected count and returns `None` when the deadline passes, which the harness
reports as an incomplete trace, never as a pass.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

from manzil_shared.config import (
    LANGFUSE_TRACE_CHECK_POLL_SECONDS,
    LANGFUSE_TRACE_CHECK_TIMEOUT_SECONDS,
)

from manzil_worker.llm.client import _langfuse, _require_langfuse_configured

if TYPE_CHECKING:
    from datetime import datetime

_PAGE_LIMIT = 1000  # the v2 observations endpoint's maximum page size


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


async def _count_once(api: Any, session_id: str, since: datetime) -> int:
    """Count the session's generations, following the cursor."""
    count = 0
    cursor: str | None = None
    filter_ = _session_filter(session_id, since)
    while True:
        page = await api.observations.get_many(
            fields="core", filter=filter_, limit=_PAGE_LIMIT, cursor=cursor
        )
        count += len(page.data)
        cursor = page.meta.cursor
        if not cursor:
            return count


async def session_generations(
    session_id: str,
    *,
    expected_generations: int,
    since: datetime,
    api: Any | None = None,
    timeout_s: float = LANGFUSE_TRACE_CHECK_TIMEOUT_SECONDS,
    poll_s: float = LANGFUSE_TRACE_CHECK_POLL_SECONDS,
) -> int | None:
    """Generations Langfuse holds for `session_id`, once there are at least
    `expected_generations`; `None` if they never all arrive before the timeout.

    `api` is injectable for tests; by default it is the configured client's
    async API (which requires the Langfuse keys, like every live call)."""
    if expected_generations <= 0:
        return 0
    if api is None:
        _require_langfuse_configured()
        api = _langfuse().async_api
    deadline = time.monotonic() + timeout_s
    while True:
        count = await _count_once(api, session_id, since)
        if count >= expected_generations:
            return count
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(poll_s)
