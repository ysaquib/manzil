"""SSRF policy — the one home for "may we connect to this host?" (§16).

Every fetch path funnels through here. VALIDATE_URL (§10.3) does a deterministic,
zero-network *literal* screen (scheme, an IP-literal that is obviously private);
this module adds the piece that stage deliberately cannot do without a network
call: **resolve the host and refuse if any resolved address is non-global**. A
public hostname that DNS-resolves to an RFC1918 address, to loopback, or to the
cloud metadata endpoint (``169.254.169.254``) is the classic SSRF shape, and once
Phase 3 hands ``fetch_page`` to a model-controlled loop whose context includes
untrusted page text, "steer a fetch at an internal host and read the response"
becomes a realistic prompt-injection outcome.

Resolver seam
-------------
Resolution goes through an injectable ``Resolver`` (host -> list of IP strings);
the default wraps ``asyncio.get_running_loop().getaddrinfo``. Tests inject a fake
resolver so no live DNS happens in CI, and local-dev ergonomics (if ever needed)
use the seam rather than a "permit private hosts" env flag — there is deliberately
no such flag (§16: no blanket bypass).

DNS-rebinding posture (decision, see report + the §20 entry the docs task writes)
---------------------------------------------------------------------------------
Re-resolve-and-screen alone is bypassable by the guard's own named adversary —
someone who controls a hostname's DNS — via classic rebinding: our screen and
httpx's connect do *separate* ``getaddrinfo`` calls, so a low-TTL record that
answers public-then-private lands the connect on the private IP, repeatably, and
for a read/exfil threat one success is the whole win.

So **tier 1 connects to the vetted IP** (``pin_target``): resolve once, screen all
returned addresses, dial a screened IP, and preserve the hostname for Host/SNI/cert
verification. httpx's own connect-time resolution never runs, so the screen and the
connect target are the *same* IP — the TOCTOU window is closed for tier 1. The pin
is re-applied on every redirect hop.

Tier 2 (Chromium) cannot be pinned this way — the browser owns its own DNS/connect.
Its route-guard (abort non-global IP-literal requests; DNS-re-screen main-frame
navigations) plus the ``page.url`` post-load backstop is the accepted best-effort;
the residual rebinding window there is real and requires a manual browser smoke test
before a live loop wires it (recorded as a doc gate).

Tier 3 caveat: tier-3 requests originate from the *provider's* network, so our
internal hosts are unreachable from there and a provider fetching ``169.254...``
would return *its* metadata, not ours. The pre-dispatch screen there is pure
consistency / defense-in-depth, not a load-bearing control (and now assumes the
target also resolves from our network — see the report note).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

from manzil_shared.errors import PrivateAddressRefused

# host -> resolved IP strings. Async so the default can use the event loop's
# threaded getaddrinfo without blocking; fakes just return a list.
Resolver = Callable[[str], Awaitable[list[str]]]

_ALLOWED_SCHEMES = ("http", "https")
_ZERO_NET_V4 = ipaddress.ip_network("0.0.0.0/8")
_UNIQUE_LOCAL_V6 = ipaddress.ip_network("fc00::/7")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


async def _default_resolver(host: str) -> list[str]:
    """Resolve ``host`` to its IP strings via the event loop's getaddrinfo.

    Both address families, so an IPv4-only screen can't be dodged with a AAAA
    record (and vice versa)."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    # sockaddr is (ip, port[, flowinfo, scopeid]); ip may carry a %zone suffix.
    return [str(info[4][0]) for info in infos]


