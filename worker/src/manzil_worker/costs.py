"""The run cost tally (AD-C) — every dollar a stage spends, LLM or not.

This module owns `CostTally` and the ambient `cost_tally()` context the runner
opens around each stage. It lives *outside* `llm/` on purpose: tier-3 fetching
is real spend that has nothing to do with a model call, and `fetching/tier3.py`
must be able to record it without importing the LLM seam.

Two channels, deliberately kept apart:

- **token cost** (`cost_usd`, via `add`) — what the model call billed. Owned by
  `llm/client.py`, which is the only caller of `add`.
- **fetch cost** (`fetch_cost_usd`, via `record_fetch`) — what a managed
  unblocker billed. Owned by `fetching/tier3.py`.

`total_cost_usd` is the sum, and it is what the runner folds onto
`RunState.cost_usd`. Keeping the channels separate is what lets the Costs view
answer "how much of this was the model?" — a single blended number cannot.

`llm/client.py` re-exports `CostTally` and `cost_tally` so every existing
`from manzil_worker.llm.client import cost_tally` keeps working unchanged.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog
from manzil_shared.config import TIER3_PRICES_USD

if TYPE_CHECKING:
    from collections.abc import Iterator

log = structlog.get_logger()


@dataclass(frozen=True)
class CallUsage:
    """One model call's billed usage, as the seam normalized it."""

    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float


@dataclass
class CostTally:
    """Accumulates across calls; the runner adds `total_cost_usd` onto
    `RunState.cost_usd` at each stage boundary.

    `cost_usd` is the **token** total only — new fields are appended so existing
    positional/keyword construction (`CostTally(calls=2, cost_usd=0.002)`) keeps
    working.
    """

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    # ── non-LLM spend (AD-C) ────────────────────────────────────────────────
    fetch_calls: int = 0
    fetch_cost_usd: float = 0.0
    # provider name -> calls. Kept per provider because the price is per
    # provider, so a blended count could not be re-priced after the fact.
    fetch_calls_by_provider: dict[str, int] = field(default_factory=dict)

    @property
    def total_cost_usd(self) -> float:
        """Everything this tally billed — the number that belongs on the job."""
        return self.cost_usd + self.fetch_cost_usd

    def add(self, usage: CallUsage) -> None:
        self.calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_tokens += usage.cache_read_tokens
        self.cache_write_tokens += usage.cache_write_tokens
        self.cost_usd += usage.cost_usd

    def add_fetch(self, provider: str, *, calls: int = 1) -> None:
        """Bill `calls` requests to `provider`. An unpriced provider still
        increments the counters and adds $0 — see `TIER3_PRICES_USD`."""
        price = TIER3_PRICES_USD.get(provider)
        self.fetch_calls += calls
        self.fetch_cost_usd += calls * (price or 0.0)
        self.fetch_calls_by_provider[provider] = (
            self.fetch_calls_by_provider.get(provider, 0) + calls
        )

    def merge(self, other: CostTally) -> None:
        """Fold `other` into this tally. The runner uses this to keep the spend
        from a *failed* stage attempt: a retry opens a fresh tally, and without
        the merge the money the failed attempt already burned would vanish from
        the job's total."""
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.cost_usd += other.cost_usd
        self.fetch_calls += other.fetch_calls
        self.fetch_cost_usd += other.fetch_cost_usd
        for provider, calls in other.fetch_calls_by_provider.items():
            self.fetch_calls_by_provider[provider] = (
                self.fetch_calls_by_provider.get(provider, 0) + calls
            )


_active_tally: ContextVar[CostTally | None] = ContextVar("manzil_cost_tally", default=None)


@contextmanager
def cost_tally() -> Iterator[CostTally]:
    tally = CostTally()
    token = _active_tally.set(tally)
    try:
        yield tally
    finally:
        _active_tally.reset(token)


def active_tally() -> CostTally | None:
    """The tally the current stage is billing to, or None outside a stage."""
    return _active_tally.get()


def record_fetch(provider: str, *, calls: int = 1) -> None:
    """Bill a managed-unblocker request to the active tally.

    A no-op outside a stage (bare CLI fetches, tests) — spend with no run to
    attribute it to is not worth inventing a tally for.
    """
    tally = _active_tally.get()
    if tally is None:
        return
    tally.add_fetch(provider, calls=calls)
    if provider not in TIER3_PRICES_USD:
        # Loud once per call rather than silently free: an unpriced provider is
        # a gap in `TIER3_PRICES_USD`, not a free service.
        log.warning("tier3_provider_unpriced", provider=provider)
