"""Per-domain adapter registry (P0-6, DESIGN §10.7): records which fetch tier
each site requires so the ladder is climbed once per domain, not once per fetch.

`InMemoryRegistry` backs tests and registry-less CLI runs; `PostgresRegistry`
persists to `fetch_adapter_registry` (migration 0001) via asyncpg — plain SQL,
no ORM (IMPLEMENTATION §2).
"""

from __future__ import annotations

from typing import Protocol

import asyncpg
from manzil_shared.models import FetchOutcome

MIN_TIER = 1
MAX_TIER = 2  # tier 3 deferred behind the Phase 0 census gate (§19)


class AdapterRegistry(Protocol):
    async def required_tier(self, domain: str) -> int: ...

    async def record(self, domain: str, tier: int, outcome: FetchOutcome) -> None: ...


def next_required_tier(tier: int, outcome: FetchOutcome) -> int:
    """Self-tuning rule (§10.7): success settles the domain at this tier;
    shell/blocked resume climbing from the next tier on future fetches."""
    if outcome is FetchOutcome.SUCCESS:
        return tier
    if outcome in (FetchOutcome.SHELL, FetchOutcome.BLOCKED):
        return min(tier + 1, MAX_TIER)
    return tier  # error / not_listing say nothing about the tier requirement


class InMemoryRegistry:
    def __init__(self) -> None:
        self.tiers: dict[str, int] = {}
        self.last: dict[str, tuple[int, FetchOutcome]] = {}

    async def required_tier(self, domain: str) -> int:
        return self.tiers.get(domain, MIN_TIER)

    async def record(self, domain: str, tier: int, outcome: FetchOutcome) -> None:
        self.tiers[domain] = next_required_tier(tier, outcome)
        self.last[domain] = (tier, outcome)


class PostgresRegistry:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def required_tier(self, domain: str) -> int:
        conn = await asyncpg.connect(self._dsn)
        try:
            tier = await conn.fetchval(
                "select required_tier from fetch_adapter_registry where site_domain = $1",
                domain,
            )
            return int(tier) if tier is not None else MIN_TIER
        finally:
            await conn.close()

    async def record(self, domain: str, tier: int, outcome: FetchOutcome) -> None:
        required = next_required_tier(tier, outcome)
        success = outcome is FetchOutcome.SUCCESS
        conn = await asyncpg.connect(self._dsn)
        try:
            await conn.execute(
                """
                insert into fetch_adapter_registry
                    (site_domain, required_tier, last_success_tier, last_outcome, updated_at)
                values ($1, $2, $3, $4, now())
                on conflict (site_domain) do update set
                    required_tier = excluded.required_tier,
                    last_success_tier = coalesce(
                        excluded.last_success_tier, fetch_adapter_registry.last_success_tier
                    ),
                    last_outcome = excluded.last_outcome,
                    updated_at = now()
                """,
                domain,
                required,
                tier if success else None,
                outcome.value,
            )
        finally:
            await conn.close()
