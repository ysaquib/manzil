"""P0-6: tier ladder escalation + registry self-tuning (DESIGN §10.7)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from manzil_shared.models import FetchOutcome
from manzil_worker.fetching.ladder import fetch_with_ladder
from manzil_worker.fetching.registry import InMemoryRegistry, next_required_tier
from manzil_worker.fetching.results import FetchResult

PAGES = Path(__file__).parent / "fixtures" / "pages"
SHELL_BODY = (PAGES / "shell_js.html").read_text()
SUCCESS_BODY = (PAGES / "success_text.html").read_text()
URL = "https://slowrender.example/listing/42"


class FakeFetcher:
    def __init__(self, tier: int, body: str, status: int = 200) -> None:
        self.tier = tier
        self._body = body
        self._status = status
        self.calls = 0

    async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
        self.calls += 1
        return FetchResult(
            url=url, final_url=url, status_code=self._status, body=self._body, tier=self.tier
        )


def test_shell_escalates_to_tier2_and_registry_settles_there() -> None:
    registry = InMemoryRegistry()
    tier1 = FakeFetcher(1, SHELL_BODY)
    tier2 = FakeFetcher(2, SUCCESS_BODY)

    ladder = asyncio.run(fetch_with_ladder(URL, registry, {1: tier1, 2: tier2}))

    assert ladder.outcome is FetchOutcome.SUCCESS
    assert ladder.attempts == [(1, FetchOutcome.SHELL), (2, FetchOutcome.SUCCESS)]
    assert ladder.result.tier == 2
    # Ladder is climbed once per domain: the next fetch starts at tier 2.
    assert asyncio.run(registry.required_tier("slowrender.example")) == 2

    second = asyncio.run(fetch_with_ladder(URL, registry, {1: tier1, 2: tier2}))
    assert second.attempts == [(2, FetchOutcome.SUCCESS)]
    assert tier1.calls == 1  # tier 1 never retried for this domain


def test_blocked_at_top_tier_returns_blocked() -> None:
    registry = InMemoryRegistry()
    blocked = FakeFetcher(1, "", status=403)
    also_blocked = FakeFetcher(2, "", status=403)

    ladder = asyncio.run(fetch_with_ladder(URL, registry, {1: blocked, 2: also_blocked}))

    assert ladder.outcome is FetchOutcome.BLOCKED
    assert ladder.attempts == [(1, FetchOutcome.BLOCKED), (2, FetchOutcome.BLOCKED)]


def test_error_and_not_listing_do_not_escalate() -> None:
    assert next_required_tier(1, FetchOutcome.ERROR) == 1
    assert next_required_tier(1, FetchOutcome.NOT_LISTING) == 1
    assert next_required_tier(1, FetchOutcome.SHELL) == 2
    assert next_required_tier(2, FetchOutcome.BLOCKED) == 3  # tier 3 on the ladder (§20 2026-07-07)
    assert next_required_tier(2, FetchOutcome.SUCCESS) == 2
