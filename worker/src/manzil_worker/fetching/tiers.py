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
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse

import httpx
import structlog
from manzil_shared.config import (
    FETCH_MAX_REDIRECTS,
    FETCH_TARGET_BODY_MAX_BYTES,
    TIER2_MIN_DELAY_SECONDS,
)
from manzil_shared.errors import FetchResponseTooLarge, PrivateAddressRefused

from manzil_worker.fetching.results import FetchResult
from manzil_worker.fetching.ssrf import (
    Resolver,
    is_blocked_ip_literal,
    pin_target,
    resolve_public_host,
    screen_url,
    screen_urls,
)

log = structlog.get_logger()

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


async def read_response_limited(
    response: httpx.Response,
    *,
    url: str,
    layer: str,
    limit_bytes: int,
) -> bytes:
    """Read one HTTP response without ever retaining more than ``limit_bytes``.

    Content-Length is only an optimization — chunked and dishonest responses are
    still stopped at the first over-limit chunk.  Callers decode the returned
    bytes exactly once after the response stream has closed.
    """
    content_length = response.headers.get("content-length")
    try:
        declared = int(content_length) if content_length is not None else None
    except ValueError:
        declared = None
    if declared is not None and declared > limit_bytes:
        raise FetchResponseTooLarge(
            url, layer=layer, observed_bytes=declared, limit_bytes=limit_bytes
        )

    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > limit_bytes:
            raise FetchResponseTooLarge(
                url, layer=layer, observed_bytes=total, limit_bytes=limit_bytes
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def read_raw_response_limited(
    response: httpx.Response,
    *,
    url: str,
    layer: str,
    limit_bytes: int,
) -> bytes:
    """Bound carrier bytes without invoking httpx content decoders.

    Managed unblockers occasionally send a body whose ``Content-Encoding`` is
    stale or malformed. Their adapter must inspect the wire bytes itself;
    ``aiter_bytes`` would raise before it can decide whether the bytes are an
    uncompressed provider envelope with a bad header.
    """
    content_length = response.headers.get("content-length")
    try:
        declared = int(content_length) if content_length is not None else None
    except ValueError:
        declared = None
    if declared is not None and declared > limit_bytes:
        raise FetchResponseTooLarge(
            url, layer=layer, observed_bytes=declared, limit_bytes=limit_bytes
        )

    # MockTransport (and a few custom test transports) hand httpx a response
    # with preloaded content. It is already raw at that boundary; aiter_raw
    # correctly refuses a second stream iteration, so use the retained bytes.
    if response.is_stream_consumed:
        data = getattr(response, "_content", None)
        if not isinstance(data, bytes):
            # This is only a compatibility path for preloaded responses. A
            # normal streamed response always takes the raw iterator below.
            data = response.content
        if len(data) > limit_bytes:
            raise FetchResponseTooLarge(
                url, layer=layer, observed_bytes=len(data), limit_bytes=limit_bytes
            )
        return data

    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_raw():
        total += len(chunk)
        if total > limit_bytes:
            raise FetchResponseTooLarge(
                url, layer=layer, observed_bytes=total, limit_bytes=limit_bytes
            )
        chunks.append(chunk)
    return b"".join(chunks)


def decode_response_body(data: bytes, response: httpx.Response) -> str:
    """Decode bounded page bytes once, with a safe fallback for bad headers."""
    encoding = response.encoding or "utf-8"
    try:
        return data.decode(encoding, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def site_domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


class Fetcher(Protocol):
    tier: int

    async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult: ...


class Tier1Fetcher:
    """Plain HTTP with sane headers.

    SSRF discipline (§16): redirects are followed manually
    (``follow_redirects=False``) so the screen re-runs on every hop, and each hop
    connects to the *vetted IP* (``pin_target``) — closing the DNS-rebinding TOCTOU
    that a re-resolve-only check leaves open (see ``ssrf`` module docstring). A
    public URL that 302s at an internal host is refused at the hop, not fetched.

    Error taxonomy: ``PrivateAddressRefused`` (a security refusal) propagates — so
    `fetch_page` surfaces it as a tool error and a submission fails the job cleanly.
    A resolver/network failure (``OSError``/``gaierror`` on NXDOMAIN or transient
    DNS, or ``httpx.HTTPError``) becomes a ``FetchResult`` with ``status_code=0`` so
    the ladder classifies it ERROR → ``StageRetryable`` (retry with backoff),
    preserving pre-guard behavior for dead/flaky hosts."""

    tier = 1

    def __init__(
        self,
        timeout: float = 20.0,
        *,
        resolver: Resolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,  # injected by tests
    ) -> None:
        self._timeout = timeout
        self._resolver = resolver  # None → real getaddrinfo; tests inject a fake
        self._transport = transport

    async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
        current = url
        try:
            async with httpx.AsyncClient(
                headers=_HEADERS,
                follow_redirects=False,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                for _ in range(FETCH_MAX_REDIRECTS + 1):
                    # Screen scheme + literal host + resolved IPs BEFORE connecting.
                    # Raises PrivateAddressRefused (propagates past the handlers
                    # below — a refusal must never masquerade as a retryable error).
                    addresses = await screen_url(current, resolver=self._resolver)
                    # Dial the screened IP; keep the hostname for Host/SNI/cert.
                    pinned, host_header, sni = pin_target(current, addresses[0])
                    async with client.stream(
                        "GET",
                        pinned,
                        headers={"Host": host_header},
                        extensions={"sni_hostname": sni},
                    ) as response:
                        if not response.is_redirect or not response.has_redirect_location:
                            body = decode_response_body(
                                await read_response_limited(
                                    response,
                                    url=current,
                                    layer="target response",
                                    limit_bytes=FETCH_TARGET_BODY_MAX_BYTES,
                                ),
                                response,
                            )
                            return FetchResult(
                                url=url,
                                final_url=current,  # hostname form, not the pinned IP
                                status_code=response.status_code,
                                headers={k.lower(): v for k, v in response.headers.items()},
                                body=body,
                                tier=self.tier,
                            )
                        # Relative targets resolve against the current URL.
                        current = urljoin(current, response.headers["location"])
        except PrivateAddressRefused:
            raise  # security refusal: never mask as a retryable fetch error
        except (httpx.HTTPError, OSError) as exc:
            return FetchResult(
                url=url, final_url=current, status_code=0, tier=self.tier, error=repr(exc)
            )
        # Fell out of the loop: more than FETCH_MAX_REDIRECTS hops — a clean fetch
        # error (a redirect chase, not a security refusal).
        return FetchResult(
            url=url,
            final_url=current,
            status_code=0,
            tier=self.tier,
            error=f"too many redirects (> {FETCH_MAX_REDIRECTS})",
        )


class Tier2Fetcher:
    """Headless Chromium via Playwright; per-domain rate-limited. Playwright is
    imported lazily so environments without the browser can still use tier 1."""

    tier = 2

    def __init__(self, timeout: float = 45.0, *, resolver: Resolver | None = None) -> None:
        self._timeout = timeout
        self._resolver = resolver
        self._last_fetch: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _route_guard(self) -> Callable[[Any], Awaitable[None]]:
        """Playwright route handler enforcing the SSRF screen inside the browser.

        Scope (proportionate, per §16): (1) EVERY request whose host is a non-global
        IP *literal* is aborted — cheap, no DNS, stops a page (or any subresource)
        fetching ``http://169.254.169.254`` directly; this is the live-valuable
        subresource protection. (2) Main-frame document navigations are
        DNS-re-screened and aborted if non-global — but Playwright only invokes this
        handler for the *initial* navigation and for client-initiated (JS/meta)
        navigations. It does NOT re-invoke the handler on server-side 3xx redirects:
        the browser follows those internally, so this branch never sees them.
        Server-redirect chains are therefore covered separately by the post-load
        full-chain screen in ``fetch`` (which walks ``response.request.redirected_from``
        and screens every hop). Subresource *hostname* DNS resolution is intentionally
        NOT done — it is optional hardening that would add a lookup per asset."""

        async def guard(route: Any) -> None:
            request = route.request
            if is_blocked_ip_literal(request.url):
                await route.abort()
                return
            is_main_frame_nav = (
                request.is_navigation_request() and request.frame.parent_frame is None
            )
            if is_main_frame_nav:
                host = urlparse(request.url).hostname
                if host is not None:
                    try:
                        await resolve_public_host(host, resolver=self._resolver)
                    except PrivateAddressRefused:
                        await route.abort()
                        return
            await route.continue_()

        return guard

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
            # Pre-navigation screen (§16): refuse before launching a browser at all.
            # PrivateAddressRefused propagates past both handlers below (a refusal is
            # never a retryable fetch error); a DNS OSError is caught → retryable.
            await screen_url(url, resolver=self._resolver)
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(
                        user_agent=_HEADERS["User-Agent"],
                        locale="en-US",
                        timezone_id="America/Detroit",
                        viewport={"width": 1440, "height": 900},
                    )
                    await context.route("**/*", self._route_guard())
                    page = await context.new_page()
                    response = await page.goto(
                        url, timeout=self._timeout * 1000, wait_until="domcontentloaded"
                    )
                    # Backstop: screen the FULL server-redirect chain, not just the
                    # landing URL. Playwright follows server 3xx internally without
                    # re-invoking the route guard, so a ``public → private(reachable)
                    # → public`` chain would transit a private host while ``page.url``
                    # (the final URL) screens clean. Walk ``redirected_from`` back from
                    # the final request to collect every intermediate hop, plus
                    # ``page.url`` (the actual landed URL, which may differ after client
                    # JS). Screen every distinct URL; any private hop raises
                    # PrivateAddressRefused and the body is never read.
                    chain: list[str] = []
                    if response is not None:
                        req: Any = response.request
                        while req is not None:
                            chain.append(req.url)
                            req = req.redirected_from
                    chain.append(page.url)
                    await screen_urls(chain, resolver=self._resolver)
                    await page.wait_for_timeout(1500)  # settle JS-rendered content
                    body = await page.content()
                    if len(body.encode("utf-8")) > FETCH_TARGET_BODY_MAX_BYTES:
                        raise FetchResponseTooLarge(
                            url,
                            layer="rendered target body",
                            observed_bytes=len(body.encode("utf-8")),
                            limit_bytes=FETCH_TARGET_BODY_MAX_BYTES,
                        )
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
        except PrivateAddressRefused:
            raise  # security refusal: never mask as a retryable fetch error
        except (PlaywrightError, OSError) as exc:
            log.warning("tier2_fetch_failed", url=url, error=str(exc))
            return FetchResult(
                url=url, final_url=url, status_code=0, tier=self.tier, error=repr(exc)
            )
