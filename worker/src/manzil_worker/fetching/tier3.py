"""Tier 3 — managed unblocker (DESIGN §10.7, §20 2026-07-07).

Fallback, never default: the ladder only reaches tier 3 after tiers 1-2
classify shell/blocked. The provider is a swappable adapter chosen by
`MANZIL_TIER3_PROVIDER` (default `brightdata`); free plans only — paid
escalation is a new §20 decision, not an env change.

Changing provider = set `MANZIL_TIER3_PROVIDER` + that provider's key env.
Adding a provider = one `_Provider` entry in `PROVIDERS` (request builder +
required env vars); nothing outside this module changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from manzil_shared.config import TIER3_TIMEOUT_SECONDS
from manzil_shared.errors import PrivateAddressRefused

from manzil_worker.fetching.results import FetchResult
from manzil_worker.fetching.ssrf import Resolver, screen_url

if TYPE_CHECKING:
    from collections.abc import Callable

import os

log = structlog.get_logger()


@dataclass(frozen=True)
class _Request:
    method: str
    url: str
    headers: dict[str, str]
    json: dict[str, Any] | None = None
    params: dict[str, str] | None = None


@dataclass(frozen=True)
class _Provider:
    name: str
    required_env: tuple[str, ...]
    build: Callable[[str], _Request]  # target url -> API request


def _brightdata(url: str) -> _Request:
    # Web Unlocker API: POST /request with the zone name; format=raw returns
    # the target page's HTML as the response body.
    return _Request(
        method="POST",
        url="https://api.brightdata.com/request",
        headers={
            "Authorization": f"Bearer {os.environ['BRIGHTDATA_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={
            "zone": os.environ.get("BRIGHTDATA_ZONE", "web_unlocker1"),
            "url": url,
            "format": "raw",
        },
    )


def _scrapingbee(url: str) -> _Request:
    return _Request(
        method="GET",
        url="https://app.scrapingbee.com/api/v1/",
        headers={},
        params={
            "api_key": os.environ["SCRAPINGBEE_API_KEY"],
            "url": url,
            "render_js": "true",
        },
    )


PROVIDERS: dict[str, _Provider] = {
    "brightdata": _Provider("brightdata", ("BRIGHTDATA_API_KEY",), _brightdata),
    "scrapingbee": _Provider("scrapingbee", ("SCRAPINGBEE_API_KEY",), _scrapingbee),
}


def tier3_provider() -> _Provider:
    """The selected provider; unknown names fail loudly (no silent fallback)."""
    name = os.environ.get("MANZIL_TIER3_PROVIDER", "brightdata")
    try:
        return PROVIDERS[name]
    except KeyError:
        raise KeyError(
            f"MANZIL_TIER3_PROVIDER={name!r}: known providers are {sorted(PROVIDERS)}"
        ) from None


def tier3_configured() -> str | None:
    """Provider name if its key env is set, else None (tier 3 stays off the
    ladder — exactly the pre-tier-3 behavior)."""
    provider = tier3_provider()
    return provider.name if all(os.environ.get(k) for k in provider.required_env) else None


class Tier3Fetcher:
    """Sends the URL to the unblocker API; the returned HTML flows through the
    same classifier/cleaner as any other tier. Unblockers retry/solve on their
    side, hence the long timeout."""

    tier = 3

    def __init__(
        self,
        timeout: float = TIER3_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,  # injected by tests
        *,
        resolver: Resolver | None = None,  # injected by tests; None → real getaddrinfo
    ) -> None:
        self._timeout = timeout
        self._transport = transport
        self._resolver = resolver

    async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
        provider = tier3_provider()
        try:
            # Defense-in-depth screen (§16). The unblocker fetches from *its*
            # network, so a private target is unreachable-from-there rather than an
            # SSRF against us (a provider fetching 169.254.169.254 returns THEIR
            # metadata, not ours); we screen anyway for consistency across tiers.
            # PrivateAddressRefused propagates (refusal, not a retryable error); a
            # DNS OSError is caught below → retryable, like any tier.
            await screen_url(url, resolver=self._resolver)
            request = provider.build(url)
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.request(
                    request.method,
                    request.url,
                    headers=request.headers,
                    json=request.json,
                    params=request.params,
                )
        except PrivateAddressRefused:
            raise  # security refusal: never mask as a retryable fetch error
        except (httpx.HTTPError, OSError) as exc:
            log.warning("tier3_fetch_failed", url=url, provider=provider.name, error=repr(exc))
            return FetchResult(
                url=url, final_url=url, status_code=0, tier=self.tier, error=repr(exc)
            )
        log.info("tier3_fetched", url=url, provider=provider.name, status=response.status_code)
        return FetchResult(
            url=url,
            final_url=url,  # unblockers don't expose the redirect chain
            status_code=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            body=response.text,
            tier=self.tier,
        )
