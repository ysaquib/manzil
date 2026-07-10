"""Jobs query-parameter dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query
from manzil_shared.models import JobState

from manzil_api.jobs.exceptions import InvalidJobState


def parse_job_states(
    state: Annotated[list[str] | None, Query()] = None,
) -> list[JobState] | None:
    """Accept repeated `state` params and comma-separated values in one param.

    Frontend polls with `?state=queued,running,waiting_user` (P1-13); FastAPI's
    raw `list[JobState]` only accepts `?state=queued&state=running`.
    """
    if not state:
        return None
    tokens = [t.strip() for item in state for t in item.split(",") if t.strip()]
    parsed: list[JobState] = []
    for token in tokens:
        try:
            parsed.append(JobState(token))
        except ValueError as exc:
            raise InvalidJobState(f"Invalid job state: {token!r}") from exc
    return parsed
