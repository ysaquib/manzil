"""Tier 3 — managed unblocker (DESIGN §10.7, §20 2026-07-07, §20 2026-08-11).

Fallback, never default: the ladder only reaches tier 3 after tiers 1-2
classify shell/blocked. The provider is a swappable adapter chosen by
`MANZIL_TIER3_PROVIDER` (default `brightdata`); free plans only — paid
escalation is a new §20 decision, not an env change.

Changing provider = set `MANZIL_TIER3_PROVIDER` + that provider's env vars.
Adding a provider = one `_Provider` entry in `PROVIDERS` (request builder,
response unwrapper, required env) ; nothing outside this module changes.

**Two response layers, never conflated.** A managed unblocker answers on its
own API before the target answers on the page's. `unwrap` separates them:

- a target response (however unhappy — 403, 404, a captcha wall) becomes a
  `FetchResult` carrying *the target's* status and headers, and flows through
  the same classifier/cleaner as any other tier;
- a rejection of our own request (unknown zone, bad key, suspended account,
  exhausted plan) raises `FetchProviderError`, because no target was ever
  contacted and reporting its URL with the provider's status is a lie that
  costs an operator an afternoon (§20 2026-08-11).

Bright Data is therefore asked for `format: "json"` — the enveloped form,
`{status, headers, body}` — rather than `raw`. Raw returns the page bytes with
no way to tell whose status the HTTP layer is carrying.
"""

from __future__ import annotations

import gzip
import json
import zlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from manzil_shared.config import (
    FETCH_PROVIDER_RESPONSE_MAX_BYTES,
    FETCH_TARGET_BODY_MAX_BYTES,
    TIER3_TIMEOUT_SECONDS,
)
from manzil_shared.errors import FetchProviderError, FetchResponseTooLarge, PrivateAddressRefused

from manzil_worker.costs import record_fetch
from manzil_worker.fetching.results import FetchResult
from manzil_worker.fetching.ssrf import Resolver, screen_url
from manzil_worker.fetching.tiers import read_raw_response_limited

if TYPE_CHECKING:
    from collections.abc import Callable

import os

log = structlog.get_logger()

# How much of a provider's rejection body reaches the log and the job error.
# Enough to read the reason; short enough that a vendor HTML error page cannot
# flood a job row.
PROVIDER_ERROR_MAX_CHARS = 400

# Provider-API statuses that mean *the request*, not the target, was refused.
# Everything here is deterministic — the same call will be refused again — so
# FETCH fails fatally rather than paying for three more identical answers.
_FATAL_PROVIDER_STATUSES = frozenset({400, 401, 402, 403, 404, 422})


class _ProviderDecodeError(Exception):
    """A carrier response arrived but could not be safely decoded."""

    def __init__(self, *, provider: str, encoding: str, size: int, error: Exception) -> None:
        super().__init__(f"{provider} carrier decoding failed for {encoding!r}: {error}")
        self.provider = provider
        self.encoding = encoding
        self.size = size


@dataclass(frozen=True)
class _Request:
    method: str
    url: str
    headers: dict[str, str]
    json: dict[str, Any] | None = None
    params: dict[str, str] | None = None


@dataclass(frozen=True)
class _Target:
    """The target page's own response, unwrapped from the provider's envelope."""

    status_code: int
    headers: dict[str, str]
    body: str


def _target_within_limit(target: _Target, *, url: str) -> _Target:
    """Reject an oversized complete target before it reaches the HTML cleaner."""
    size = len(target.body.encode("utf-8"))
    if size > FETCH_TARGET_BODY_MAX_BYTES:
        raise FetchResponseTooLarge(
            url,
            layer="unwrapped target body",
            observed_bytes=size,
            limit_bytes=FETCH_TARGET_BODY_MAX_BYTES,
        )
    return target


@dataclass(frozen=True)
class _Provider:
    name: str
    # Each inner tuple is one required setting; any one of its names may carry
    # the value (aliases). An env var set to the empty string does not count —
    # a blank value in a deploy dashboard is a missing value, not a default.
    required_env: tuple[tuple[str, ...], ...]
    build: Callable[[str], _Request]  # target url -> API request
    # provider API response -> the target's response, or None when the provider
    # refused our request and never contacted the target.
    unwrap: Callable[[httpx.Response], _Target | None]


