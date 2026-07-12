"""Tier 3 (§10.7, §20 2026-07-07): provider seam, ladder escalation, census
verdicts, and the slug-hint stopgap. No real unblocker calls — httpx
MockTransport plays the vendor."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from manzil_shared.models import FetchOutcome
from manzil_worker.fetching.census import run_census
from manzil_worker.fetching.ladder import fetch_with_ladder
from manzil_worker.fetching.registry import InMemoryRegistry, next_required_tier
from manzil_worker.fetching.slug_hint import search_hint
from manzil_worker.fetching.tier3 import Tier3Fetcher, tier3_configured, tier3_provider
from worker_helpers import PAGES, FakeFetcher

LISTING_HTML = (
    "<html><body>" + "2 bedroom apartment with rent and lease terms. " * 60 + ("</body></html>")
)


async def _public_resolver(host: str) -> list[str]:
    """Fake resolver: every host maps to a public IP so the tier-3 SSRF screen
    passes without live DNS (no network in CI)."""
    return ["93.184.216.34"]


# ── provider selection ───────────────────────────────────────────────────────


def test_brightdata_is_the_default_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MANZIL_TIER3_PROVIDER", raising=False)
    assert tier3_provider().name == "brightdata"


def test_unknown_provider_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANZIL_TIER3_PROVIDER", "scrapey-mc-scrapeface")
    with pytest.raises(KeyError, match="known providers"):
        tier3_provider()


def test_tier3_configured_requires_the_selected_providers_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MANZIL_TIER3_PROVIDER", raising=False)
    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
    # Real keys can reach os.environ before this test runs (cli.py's import-time
    # load_dotenv exports .env at collection) — isolate from them.
    monkeypatch.delenv("SCRAPINGBEE_API_KEY", raising=False)
    assert tier3_configured() is None
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "key")
    assert tier3_configured() == "brightdata"
    # Switching provider = one env var; its own key gates availability.
    monkeypatch.setenv("MANZIL_TIER3_PROVIDER", "scrapingbee")
    assert tier3_configured() is None
    monkeypatch.setenv("SCRAPINGBEE_API_KEY", "key")
    assert tier3_configured() == "scrapingbee"


# ── the fetcher itself ───────────────────────────────────────────────────────


def test_brightdata_request_shape_and_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MANZIL_TIER3_PROVIDER", raising=False)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd-key")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "my_zone")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, text=LISTING_HTML)

    fetcher = Tier3Fetcher(transport=httpx.MockTransport(handler), resolver=_public_resolver)
    result = asyncio.run(fetcher.fetch("https://www.zillow.com/detroit-mi/rentals/"))

    assert seen["url"] == "https://api.brightdata.com/request"
    assert seen["auth"] == "Bearer bd-key"
    assert seen["payload"] == {
        "zone": "my_zone",
        "url": "https://www.zillow.com/detroit-mi/rentals/",
        "format": "raw",
    }
    assert result.tier == 3
    assert result.status_code == 200
    assert result.body == LISTING_HTML


def test_scrapingbee_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANZIL_TIER3_PROVIDER", "scrapingbee")
    monkeypatch.setenv("SCRAPINGBEE_API_KEY", "sb-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "app.scrapingbee.com"
        assert request.url.params["api_key"] == "sb-key"
        assert request.url.params["url"] == "https://www.trulia.com/for_rent/Detroit,MI/"
        assert request.url.params["render_js"] == "true"
        return httpx.Response(200, text=LISTING_HTML)

    fetcher = Tier3Fetcher(transport=httpx.MockTransport(handler), resolver=_public_resolver)
    result = asyncio.run(fetcher.fetch("https://www.trulia.com/for_rent/Detroit,MI/"))
    assert result.tier == 3 and result.body == LISTING_HTML


def test_vendor_network_failure_is_a_fetch_error_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MANZIL_TIER3_PROVIDER", raising=False)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd-key")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("vendor down")

    fetcher = Tier3Fetcher(transport=httpx.MockTransport(handler), resolver=_public_resolver)
    result = asyncio.run(fetcher.fetch("https://www.zillow.com/x"))
    assert result.status_code == 0
    assert result.error is not None
    assert result.body == ""


# ── ladder + registry with three rungs ───────────────────────────────────────

BLOCK_PAGE = (PAGES / "blocked_px.html").read_text()  # classifies as BLOCKED


def test_ladder_climbs_all_three_tiers(tmp_path: Path) -> None:
    fetchers = {
        1: FakeFetcher(1, BLOCK_PAGE),
        2: FakeFetcher(2, BLOCK_PAGE),
        3: FakeFetcher(3, LISTING_HTML),
    }
    ladder = asyncio.run(
        fetch_with_ladder("https://hostile.example/listing-x", InMemoryRegistry(), fetchers)
    )
    assert [t for t, _ in ladder.attempts] == [1, 2, 3]
    assert ladder.outcome is FetchOutcome.SUCCESS
    assert ladder.result.tier == 3


def test_ladder_skips_missing_rungs(tmp_path: Path) -> None:
    """--no-tier2 with tier 3 configured: blocked at 1 escalates straight to 3."""
    fetchers = {1: FakeFetcher(1, BLOCK_PAGE), 3: FakeFetcher(3, LISTING_HTML)}
    ladder = asyncio.run(
        fetch_with_ladder("https://hostile.example/listing-x", InMemoryRegistry(), fetchers)
    )
    assert [t for t, _ in ladder.attempts] == [1, 3]
    assert ladder.outcome is FetchOutcome.SUCCESS


def test_registry_demanding_tier3_clamps_to_available_fetchers() -> None:
    """A domain recorded as needing tier 3 must not crash a run without a
    tier-3 fetcher — it starts at the best runnable rung instead."""
    registry = InMemoryRegistry()
    registry.tiers["hostile.example"] = 3
    fetchers = {1: FakeFetcher(1, BLOCK_PAGE), 2: FakeFetcher(2, BLOCK_PAGE)}
    ladder = asyncio.run(fetch_with_ladder("https://hostile.example/listing-x", registry, fetchers))
    assert [t for t, _ in ladder.attempts] == [2]
    assert ladder.outcome is FetchOutcome.BLOCKED


def test_registry_self_tunes_up_to_tier3() -> None:
    assert next_required_tier(2, FetchOutcome.BLOCKED) == 3
    assert next_required_tier(3, FetchOutcome.BLOCKED) == 3  # capped at MAX_TIER
    assert next_required_tier(3, FetchOutcome.SUCCESS) == 3


# ── census verdicts with tier 3 on the ladder ────────────────────────────────


def test_census_tier3_column_and_verdicts(tmp_path: Path) -> None:
    fetchers = {
        1: FakeFetcher(1, BLOCK_PAGE),
        2: FakeFetcher(2, BLOCK_PAGE),
        3: FakeFetcher(3, LISTING_HTML),
    }
    out = asyncio.run(run_census(["https://hostile.example/a"], fetchers, tmp_path / "census.csv"))
    header, row = out.read_text().strip().splitlines()
    assert "tier3_outcome" in header
    assert "tier3_ok" in row

    all_blocked = {
        1: FakeFetcher(1, BLOCK_PAGE),
        2: FakeFetcher(2, BLOCK_PAGE),
        3: FakeFetcher(3, BLOCK_PAGE),
    }
    out = asyncio.run(
        run_census(["https://hostile.example/a"], all_blocked, tmp_path / "census2.csv")
    )
    assert "hostile_unfetchable" in out.read_text()

    no_tier3 = {1: FakeFetcher(1, BLOCK_PAGE), 2: FakeFetcher(2, BLOCK_PAGE)}
    out = asyncio.run(run_census(["https://hostile.example/a"], no_tier3, tmp_path / "census3.csv"))
    assert "hostile_needs_tier3" in out.read_text()  # pre-tier-3 verdict preserved


# ── slug-hint stopgap ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "hint"),
    [
        (
            "https://www.rent.com/apartment/autumn-ridge-detroit-mi-lc5933022",
            "autumn ridge detroit mi",
        ),
        (
            "https://www.apartments.com/riverfront-towers-detroit-mi/xk1234/",
            "riverfront towers detroit mi",
        ),
        (
            "https://www.zillow.com/apartments/detroit-mi/windsor-woods/5XjKcm/",
            "detroit mi windsor woods",
        ),
        ("https://www.forrent.com/find/MI/metro-Detroit/Detroit", "mi metro detroit"),
        ("https://www.forrent.com/find/MI/metro-Detroit/Dearborn", "mi metro detroit dearborn"),
        ("https://example.com/", None),  # no identity in the path
        ("https://example.com/listings/12345", None),  # ids and noise only
    ],
)
def test_search_hint_extracts_property_identity(url: str, hint: str | None) -> None:
    assert search_hint(url) == hint
