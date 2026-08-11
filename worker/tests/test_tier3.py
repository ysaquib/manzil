"""Tier 3 (§10.7, §20 2026-07-07): provider seam, ladder escalation, census
verdicts, and the slug-hint stopgap. No real unblocker calls — httpx
MockTransport plays the vendor."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from manzil_shared.errors import FetchProviderError
from manzil_shared.models import FetchOutcome
from manzil_worker.fetching.census import run_census
from manzil_worker.fetching.ladder import fetch_with_ladder
from manzil_worker.fetching.registry import InMemoryRegistry, next_required_tier
from manzil_worker.fetching.slug_hint import search_hint
from manzil_worker.fetching.tier3 import (
    Tier3Fetcher,
    missing_provider_env,
    provider_configured,
    tier3_configured,
    tier3_provider,
)
from worker_helpers import PAGES, FakeFetcher


def _envelope(status: int, body: str, headers: dict[str, str] | None = None) -> httpx.Response:
    """What Bright Data's `format: "json"` returns: the TARGET's response,
    wrapped, so its status never collides with the API's own."""
    return httpx.Response(200, json={"status": status, "headers": headers or {}, "body": body})


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


def test_tier3_configured_requires_every_setting_not_just_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MANZIL_TIER3_PROVIDER", raising=False)
    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
    monkeypatch.delenv("BRIGHTDATA_ZONE", raising=False)
    monkeypatch.delenv("BRIGHTDATA_KEY_NAME", raising=False)
    # Real keys can reach os.environ before this test runs (cli.py's import-time
    # load_dotenv exports .env at collection) — isolate from them.
    monkeypatch.delenv("SCRAPINGBEE_API_KEY", raising=False)
    assert tier3_configured() is None
    # A key with no zone is the 2026-08-11 incident: it looks enabled, joins the
    # ladder, and 400s on every request. Treated as not configured.
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "key")
    assert tier3_configured() is None
    monkeypatch.setenv("BRIGHTDATA_ZONE", "manzil_unlocker_prod")
    assert tier3_configured() == "brightdata"
    # Switching provider = one env var; its own settings gate availability.
    monkeypatch.setenv("MANZIL_TIER3_PROVIDER", "scrapingbee")
    assert tier3_configured() is None
    monkeypatch.setenv("SCRAPINGBEE_API_KEY", "key")
    assert tier3_configured() == "scrapingbee"


def test_the_zone_accepts_the_key_name_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MANZIL_TIER3_PROVIDER", raising=False)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "key")
    monkeypatch.delenv("BRIGHTDATA_ZONE", raising=False)
    monkeypatch.setenv("BRIGHTDATA_KEY_NAME", "manzil_webunlocker1")
    assert tier3_configured() == "brightdata"


def test_an_empty_env_var_is_unset_not_a_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank field in a deploy dashboard is a missing setting. `os.environ.get`
    with a default returns the empty string instead, which used to be sent to the
    provider verbatim."""
    monkeypatch.delenv("MANZIL_TIER3_PROVIDER", raising=False)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "key")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "   ")
    monkeypatch.delenv("BRIGHTDATA_KEY_NAME", raising=False)
    assert tier3_configured() is None
    assert missing_provider_env(tier3_provider()) == ["BRIGHTDATA_ZONE"]


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
        return _envelope(200, LISTING_HTML, {"Content-Type": "text/html"})

    fetcher = Tier3Fetcher(transport=httpx.MockTransport(handler), resolver=_public_resolver)
    result = asyncio.run(fetcher.fetch("https://www.zillow.com/detroit-mi/rentals/"))

    assert seen["url"] == "https://api.brightdata.com/request"
    assert seen["auth"] == "Bearer bd-key"
    assert seen["payload"] == {
        "zone": "my_zone",
        "url": "https://www.zillow.com/detroit-mi/rentals/",
        "format": "json",
    }
    assert result.tier == 3
    assert result.provider == "brightdata"
    assert result.status_code == 200
    assert result.body == LISTING_HTML
    # The TARGET's headers, not the provider API's — the classifier reads these.
    assert result.headers == {"content-type": "text/html"}


def test_the_targets_status_survives_the_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 404 from the page is a 404 on the FetchResult, even though the API call
    that carried it succeeded."""
    monkeypatch.delenv("MANZIL_TIER3_PROVIDER", raising=False)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd-key")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "my_zone")

    fetcher = Tier3Fetcher(
        transport=httpx.MockTransport(lambda _: _envelope(404, "Not found")),
        resolver=_public_resolver,
    )
    result = asyncio.run(fetcher.fetch("https://www.zillow.com/gone/"))
    assert result.status_code == 404
    assert result.body == "Not found"


def test_a_provider_rejection_is_never_reported_as_the_targets_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 2026-08-11 production incident: the zone was set to the API key's
    name, Bright Data 400'd every request, and the job blamed the listing URL."""
    monkeypatch.delenv("MANZIL_TIER3_PROVIDER", raising=False)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd-key")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "manzil_webunlocker1")

    fetcher = Tier3Fetcher(
        transport=httpx.MockTransport(lambda _: httpx.Response(400, text="Unknown zone")),
        resolver=_public_resolver,
    )
    with pytest.raises(FetchProviderError) as raised:
        asyncio.run(fetcher.fetch("https://www.zillow.com/apartments/x/"))

    assert raised.value.provider == "brightdata"
    assert raised.value.status == 400
    assert raised.value.retryable is False  # deterministic: do not buy it again
    assert "Unknown zone" in str(raised.value)


def test_provider_congestion_stays_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MANZIL_TIER3_PROVIDER", raising=False)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd-key")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "my_zone")

    fetcher = Tier3Fetcher(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="upstream busy")),
        resolver=_public_resolver,
    )
    with pytest.raises(FetchProviderError) as raised:
        asyncio.run(fetcher.fetch("https://www.zillow.com/x/"))
    assert raised.value.retryable is True


def test_a_missing_zone_fails_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MANZIL_TIER3_PROVIDER", raising=False)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd-key")
    monkeypatch.delenv("BRIGHTDATA_ZONE", raising=False)
    monkeypatch.delenv("BRIGHTDATA_KEY_NAME", raising=False)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _envelope(200, LISTING_HTML)

    fetcher = Tier3Fetcher(transport=httpx.MockTransport(handler), resolver=_public_resolver)
    with pytest.raises(FetchProviderError, match="BRIGHTDATA_ZONE is not set"):
        asyncio.run(fetcher.fetch("https://www.zillow.com/x/"))
    assert calls["n"] == 0


def test_a_non_envelope_200_still_reads_as_the_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """Degrade to the pre-envelope behavior rather than calling an unexpected
    vendor shape a rejection."""
    monkeypatch.delenv("MANZIL_TIER3_PROVIDER", raising=False)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd-key")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "my_zone")

    fetcher = Tier3Fetcher(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=LISTING_HTML)),
        resolver=_public_resolver,
    )
    result = asyncio.run(fetcher.fetch("https://www.zillow.com/x/"))
    assert result.status_code == 200 and result.body == LISTING_HTML


def test_provider_configured_names_the_whole_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd-key")
    monkeypatch.delenv("BRIGHTDATA_ZONE", raising=False)
    monkeypatch.delenv("BRIGHTDATA_KEY_NAME", raising=False)
    assert provider_configured("brightdata") is False
    monkeypatch.setenv("BRIGHTDATA_ZONE", "z")
    assert provider_configured("brightdata") is True
    assert provider_configured("no-such-provider") is False


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
    monkeypatch.setenv("BRIGHTDATA_ZONE", "my_zone")

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
