"""Stage protocol + injected context (IMPLEMENTATION §3).

A stage is `async (RunState, StageCtx) -> RunState`. Everything a stage
touches beyond its state arrives injected through StageCtx, so tests fake the
world wholesale — no monkeypatching stage internals.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Protocol

from manzil_shared.models import Confidence, RubricCriterion

from manzil_worker.llm import client as llm_client

if TYPE_CHECKING:
    from manzil_worker.fetching.registry import AdapterRegistry
    from manzil_worker.fetching.tiers import Fetcher
    from manzil_worker.state import RunState

CallStructured = Callable[[str, type[Any], str], Awaitable[Any]]


class Persistence(Protocol):
    """The persist-before-advance sink. Phase 0: a JSON file per run;
    Phase 1+ (P1-2): the jobs row."""

    async def save(self, state: RunState) -> None: ...


class NullPersistence:
    async def save(self, state: RunState) -> None:
        return None


def _today() -> date:
    return datetime.now(UTC).date()


@dataclass
class StageCtx:
    fetchers: dict[int, Fetcher] = field(default_factory=dict)
    registry: AdapterRegistry | None = None
    call_structured: CallStructured = llm_client.call_structured
    rubric: list[RubricCriterion] = field(default_factory=list)
    rubric_version: int = 0
    # Hunt setting (§8.2 contract, DESIGN v2.3): effective values below this
    # score as unknown. Phase 0 uses the contract default; hunts own it from P1-5.
    min_confidence: Confidence = Confidence.MEDIUM
    # Household counts (§8.2 hunt settings, §9.5 v1): pet counts drive the pet-rent
    # component of `all_in_monthly`. Default 0 so Phase 0 CLI runs compose no pet rent.
    cats: int = 0
    dogs: int = 0
    persistence: Persistence = field(default_factory=NullPersistence)
    today: Callable[[], date] = _today
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep  # injected so tests skip backoff


Stage = Callable[["RunState", StageCtx], Awaitable["RunState"]]
