"""SSRF guard (§16, the Wave-B hard gate): the DNS-resolving fetch-layer policy
that closes the gap VALIDATE_URL's literal-only screen leaves open — a public
hostname that resolves to a private IP, and redirect chains that end at an
internal host. No live DNS or HTTP: a fake resolver seam plays getaddrinfo and
httpx.MockTransport plays the network."""

from __future__ import annotations

import asyncio
import ipaddress
import json

import httpx
import pytest
from manzil_shared.errors import PrivateAddressRefused
from manzil_worker.fetching.registry import InMemoryRegistry
from manzil_worker.fetching.ssrf import (
    is_blocked_ip_literal,
    is_private_literal,
    resolve_public_host,
    screen_url,
    screen_urls,
)
from manzil_worker.fetching.tiers import Tier1Fetcher
from manzil_worker.llm.tools import ToolContext, fetch_page, tool_context

PUBLIC_V4 = "8.8.8.8"
PUBLIC_V6 = "2606:4700:4700::1111"


def resolver_for(mapping: dict[str, list[str]]):
    """A fake resolver: host -> IP strings. Unknown hosts raise like NXDOMAIN."""

    async def _resolve(host: str) -> list[str]:
        try:
            return mapping[host]
        except KeyError:  # pragma: no cover - test hygiene
            raise OSError(f"no fake record for {host!r}") from None

    return _resolve


def one(ip: str):
    return resolver_for({"host.example": [ip]})


# ── the _is_global / literal predicates ──────────────────────────────────────


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.7",
        "172.16.5.5",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",  # cloud metadata endpoint
        "0.0.0.0",
        "::1",
        "fc00::1",  # IPv6 unique-local
        "fe80::1",  # IPv6 link-local
        "::ffff:10.0.0.1",  # IPv4-mapped private
        "64:ff9b::a9fe:a9fe",  # NAT64 (64:ff9b::/96) wrapping 169.254.169.254
        "2002:0a00:0001::",  # 6to4 (2002::/16) wrapping 10.0.0.1
    ],
)
async def test_resolve_refuses_every_non_global_family(ip: str) -> None:
    with pytest.raises(PrivateAddressRefused):
        await resolve_public_host("host.example", resolver=one(ip))


@pytest.mark.parametrize("ip", [PUBLIC_V4, PUBLIC_V6, "93.184.216.34", "::ffff:8.8.8.8"])
async def test_resolve_allows_genuine_public_addresses(ip: str) -> None:
    resolved = await resolve_public_host("host.example", resolver=one(ip))
    assert len(resolved) == 1


async def test_mixed_resolution_is_refused() -> None:
    """One private record among public ones is enough to refuse — an attacker
    only needs a single poisoned answer."""
    with pytest.raises(PrivateAddressRefused):
        await resolve_public_host("host.example", resolver=one_of([PUBLIC_V4, "10.0.0.1"]))


async def test_empty_resolution_is_refused_never_passed() -> None:
    with pytest.raises(PrivateAddressRefused):
        await resolve_public_host("host.example", resolver=one_of([]))


async def test_resolver_error_propagates_as_ordinary_failure() -> None:
    """NXDOMAIN (resolver raises) is a normal fetch failure, not a refusal — we
    just never turn 'couldn't check' into 'allowed'."""
    with pytest.raises(OSError):
        await resolve_public_host("nope.example", resolver=resolver_for({}))


def one_of(ips: list[str]):
    return resolver_for({"host.example": ips})


@pytest.mark.parametrize(
    ("host", "private"),
    [
        ("localhost", True),
        ("supabase.local", True),
        ("127.0.0.1", True),
        ("10.0.0.7", True),
        ("::1", True),
        ("example.com", False),  # a name — DNS decides, not the literal screen
        ("8.8.8.8", False),
    ],
)
def test_is_private_literal(host: str, private: bool) -> None:
    assert is_private_literal(host) is private