def env_value(*names: str) -> str | None:
    """First of `names` with a non-empty value. Empty-string env vars are the
    deploy-dashboard shape of "unset" and must not defeat a default or pass a
    configuration check (§20 2026-08-11)."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


# Bright Data calls this the *zone*: the entry under Proxies & Scraping
# Infrastructure the request is billed and routed through. It is NOT the name
# of the API key, which the control panel displays alongside it and which may
# differ per environment — sending the key's name yields HTTP 400 for every
# request (the 2026-08-11 production incident). `BRIGHTDATA_KEY_NAME` is
# accepted as an alias because that is what the panel labels the field some
# accounts read it from; both must hold the zone name.
_BRIGHTDATA_ZONE_VARS = ("BRIGHTDATA_ZONE", "BRIGHTDATA_KEY_NAME")


def _brightdata(url: str) -> _Request:
    # Web Unlocker API: POST /request with the zone name. `format=json` returns
    # the enveloped `{status, headers, body}` so the target's status survives
    # separately from the API's own (see the module docstring).
    key = env_value("BRIGHTDATA_API_KEY")
    zone = env_value(*_BRIGHTDATA_ZONE_VARS)
    if not key or not zone:
        missing = " and ".join(
            name
            for name, present in (("BRIGHTDATA_API_KEY", key), (_BRIGHTDATA_ZONE_VARS[0], zone))
            if not present
        )
        raise FetchProviderError(
            "brightdata",
            status=None,
            reason=f"{missing} is not set in this process's environment",
            retryable=False,
            remedy=(
                "set it to the Web Unlocker **zone** name from the Bright Data control "
                "panel (not the API key's name)"
            ),
        )
    return _Request(
        method="POST",
        url="https://api.brightdata.com/request",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
        },
        json={"zone": zone, "url": url, "format": "json"},
    )


def _unwrap_brightdata(response: httpx.Response) -> _Target | None:
    """Envelope in → target out; anything else is the provider talking.

    Tolerant on purpose: a 200 whose body is not the envelope (an older account
    shape, a `format` the zone overrides) is treated as the page itself rather
    than as a rejection, so an unexpected vendor shape degrades to the
    pre-envelope behavior instead of failing the run.
    """
    try:
        envelope = response.json()
    except (json.JSONDecodeError, ValueError):
        envelope = None
    if isinstance(envelope, dict) and isinstance(envelope.get("status"), int):
        headers = envelope.get("headers")
        headers = headers if isinstance(headers, dict) else {}
        return _Target(
            status_code=int(envelope["status"]),
            headers={str(key).lower(): str(value) for key, value in headers.items()},
            body=str(envelope.get("body") or ""),
        )
    if response.status_code == 200:
        return _Target(
            status_code=200,
            headers={k.lower(): v for k, v in response.headers.items()},
            body=response.text,
        )
    return None


def _scrapingbee(url: str) -> _Request:
    key = env_value("SCRAPINGBEE_API_KEY")
    if not key:
        raise FetchProviderError(
            "scrapingbee",
            status=None,
            reason="SCRAPINGBEE_API_KEY is not set in this process's environment",
            retryable=False,
        )
    return _Request(
        method="GET",
        url="https://app.scrapingbee.com/api/v1/",
        headers={"Accept-Encoding": "identity"},
        params={"api_key": key, "url": url, "render_js": "true"},
    )


def _unwrap_scrapingbee(response: httpx.Response) -> _Target | None:
    """ScrapingBee has no envelope — it returns the page and mirrors the
    target's status — so only its documented account-level rejections (401 bad
    key, 402 out of credits) can be told apart from a target response."""
    if response.status_code in (401, 402):
        return None
    return _Target(
        status_code=response.status_code,
        headers={k.lower(): v for k, v in response.headers.items()},
        body=response.text,
    )


PROVIDERS: dict[str, _Provider] = {
    "brightdata": _Provider(
        "brightdata",
        (("BRIGHTDATA_API_KEY",), _BRIGHTDATA_ZONE_VARS),
        _brightdata,
        _unwrap_brightdata,
    ),
    "scrapingbee": _Provider(
        "scrapingbee",
        (("SCRAPINGBEE_API_KEY",),),
        _scrapingbee,
        _unwrap_scrapingbee,
    ),
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


def tier3_fallback_provider(primary: _Provider) -> _Provider | None:
    """Configured secondary provider for carrier decode failures only.

    The fallback is intentionally opt-in: a valid primary response (including a
    blocked target page) must not spend a second vendor credit. An invalid name
    remains an operator-visible configuration error instead of silently
    disabling recovery.
    """
    name = os.environ.get("MANZIL_TIER3_FALLBACK_PROVIDER", "").strip()
    if not name:
        return None
    try:
        fallback = PROVIDERS[name]
    except KeyError:
        raise KeyError(
            f"MANZIL_TIER3_FALLBACK_PROVIDER={name!r}: known providers are {sorted(PROVIDERS)}"
        ) from None
    if fallback.name == primary.name:
        log.warning("tier3_fallback_unavailable", provider=primary.name, reason="same_as_primary")
        return None
    missing = missing_provider_env(fallback)
    if missing:
        log.warning(
            "tier3_fallback_unavailable",
            provider=fallback.name,
            reason="missing_configuration",
            missing=missing,
        )
        return None
    return fallback


def missing_provider_env(provider: _Provider) -> list[str]:
    """Which of `provider`'s required settings this environment does not carry,
    named by their primary env var."""
    return [names[0] for names in provider.required_env if env_value(*names) is None]


def provider_configured(name: str) -> bool:
    """Is `name` fully configured here? Every required setting, not just the key
    — a Web Unlocker with no zone is a 400 per request, not a working tier 3."""
    provider = PROVIDERS.get(name)
    return provider is not None and not missing_provider_env(provider)


def tier3_configured() -> str | None:
    """Provider name if it is fully configured, else None (tier 3 stays off the
    ladder — exactly the pre-tier-3 behavior).

    A partially configured provider is the dangerous case: it looks enabled,
    joins the ladder, and then refuses every request. It is treated as absent
    and said out loud, because a silent tier-3-shaped hole is how the
    2026-08-11 incident stayed invisible for nine days.
    """
    provider = tier3_provider()
    missing = missing_provider_env(provider)
    if not missing:
        return provider.name
    if len(missing) < len(provider.required_env):
        log.warning(
            "tier3_partially_configured",
            provider=provider.name,
            missing=missing,
            effect="tier 3 is off the ladder until every setting is present",
        )
    return None


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

    @staticmethod
    def _decode_carrier_body(response: httpx.Response, data: bytes, provider: _Provider) -> bytes:
        """Decode a provider envelope exactly once, tolerating a lying header.

        ``Accept-Encoding: identity`` is the normal path. If a vendor still
        labels already-plain JSON/HTML as compressed, retain the plainly textual
        bytes rather than treating the target as unavailable. Truly malformed or
        unsupported encodings take the bounded retry/failover path.
        """
        encoding = response.headers.get("content-encoding", "identity").lower().strip()
        if not encoding or encoding == "identity":
            return data
        try:
            if encoding == "gzip":
                return gzip.decompress(data)
            if encoding == "deflate":
                try:
                    return zlib.decompress(data)
                except zlib.error:
                    return zlib.decompress(data, -zlib.MAX_WBITS)
            raise ValueError(f"unsupported content encoding {encoding!r}")
        except (OSError, ValueError, zlib.error) as error:
            # Bright Data's JSON envelope and an HTML target have unmistakable
            # UTF-8 prefixes. A false compression label must not make a usable
            # source disappear, which is the production failure this repairs.
            if data.lstrip().startswith((b"{", b"[", b"<")):
                log.warning(
                    "tier3_encoding_header_ignored",
                    provider=provider.name,
                    api_status=response.status_code,
                    content_encoding=encoding,
                    response_bytes=len(data),
                )
                return data
            raise _ProviderDecodeError(
                provider=provider.name,
                encoding=encoding,
                size=len(data),
                error=error,
            ) from error

    async def _fetch_from_provider(self, provider: _Provider, url: str) -> FetchResult:
        request = provider.build(url)  # may raise FetchProviderError (config)
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client,
                client.stream(
                    request.method,
                    request.url,
                    headers=request.headers,
                    json=request.json,
                    params=request.params,
                ) as streamed,
            ):
                data = await read_raw_response_limited(
                    streamed,
                    url=url,
                    layer="provider response",
                    limit_bytes=FETCH_PROVIDER_RESPONSE_MAX_BYTES,
                )
                try:
                    decoded = self._decode_carrier_body(streamed, data, provider)
                except _ProviderDecodeError:
                    # A carrier response normally represents a vendor request
                    # that consumed credit. The malformed body prevents target
                    # classification, but must not erase that observed spend.
                    if streamed.status_code < 400:
                        record_fetch(provider.name)
                    raise
                headers = {
                    key: value
                    for key, value in streamed.headers.items()
                    if key.lower() not in {"content-encoding", "content-length"}
                }
                response = httpx.Response(
                    streamed.status_code,
                    headers=headers,
                    content=decoded,
                    request=streamed.request,
                )
        except (FetchResponseTooLarge, FetchProviderError, _ProviderDecodeError):
            raise
        except (httpx.HTTPError, OSError) as exc:
            log.warning("tier3_fetch_failed", url=url, provider=provider.name, error=repr(exc))
            return FetchResult(
                url=url,
                final_url=url,
                status_code=0,
                tier=self.tier,
                provider=provider.name,
                error=repr(exc),
            )

        target = provider.unwrap(response)
        if target is None:
            reason = response.text.strip()[:PROVIDER_ERROR_MAX_CHARS] or "no reason given"
            log.error(
                "tier3_provider_rejected",
                url=url,
                provider=provider.name,
                api_status=response.status_code,
                reason=reason,
            )
            raise FetchProviderError(
                provider.name,
                status=response.status_code,
                reason=reason,
                retryable=response.status_code not in _FATAL_PROVIDER_STATUSES,
                remedy=(
                    "check the zone name, API key, and account balance in the provider's "
                    "control panel"
                    if response.status_code in _FATAL_PROVIDER_STATUSES
                    else None
                ),
            )

        target = _target_within_limit(target, url=url)
        record_fetch(provider.name)
        log.info(
            "tier3_fetched",
            url=url,
            provider=provider.name,
            api_status=response.status_code,
            status=target.status_code,
        )
        return FetchResult(
            url=url,
            final_url=url,
            status_code=target.status_code,
            headers=target.headers,
            body=target.body,
            tier=self.tier,
            provider=provider.name,
        )

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
        except (PrivateAddressRefused, FetchProviderError):
            raise  # a refusal and a misconfiguration are never retryable fetch errors
        except (httpx.HTTPError, OSError) as exc:
            log.warning("tier3_fetch_failed", url=url, provider=provider.name, error=repr(exc))
            return FetchResult(
                url=url,
                final_url=url,
                status_code=0,
                tier=self.tier,
                provider=provider.name,
                error=repr(exc),
            )

        for attempt in (1, 2):
            try:
                return await self._fetch_from_provider(provider, url)
            except _ProviderDecodeError as error:
                log.warning(
                    "tier3_carrier_decode_failed",
                    url=url,
                    provider=provider.name,
                    attempt=attempt,
                    content_encoding=error.encoding,
                    response_bytes=error.size,
                )
                if attempt == 1:
                    continue
                fallback = tier3_fallback_provider(provider)
                if fallback is None:
                    return FetchResult(
                        url=url,
                        final_url=url,
                        status_code=0,
                        tier=self.tier,
                        provider=provider.name,
                        error=str(error),
                    )
                log.info(
                    "tier3_provider_failover",
                    url=url,
                    provider=provider.name,
                    fallback_provider=fallback.name,
                )
                try:
                    return await self._fetch_from_provider(fallback, url)
                except _ProviderDecodeError as fallback_error:
                    log.warning(
                        "tier3_carrier_decode_failed",
                        url=url,
                        provider=fallback.name,
                        attempt=1,
                        content_encoding=fallback_error.encoding,
                        response_bytes=fallback_error.size,
                    )
                    return FetchResult(
                        url=url,
                        final_url=url,
                        status_code=0,
                        tier=self.tier,
                        provider=fallback.name,
                        error=str(fallback_error),
                    )
        raise AssertionError("unreachable")
