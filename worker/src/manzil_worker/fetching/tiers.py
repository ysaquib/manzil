"""Fetch tiers 1-2 (P0-6, DESIGN §10.7).

Tier 1: httpx with sane headers — covers most official complex sites.
Tier 2: Playwright with a realistic fingerprint — JS-rendered but unprotected
pages; slow, polite (per-domain min delay), captures an opportunistic
screenshot when asked (already rendering — the photo is free).
Tier 3 (managed unblocker) is deferred behind the Phase 0 census gate (§19).
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol
from urllib.parse import urlparse

import httpx
import structlog
from manzil_shared.config import TIER2_MIN_DELAY_SECONDS

from manzil_worker.fetching.results import FetchResult

log = structlog.get_logger()

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def site_domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


class Fetcher(Protocol):
    tier: int

    async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult: ...


class Tier1Fetcher:
    """Plain HTTP with sane headers."""

    tier = 1

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout

    async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
        try:
            async with httpx.AsyncClient(
                headers=_HEADERS, follow_redirects=True, timeout=self._timeout
            ) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            return FetchResult(
                url=url, final_url=url, status_code=0, tier=self.tier, error=repr(exc)
            )
        return FetchResult(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            body=response.text,
            tier=self.tier,
        )


class Tier2Fetcher:
    """Headless Chromium via Playwright; per-domain rate-limited. Playwright is
    imported lazily so environments without the browser can still use tier 1."""

    tier = 2

    def __init__(self, timeout: float = 45.0) -> None:
        self._timeout = timeout
        self._last_fetch: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def _be_polite(self, domain: str) -> None:
        async with self._lock:
            elapsed = time.monotonic() - self._last_fetch.get(domain, 0.0)
            wait = TIER2_MIN_DELAY_SECONDS - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_fetch[domain] = time.monotonic()

    async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import async_playwright

        await self._be_polite(site_domain(url))
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(
                        user_agent=_HEADERS["User-Agent"],
                        locale="en-US",
                        timezone_id="America/Detroit",
                        viewport={"width": 1440, "height": 900},
                    )
                    page = await context.new_page()
                    response = await page.goto(
                        url, timeout=self._timeout * 1000, wait_until="domcontentloaded"
                    )
                    await page.wait_for_timeout(1500)  # settle JS-rendered content
                    body = await page.content()
                    screenshot = (
                        await page.screenshot(full_page=True, type="jpeg", quality=70)
                        if capture_screenshot
                        else None
                    )
                    return FetchResult(
                        url=url,
                        final_url=page.url,
                        status_code=response.status if response else 0,
                        headers={k.lower(): v for k, v in (await response.all_headers()).items()}
                        if response
                        else {},
                        body=body,
                        tier=self.tier,
                        screenshot=screenshot,
                    )
                finally:
                    await browser.close()
        except PlaywrightError as exc:
            log.warning("tier2_fetch_failed", url=url, error=str(exc))
            return FetchResult(
                url=url, final_url=url, status_code=0, tier=self.tier, error=repr(exc)
            )