@pytest.mark.parametrize(
    ("url", "blocked"),
    [
        ("http://169.254.169.254/latest/meta-data/", True),
        ("http://10.0.0.1/x", True),
        ("http://[::1]/x", True),
        ("http://[fc00::1]/x", True),
        ("https://8.8.8.8/x", False),
        ("https://example.com/x", False),  # hostname, not an IP literal
    ],
)
def test_is_blocked_ip_literal_route_predicate(url: str, blocked: bool) -> None:
    assert is_blocked_ip_literal(url) is blocked


async def test_screen_url_rejects_non_http_scheme() -> None:
    with pytest.raises(PrivateAddressRefused):
        await screen_url("file:///etc/passwd", resolver=one(PUBLIC_V4))


# ── screen_urls: the CI-testable seam for tier 2's redirect-chain screen ──────
# Models the tier-2 threat without a browser: a fake resolver plays getaddrinfo
# for each hop host, so an intermediate (not just final) private hop is provable.


def resolver_by_host(mapping: dict[str, list[str]]):
    """Fake resolver keyed by hostname (each hop URL has a distinct host)."""
    return resolver_for(mapping)


async def test_screen_urls_passes_when_every_hop_is_global() -> None:
    resolver = resolver_by_host(
        {"a.example": [PUBLIC_V4], "b.example": [PUBLIC_V6], "c.example": [PUBLIC_V4]}
    )
    # No raise == pass.
    await screen_urls(
        ["https://a.example/1", "https://b.example/2", "https://c.example/3"],
        resolver=resolver,
    )


async def test_screen_urls_refuses_a_private_MIDDLE_hop() -> None:
    """The intermediate hop — not the final landing URL — resolves private. This is
    the exact ``public → private(reachable) → public`` chain the tier-2 fix targets:
    the final URL is clean, but the middle host must still refuse."""
    resolver = resolver_by_host(
        {
            "start.example": [PUBLIC_V4],
            "internal.example": ["10.0.0.9"],  # the transited private hop
            "landing.example": [PUBLIC_V4],  # final URL screens clean on its own
        }
    )
    with pytest.raises(PrivateAddressRefused):
        await screen_urls(
            [
                "https://start.example/a",
                "https://internal.example/b",
                "https://landing.example/c",
            ],
            resolver=resolver,
        )


async def test_screen_urls_refuses_a_private_ip_literal_hop() -> None:
    resolver = resolver_by_host({"start.example": [PUBLIC_V4]})
    with pytest.raises(PrivateAddressRefused):
        await screen_urls(
            ["https://start.example/a", "http://169.254.169.254/latest/meta-data/"],
            resolver=resolver,
        )


async def test_screen_urls_refuses_a_disallowed_scheme_hop() -> None:
    resolver = resolver_by_host({"start.example": [PUBLIC_V4]})
    with pytest.raises(PrivateAddressRefused):
        await screen_urls(
            ["https://start.example/a", "file:///etc/passwd"],
            resolver=resolver,
        )


async def test_screen_urls_dedupe_does_not_drop_a_distinct_private_hop() -> None:
    """Dedupe collapses repeated hops but must not let a distinct private hop slip:
    a repeated public host precedes a private one, and the private one still refuses."""
    resolver = resolver_by_host({"pub.example": [PUBLIC_V4], "internal.example": ["192.168.1.5"]})
    with pytest.raises(PrivateAddressRefused):
        await screen_urls(
            [
                "https://pub.example/x",
                "https://pub.example/x",  # duplicate — screened once
                "https://internal.example/y",  # distinct private — must still refuse
            ],
            resolver=resolver,
        )


# ── Tier 1: pre-connect screen + manual redirect discipline ──────────────────


class _RecordingTransport:
    """httpx MockTransport wrapper that records what was actually dialed. Because
    tier 1 pins to the vetted IP, ``dialed_hosts`` are IP literals (the socket
    target) and ``host_headers`` carry the original authority — so a test can prove
    the connection went to the screened IP and never to a rebound private one."""

    def __init__(self, handler):
        self.dialed_urls: list[str] = []
        self.dialed_hosts: list[str] = []
        self.host_headers: list[str | None] = []
        self._mock = httpx.MockTransport(self._wrapped(handler))

    def _wrapped(self, handler):
        def inner(request: httpx.Request) -> httpx.Response:
            self.dialed_urls.append(str(request.url))
            self.dialed_hosts.append(request.url.host)
            self.host_headers.append(request.headers.get("host"))
            return handler(request)

        return inner


