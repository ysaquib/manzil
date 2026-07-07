"""Fetch outcome classifier (P0-6, DESIGN §10.7): layered checks, cheapest first.

`success | shell | blocked | not_listing | error` — HTTP-layer signals, then
challenge fingerprints, then positive content signals (JSON-LD short-circuit;
cleaned text — which includes the mined [EMBEDDED DATA] digest — long enough
AND a listing token), then negative body signals (JS-shell signature, size
floor). `not_listing` here is a candidate verdict — VALIDATE (LLM) confirms it
before it reaches the user.
"""

from __future__ import annotations

import re

from manzil_shared.config import (
    CLEANED_TEXT_MIN_CHARS,
    FETCH_MIN_BODY_BYTES,
    SHELL_SCRIPT_RATIO,
)
from manzil_shared.models import FetchOutcome

from manzil_worker.fetching.results import CleanedPage, FetchResult

# HTTP-layer signals (§10.7): challenge statuses, headers, cookies, captcha paths.
_BLOCK_STATUSES = {403, 429}
_CHALLENGE_COOKIE_MARKERS = ("cf-chl", "cf_clearance", "_px")
_CAPTCHA_URL_MARKERS = ("captcha", "challenge", "px-captcha", "blocked")

# Known challenge fingerprints in the body.
_CHALLENGE_FINGERPRINTS = (
    "pardon our interruption",
    "verify you are human",
    "enable javascript and cookies to continue",
    "cf-challenge",
    "checking if the site connection is secure",
    "are you a robot",
)

# Positive content signals: currency, bed/bath tokens, address fragments, and
# rental-fact keys in the mined [EMBEDDED DATA] digest (state blobs carry
# prices as bare numbers — `"priceLow": 1443` — that the currency regex misses).
_CURRENCY = re.compile(r"\$\s?\d{3,4}(?:[,.]\d{3})?")
_BED_BATH = re.compile(r"\b(?:\d+|studio)\s*(?:bed|br\b|bd\b|bedroom)|\bbath|\bba\b", re.I)
_JSON_FACT_KEYS = re.compile(
    r'"[a-z_]*(?:price|rent|bed|bath|floor_?plan|sq_?ft)[a-z_]*"\s*:', re.I
)
_ADDRESS = re.compile(
    r"\b(?:st|ave|rd|blvd|dr|ln|lane|way|ct|circle|pkwy)\.?,?\s+[a-z .]+,?\s+[a-z]{2}\s+\d{5}"
    r"|\b[a-z]{2}\s+\d{5}\b",
    re.I,
)

# JSON-LD types that short-circuit doubt (§10.7).
_JSONLD_BLOCK = re.compile(r'type=["\']application/ld\+json["\']', re.I)
_JSONLD_TYPES = re.compile(
    r'"@type"\s*:\s*"?(?:\[[^\]]*)?(?:ApartmentComplex|Apartment|RealEstateListing|Offer|'
    r"SingleFamilyResidence|House)",
    re.I,
)

_SCRIPT_CONTENT = re.compile(r"<script\b[^>]*>.*?</script>", re.I | re.S)


def _is_blocked(result: FetchResult, body_lower: str) -> bool:
    if result.status_code in _BLOCK_STATUSES:
        return True
    set_cookie = result.headers.get("set-cookie", "")
    if any(marker in set_cookie for marker in _CHALLENGE_COOKIE_MARKERS):
        return True
    if result.headers.get("cf-mitigated") == "challenge":
        return True
    if result.final_url != result.url and any(
        marker in result.final_url.lower() for marker in _CAPTCHA_URL_MARKERS
    ):
        return True
    return any(fp in body_lower for fp in _CHALLENGE_FINGERPRINTS)


def _is_js_shell(body: str) -> bool:
    """A body that is nearly all script tags is the JS-shell signature."""
    if not body:
        return False
    script_chars = sum(len(m.group(0)) for m in _SCRIPT_CONTENT.finditer(body))
    return script_chars / len(body) > SHELL_SCRIPT_RATIO


def has_listing_signal(text: str) -> bool:
    return bool(
        _CURRENCY.search(text)
        or _BED_BATH.search(text)
        or _ADDRESS.search(text)
        or _JSON_FACT_KEYS.search(text)
    )


def classify(result: FetchResult, cleaned: CleanedPage) -> FetchOutcome:
    """Routing downstream (§10.7): shell -> escalate one tier; blocked -> escalate
    and record in the registry; not_listing -> VALIDATE verdict; success -> clean,
    hash, proceed."""
    if result.error is not None or result.status_code == 0:
        return FetchOutcome.ERROR

    body_lower = result.body.lower()
    if _is_blocked(result, body_lower):
        return FetchOutcome.BLOCKED

    if result.status_code >= 400:  # non-challenge HTTP failure (404, 500, ...)
        return FetchOutcome.ERROR

    # JSON-LD is a strong positive that short-circuits the remaining doubt.
    if _JSONLD_BLOCK.search(result.body) and _JSONLD_TYPES.search(result.body):
        return FetchOutcome.SUCCESS

    # Positive content outranks the JS-shell heuristic (§20 v2.6): cleaned text
    # includes the mined [EMBEDDED DATA] digest, so a script-heavy body whose
    # state blob carries prices/floor plans is a usable page, not a shell.
    text = cleaned.text
    if len(text) >= CLEANED_TEXT_MIN_CHARS and has_listing_signal(text):
        return FetchOutcome.SUCCESS

    if _is_js_shell(result.body):
        return FetchOutcome.SHELL

    if len(result.body.encode()) < FETCH_MIN_BODY_BYTES or len(text) < CLEANED_TEXT_MIN_CHARS:
        return FetchOutcome.SHELL

    return FetchOutcome.NOT_LISTING
