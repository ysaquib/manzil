"""VALIDATE_URL stage (DESIGN v2.4, §10.1/§10.3): is the submitted URL worth
fetching at all?

Pure deterministic code (§10.2 P2, no LLM): scheme, a public host, and a
plausibly-HTML target — rejecting garbage before any fetch, tier escalation,
or token is spent, and refusing private/loopback hosts so a pasted URL can
never point the worker at internal infrastructure (§16). Content-level
validation ("is this a rental listing page?") is VALIDATE, after FETCH.

Also the one place URL normalization happens: surrounding whitespace and
fragments are stripped, and the normalized URL is written back to the state
so every later stage (and the adapter registry) sees one canonical form.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit, urlunsplit

import structlog
from manzil_shared.errors import StageFatal

from manzil_worker.stages.base import StageCtx
from manzil_worker.state import RunState

log = structlog.get_logger()

_ALLOWED_SCHEMES = ("http", "https")

# Extensions that are definitely not a listing page — reject before fetching.
_NON_HTML_EXTENSIONS = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".zip",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".mp4",
    ".mov",
)


def _is_private_host(hostname: str) -> bool:
    if hostname == "localhost" or hostname.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False  # a name, not an IP literal — public DNS resolves it
    return not address.is_global


def normalize_url(raw: str) -> str:
    """Validate and canonicalize; raises StageFatal with the reason."""
    url = raw.strip()
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise StageFatal(f"invalid url: scheme {parts.scheme or '(none)'!r} is not http(s)")
    hostname = parts.hostname
    if not hostname or ("." not in hostname and hostname != "localhost"):
        raise StageFatal("invalid url: no resolvable host")
    if _is_private_host(hostname):
        raise StageFatal(f"invalid url: host {hostname!r} is private/loopback — refusing to fetch")
    path_lower = parts.path.lower()
    if path_lower.endswith(_NON_HTML_EXTENSIONS):
        raise StageFatal(f"invalid url: {path_lower.rsplit('.', 1)[-1]!r} file, not a listing page")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


async def validate_url_stage(state: RunState, ctx: StageCtx) -> RunState:
    state.url = normalize_url(state.url)
    log.info("url_validated", job_id=str(state.job_id), stage="validate_url", url=state.url)
    return state