class _CountingResolver:
    """Returns successive answers; records call count. Models a rebinding DNS whose
    later answers differ from the first."""

    def __init__(self, answers: list[list[str]]) -> None:
        self._answers = answers
        self.calls = 0

    async def __call__(self, host: str) -> list[str]:
        answer = self._answers[min(self.calls, len(self._answers) - 1)]
        self.calls += 1
        return answer


def one_host_public(host: str):
    return resolver_for({host: [PUBLIC_V4]})


async def test_public_host_resolving_private_refused_before_connect() -> None:
    rec = _RecordingTransport(lambda r: httpx.Response(200, text="<html>ok</html>"))
    fetcher = Tier1Fetcher(resolver=one("10.0.0.5"), transport=rec._mock)
    with pytest.raises(PrivateAddressRefused):
        await fetcher.fetch("https://host.example/listing")
    assert rec.dialed_urls == []  # never connected


async def test_tier1_pins_to_vetted_ip_preserving_host_header() -> None:
    """The socket dials the screened IP; the original hostname rides the Host
    header (and, in production, TLS SNI + cert verification)."""
    rec = _RecordingTransport(lambda r: httpx.Response(200, text="<html>ok</html>"))
    fetcher = Tier1Fetcher(resolver=one(PUBLIC_V4), transport=rec._mock)
    result = await fetcher.fetch("https://host.example/listing")
    assert result.status_code == 200
    assert result.final_url == "https://host.example/listing"  # hostname form, not IP
    assert rec.dialed_hosts == [PUBLIC_V4]  # connected to the vetted IP
    assert rec.host_headers == ["host.example"]  # authority preserved


async def test_rebinding_connect_goes_to_vetted_ip_never_the_private_flip() -> None:
    """FIX 2: a resolver that would answer public-then-private cannot land the
    connect on the private IP — tier 1 resolves once, pins the screened IP, and
    httpx does no second resolution."""
    resolver = _CountingResolver([[PUBLIC_V4], ["10.0.0.9"]])
    rec = _RecordingTransport(lambda r: httpx.Response(200, text="<html>ok</html>"))
    fetcher = Tier1Fetcher(resolver=resolver, transport=rec._mock)
    result = await fetcher.fetch("https://rebind.example/x")
    assert result.status_code == 200
    assert resolver.calls == 1  # one resolution — no separate connect-time lookup
    assert rec.dialed_hosts == [PUBLIC_V4]  # the vetted IP
    assert "10.0.0.9" not in rec.dialed_hosts  # the rebound private IP never dialed


async def test_public_redirects_to_private_refused_at_the_hop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("host") == "public.example":
            return httpx.Response(302, headers={"location": "https://internal.example/secret"})
        return httpx.Response(200, text="should never get here")

    resolver = resolver_for({"public.example": [PUBLIC_V4], "internal.example": ["10.0.0.9"]})
    rec = _RecordingTransport(handler)
    fetcher = Tier1Fetcher(resolver=resolver, transport=rec._mock)
    with pytest.raises(PrivateAddressRefused):
        await fetcher.fetch("https://public.example/start")
    assert rec.dialed_hosts == [PUBLIC_V4]  # only the public hop connected
    assert "10.0.0.9" not in rec.dialed_hosts  # internal never contacted


async def test_public_redirects_to_public_succeeds() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("host") == "public.example":
            return httpx.Response(302, headers={"location": "https://other.example/final"})
        return httpx.Response(200, text="<html><body>final page</body></html>")

    resolver = resolver_for({"public.example": [PUBLIC_V4], "other.example": [PUBLIC_V6]})
    rec = _RecordingTransport(handler)
    fetcher = Tier1Fetcher(resolver=resolver, transport=rec._mock)
    result = await fetcher.fetch("https://public.example/start")
    assert result.status_code == 200
    assert result.final_url == "https://other.example/final"
    assert "final page" in result.body
    assert len(rec.dialed_hosts) == 2  # both hops dialed, both by vetted IP