def _is_global(ip: IPAddress) -> bool:
    """True only for addresses safe to fetch from *our* network.

    Deliberately does not trust ``ip.is_global`` alone — across Python versions it
    inconsistently classifies carrier-grade/edge ranges — so we combine it with an
    explicit deny set. Any explicit hit, or ``not is_global``, means *reject*.
    IPv4-mapped IPv6 (``::ffff:a.b.c.d``) is unwrapped and judged on the mapped v4
    so ``::ffff:10.0.0.1`` cannot smuggle a private address past the check."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # incl. 169.254.0.0/16 — cloud metadata
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False
    if isinstance(ip, ipaddress.IPv4Address) and ip in _ZERO_NET_V4:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip in _UNIQUE_LOCAL_V6:
        return False
    return bool(ip.is_global)


def _parse_ip(addr: str) -> IPAddress:
    """Parse a resolver-returned address, tolerating an IPv6 ``%zone`` suffix."""
    return ipaddress.ip_address(addr.split("%", 1)[0])


def is_private_literal(host: str) -> bool:
    """Literal-only screen (no DNS): the deterministic part VALIDATE_URL also does.
    ``localhost``/``*.local`` and any non-global IP *literal* are private."""
    if host == "localhost" or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # a name, not a literal — DNS decides (resolve_public_host)
    return not _is_global(ip)


def is_blocked_ip_literal(url: str) -> bool:
    """Predicate for Playwright route interception: True when ``url``'s host is an
    IP *literal* that is non-global. Pure and synchronous (no DNS) so it is safe to
    run on every intercepted subresource request and is directly unit-testable."""
    host = urlsplit(url).hostname
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # a hostname subresource — not an IP-literal SSRF attempt
    return not _is_global(ip)


def screen_url_literal(url: str) -> str:
    """Scheme + literal-host screen for a URL about to be fetched or a redirect
    target. Returns the hostname. Raises ``PrivateAddressRefused`` on a disallowed
    scheme or a private/loopback literal — a redirect into ``file://`` or at
    ``10.0.0.1`` is refused, not chased."""
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise PrivateAddressRefused(f"refusing scheme {parts.scheme or '(none)'!r}: not http(s)")
    host = parts.hostname
    if not host:
        raise PrivateAddressRefused("refusing url with no host")
    if is_private_literal(host):
        raise PrivateAddressRefused(f"host {host!r} is a private/loopback literal")
    return host


async def resolve_public_host(host: str, *, resolver: Resolver | None = None) -> list[IPAddress]:
    """Resolve ``host`` and return its addresses, or raise ``PrivateAddressRefused``
    if ANY resolved address is non-global (a mixed public+private answer is refused
    — an attacker only needs one private record to win). Empty resolution is also a
    refusal: we never "pass because we couldn't check". A resolver *error*
    (NXDOMAIN → ``socket.gaierror``) is left to propagate as an ordinary fetch
    failure; only a *successful-but-unsafe* answer becomes ``PrivateAddressRefused``.
    """
    resolve = resolver or _default_resolver
    addresses = await resolve(host)
    if not addresses:
        raise PrivateAddressRefused(f"host {host!r} resolved to no addresses")
    resolved: list[IPAddress] = []
    for addr in addresses:
        ip = _parse_ip(addr)
        if not _is_global(ip):
            raise PrivateAddressRefused(
                f"host {host!r} resolves to non-global address {addr!r} — refusing to fetch"
            )
        resolved.append(ip)
    return resolved


async def screen_url(url: str, *, resolver: Resolver | None = None) -> list[IPAddress]:
    """Full pre-connect screen: scheme + literal host, then DNS resolution. Raises
    ``PrivateAddressRefused`` on any failure and returns the screened addresses.
    Called before the initial fetch and before each redirect hop by the real tier
    fetchers."""
    host = screen_url_literal(url)
    return await resolve_public_host(host, resolver=resolver)


async def screen_urls(urls: Iterable[str], *, resolver: Resolver | None = None) -> None:
    """Screen a *set* of URLs — every one must pass ``screen_url`` (scheme + literal
    + DNS) or the first offender raises ``PrivateAddressRefused``. This is the
    CI-testable seam for tier 2's post-load redirect-chain screen: the browser-coupled
    part (walking ``request.redirected_from`` to collect the hop URLs) stays a thin
    inline loop in the fetcher, while the security decision — "is any hop private?" —
    lives here where a fake resolver can exercise it without a browser.

    Order is preserved and duplicates are screened in dedup'd order so a caller that
    already dedup'd its hops does no redundant DNS. Screens all hops rather than only
    the landing URL because a ``public → private(reachable) → public`` redirect chain
    transits the private host (the browser makes that request) even though the final
    URL is clean."""
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        await screen_url(url, resolver=resolver)


def pin_target(url: str, address: IPAddress) -> tuple[str, str, str]:
    """Closes the DNS-rebinding TOCTOU for a single connection: rewrite ``url`` so
    the socket dials the already-screened ``address``, while the original hostname
    is preserved for the ``Host`` header, TLS SNI, and certificate verification.

    Returns ``(pinned_url, host_header, sni_hostname)``. The caller connects to
    ``pinned_url`` (IP authority), sets ``Host: host_header``, and passes
    ``extensions={"sni_hostname": sni_hostname}`` — httpcore uses that as the TLS
    ``server_hostname``, so with the default verifying context (``check_hostname``)
    the certificate is still validated against the hostname, not the IP. Because we
    dial the exact IP we vetted, httpx's own connect-time ``getaddrinfo`` never runs
    for this request, so a resolver that flips public→private between our screen and
    the connect cannot land the socket on a private address."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    ip = str(address)
    ip_authority = f"[{ip}]" if isinstance(address, ipaddress.IPv6Address) else ip
    if parts.port is not None:
        ip_authority = f"{ip_authority}:{parts.port}"
    host_header = host if parts.port is None else f"{host}:{parts.port}"
    pinned_url = urlunsplit((parts.scheme, ip_authority, parts.path, parts.query, ""))
    return pinned_url, host_header, host
