"""FETCH's handling of a managed unblocker refusing *us* (§20 2026-08-11).

The production incident these pin: `BRIGHTDATA_ZONE` held the API key's name
instead of the zone, Bright Data answered HTTP 400 to every request, and the
job reported `fetch error for <zillow url> (status 400)` — a status the listing
page never returned — then bought the same refusal three more times on the
retry ladder.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from manzil_shared.errors import FetchProviderError, StageFatal, StageRetryable
from manzil_shared.models import JobType
from manzil_worker.fetching.registry import InMemoryRegistry
from manzil_worker.fetching.results import FetchResult
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.fetch import fetch_stage
from manzil_worker.state import RunState
from worker_helpers import PAGES, FakeFetcher

URL = "https://www.zillow.com/apartments/detroit-mi/vinton/9GkMrx/"
LISTING = (PAGES / "e2e_listing.html").read_text()


class RefusingFetcher:
    """A tier-3 fetcher whose provider rejects the request itself."""

    tier = 3

    def __init__(self, *, retryable: bool) -> None:
        self._retryable = retryable
        self.calls = 0

    async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
        self.calls += 1
        raise FetchProviderError(
            "brightdata",
            status=503 if self._retryable else 400,
            reason="Unknown zone",
            retryable=self._retryable,
        )


def _state(url: str = URL) -> RunState:
    return RunState(job_id=uuid4(), job_type=JobType.INGEST, url=url)


def _ctx(fetchers: dict[int, object], *, pinned: dict[str, int] | None = None) -> StageCtx:
    registry = InMemoryRegistry()
    registry.tiers.update(pinned or {})
    return StageCtx(registry=registry, fetchers=fetchers)  # type: ignore[arg-type]


def test_a_deterministic_provider_refusal_is_fatal_not_retryable() -> None:
    """`StageRetryable` would spend four credits to be told the same thing four
    times; the runner's backoff cannot fix a wrong zone."""
    fetcher = RefusingFetcher(retryable=False)

    with pytest.raises(StageFatal) as raised:
        asyncio.run(fetch_stage(_state(), _ctx({3: fetcher})))

    assert fetcher.calls == 1
    message = str(raised.value)
    assert "brightdata API rejected the request (HTTP 400)" in message
    assert "Unknown zone" in message
    assert URL in message  # which submission died, without blaming its status


def test_provider_congestion_is_still_retryable() -> None:
    with pytest.raises(StageRetryable):
        asyncio.run(fetch_stage(_state(), _ctx({3: RefusingFetcher(retryable=True)})))


def test_a_refused_sibling_never_sinks_a_usable_submission() -> None:
    """Per-source isolation holds for provider errors too: the submitted page
    fetched fine at tier 1, so a tier-3 sibling refusal is a warning."""
    state = _state()
    sibling = "https://sibling.test/maple-court"
    state.slate_urls = [state.url, sibling]

    out = asyncio.run(
        fetch_stage(
            state,
            _ctx(
                {1: FakeFetcher(1, LISTING), 3: RefusingFetcher(retryable=False)},
                pinned={"sibling.test": 3},  # only the sibling reaches the unblocker
            ),
        )
    )

    assert [source.url for source in out.sources] == [URL]
    assert out.sources[0].cleaned_text


def test_a_target_error_still_names_the_page_and_the_rung() -> None:
    """The other half of the fix: when the *target* really did answer 500, say
    so, and say which rung carried it."""
    with pytest.raises(StageRetryable) as raised:
        asyncio.run(fetch_stage(_state(), _ctx({1: FakeFetcher(1, "boom", status=500)})))

    message = str(raised.value)
    assert "the page returned status 500 at tier 1" in message
    assert URL in message