async def test_relative_redirect_resolved_against_current_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b"})  # relative
        return httpx.Response(200, text="<html>b</html>")

    rec = _RecordingTransport(handler)
    fetcher = Tier1Fetcher(resolver=one_host_public("public.example"), transport=rec._mock)
    result = await fetcher.fetch("https://public.example/a")
    assert result.status_code == 200
    assert result.final_url == "https://public.example/b"  # relative joined correctly
    assert [u.rsplit("/", 1)[-1] for u in rec.dialed_urls] == ["a", "b"]


async def test_redirect_cap_exceeded_is_a_clean_fetch_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://public.example/loop"})

    from manzil_shared.config import FETCH_MAX_REDIRECTS

    rec = _RecordingTransport(handler)
    fetcher = Tier1Fetcher(resolver=one_host_public("public.example"), transport=rec._mock)
    result = await fetcher.fetch("https://public.example/loop")
    assert result.status_code == 0
    assert result.error is not None and "too many redirects" in result.error
    assert len(rec.dialed_hosts) == FETCH_MAX_REDIRECTS + 1  # capped, not infinite


async def test_gaierror_is_a_retryable_fetch_error_not_an_escape() -> None:
    """FIX 1: a resolver failure (NXDOMAIN / transient DNS = gaierror, an OSError)
    must become a status-0 FetchResult (→ ERROR → StageRetryable), not escape the
    fetcher and hard-fail the job."""

    async def failing_resolver(host: str) -> list[str]:
        import socket

        raise socket.gaierror(socket.EAI_AGAIN, "temporary failure in name resolution")

    rec = _RecordingTransport(lambda r: httpx.Response(200, text="ok"))
    fetcher = Tier1Fetcher(resolver=failing_resolver, transport=rec._mock)
    result = await fetcher.fetch("https://flaky-dns.example/x")
    assert result.status_code == 0
    assert result.error is not None
    assert rec.dialed_urls == []  # never connected (resolution failed first)


def test_pin_target_ipv4() -> None:
    from manzil_worker.fetching.ssrf import pin_target

    pinned, host_header, sni = pin_target(
        "https://example.com/p?q=1", ipaddress.ip_address("8.8.8.8")
    )
    assert pinned == "https://8.8.8.8/p?q=1"
    assert host_header == "example.com"
    assert sni == "example.com"


def test_pin_target_ipv6_and_port_bracket_and_preserve() -> None:
    from manzil_worker.fetching.ssrf import pin_target

    pinned, host_header, sni = pin_target(
        "https://example.com:8443/x", ipaddress.ip_address("2606:4700:4700::1111")
    )
    assert pinned == "https://[2606:4700:4700::1111]:8443/x"
    assert host_header == "example.com:8443"
    assert sni == "example.com"


# ── fetch_page: the model-facing tool surfaces the refusal, does not crash ────


async def test_fetch_page_dns_resolving_private_returns_tool_error() -> None:
    rec = _RecordingTransport(lambda r: httpx.Response(200, text="<html>ok</html>"))
    fetcher = Tier1Fetcher(resolver=one("10.0.0.5"), transport=rec._mock)
    ctx = ToolContext(fetchers={1: fetcher}, registry=InMemoryRegistry())
    with tool_context(ctx):
        result = await fetch_page("https://host.example/anything")
    payload = json.loads(result)
    assert "refused" in payload["error"]
    assert rec.dialed_urls == []  # the model could not steer a connection to the private host


async def test_fetch_page_public_dns_still_fetches() -> None:
    rec = _RecordingTransport(
        lambda r: httpx.Response(200, text="<html><body>a listing page here</body></html>")
    )
    fetcher = Tier1Fetcher(resolver=one("93.184.216.34"), transport=rec._mock)
    ctx = ToolContext(fetchers={1: fetcher}, registry=InMemoryRegistry())
    with tool_context(ctx):
        text = await fetch_page("https://host.example/listing")
    assert isinstance(text, str) and text
    assert rec.dialed_hosts == ["93.184.216.34"]


def test_smoke_asyncio_entrypoint() -> None:
    """A non-async sanity check so the module has at least one sync test even if
    asyncio_mode changes."""
    assert asyncio.run(resolve_public_host("host.example", resolver=one(PUBLIC_V4)))
