"""Embedded structured-data miner (DESIGN §10.7, §20 2026-07-07 v2.6).

Listing sites server-render their *data* even when they don't server-render
their DOM: JSON-LD blocks and framework state blobs (`__NEXT_DATA__`,
`window.__PRELOADED_STATE__ = {...}`, bare-JSON state scripts) carry the floor
plans, prices and fees that never reach the rendered text at tier 1. This
module mines those script tags into a compact JSON digest the cleaner appends
under `[EMBEDDED DATA]`, so EXTRACT sees the facts without any site-specific
adapter. Deterministic, zero LLM.

Pruning is list-driven, drop before keep:
- `_DROP` kills whole subtrees that are noise or — worse — contamination:
  `similar`/`nearby` listings carry *another property's* floor plans and
  prices, and must never reach EXTRACT under this listing's URL.
- `_SIGNAL` keeps subtrees whose key looks like a rental fact.
- `_SCRUB` strips bulk (image/url/media keys, URL string values, nulls) from
  kept subtrees. Everything else is discarded.
"""

from __future__ import annotations

import json
import re
from typing import Any

import lxml.html
from manzil_shared.config import EMBEDDED_DATA_MAX_CHARS, EMBEDDED_SCRIPT_MIN_CHARS

EMBEDDED_DATA_MARKER = "[EMBEDDED DATA]"

# JSON-LD blocks whose every @type is boilerplate carry no listing facts.
_BOILERPLATE_LD_TYPES = frozenset(
    {
        "breadcrumblist",
        "listitem",
        "website",
        "webpage",
        "searchaction",
        "organization",
        "corporation",
        "sitenavigationelement",
        "imageobject",
    }
)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TOKEN = re.compile(r"[a-z0-9]+")

# Subtrees that are noise, tracking plumbing, or wrong-property contamination.
_DROP = frozenset(
    [
        "similar",
        "nearby",
        "recommended",
        "recommendation",
        "recommendations",
        "seo",
        "breadcrumb",
        "breadcrumbs",
        "analytics",
        "tracking",
        "gtm",
        "experiment",
        "experiments",
        "testing",
        "translation",
        "translations",
        "i18n",
        "locale",
        "locales",
        "school",
        "schools",
        "review",
        "reviews",
        "user",
        "session",
        "cookie",
        "cookies",
        "request",
        "headers",
        "auth",
        "geolocation",
        "device",
        "sem",
        "env",
        "build",
        "runtime",
        "webpack",
        "chunks",
        "assets",
        "styles",
        "icons",
        "sprite",
        "gallery",
        "video",
        "videos",
        "photo",
        "photos",
        "image",
        "images",
        "media",
        "map",
        "maps",
        "marker",
        "static",
        "nav",
        "footer",
        "banner",
        "ads",
        "campaign",
        "marketing",
        "optimizely",
        "fastly",
        "trend",
        "trends",
        "bot",
        "agent",
        "ip",
        "host",
        "referrer",
        "route",
        "router",
    ]
)

# Subtrees that look like rental facts — kept whole (minus _DROP/_SCRUB inside).
_SIGNAL = frozenset(
    [
        "floorplan",
        "floorplans",
        "plan",
        "plans",
        "unit",
        "units",
        "price",
        "prices",
        "pricing",
        "rent",
        "rents",
        "rental",
        "bed",
        "beds",
        "bedroom",
        "bedrooms",
        "bath",
        "baths",
        "bathroom",
        "bathrooms",
        "sqft",
        "deposit",
        "deposits",
        "fee",
        "fees",
        "amenity",
        "amenities",
        "lease",
        "leases",
        "leasing",
        "pet",
        "pets",
        "parking",
        "address",
        "availability",
        "availabilities",
        "available",
        "special",
        "specials",
        "promotion",
        "promotions",
        "promo",
        "utility",
        "utilities",
        "laundry",
        "washer",
        "dryer",
        "income",
        "listing",
        "listings",
        "property",
        "properties",
        "building",
        "buildings",
        "apartment",
        "apartments",
        "community",
    ]
)

# Bulk stripped from kept subtrees: media keys and URL-ish values.
_SCRUB = frozenset(
    [
        "image",
        "images",
        "img",
        "photo",
        "photos",
        "url",
        "urls",
        "href",
        "link",
        "links",
        "icon",
        "icons",
        "thumbnail",
        "thumbnails",
        "logo",
        "svg",
        "video",
        "videos",
        "css",
    ]
)

_URLISH = re.compile(r"^(?:https?:)?//|^data:", re.I)

# `lhs = {...}` / `lhs = [...]` assignment targets inside multi-statement scripts.
_ASSIGNED_JSON = re.compile(r"=\s*([\[{])")


def _tokens(key: str) -> set[str]:
    return set(_TOKEN.findall(_CAMEL_BOUNDARY.sub(" ", key).lower()))


def _scrub(node: Any) -> Any:
    """Strip media keys, URL strings, nulls and empty containers from a kept subtree."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if _tokens(key) & (_SCRUB | _DROP):
                continue
            cleaned = _scrub(value)
            if cleaned not in (None, {}, []):
                out[key] = cleaned
        return out
    if isinstance(node, list):
        items = [_scrub(item) for item in node]
        return [item for item in items if item not in (None, {}, [])]
    if isinstance(node, str) and _URLISH.match(node):
        return None
    return node


def _prune(node: Any) -> Any:
    """Walk a state blob: drop noise subtrees, keep signal subtrees, recurse the rest."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            toks = _tokens(key)
            if toks & _DROP:
                continue
            kept = _scrub(value) if toks & _SIGNAL else _prune(value)
            if kept not in (None, {}, []):
                out[key] = kept
        return out
    if isinstance(node, list):
        items = [_prune(item) for item in node]
        return [item for item in items if item not in (None, {}, [])]
    return None  # bare scalars outside a signal subtree carry no keyable fact


def _ld_types(node: Any) -> set[str]:
    if isinstance(node, dict):
        found: set[str] = set()
        declared = node.get("@type")
        for t in declared if isinstance(declared, list) else [declared]:
            if isinstance(t, str):
                found.add(t.lower())
        for value in node.values():
            found |= _ld_types(value)
        return found
    if isinstance(node, list):
        return set().union(*(_ld_types(item) for item in node)) if node else set()
    return set()


def _decode_candidates(body: str) -> list[Any]:
    """Every JSON value parseable from this script body: the whole body if it is
    bare JSON, else the right-hand side of each `x = {...}` assignment."""
    decoder = json.JSONDecoder()
    offsets = []
    stripped_at = len(body) - len(body.lstrip())
    if body[stripped_at : stripped_at + 1] in "[{":
        offsets.append(stripped_at)
    offsets.extend(m.start(1) for m in _ASSIGNED_JSON.finditer(body))
    found: list[Any] = []
    for offset in offsets[:50]:  # bound the work on minified-JS false positives
        try:
            value, _ = decoder.raw_decode(body, offset)
        except ValueError:
            continue
        if isinstance(value, (dict, list)) and value:
            found.append(value)
    return found


def extract_embedded_data(html: str) -> tuple[str, int]:
    """Mine script tags for listing data; return (digest, blobs_kept).

    JSON-LD blocks come first (curated, high signal — scrubbed but not
    pruned); framework state blobs follow, largest pruned blob first. The
    digest is capped at EMBEDDED_DATA_MAX_CHARS.
    """
    try:
        tree = lxml.html.fromstring(html)
    except Exception:
        return "", 0

    ld_blocks: list[str] = []
    state_blobs: list[str] = []
    seen: set[str] = set()
    for script in tree.iter("script"):
        body = script.text_content() or ""
        if (script.get("type") or "").lower() == "application/ld+json":
            try:
                data = json.loads(body)
            except ValueError:
                continue
            if not _ld_types(data) - _BOILERPLATE_LD_TYPES:
                continue
            rendered = json.dumps(_scrub(data), separators=(",", ":"))
            if rendered not in seen and rendered not in ("{}", "[]"):
                seen.add(rendered)
                ld_blocks.append(rendered)
        elif len(body) >= EMBEDDED_SCRIPT_MIN_CHARS:
            for value in _decode_candidates(body):
                pruned = _prune(value)
                if pruned in (None, {}, []):
                    continue
                rendered = json.dumps(pruned, separators=(",", ":"))
                if rendered not in seen:
                    seen.add(rendered)
                    state_blobs.append(rendered)

    state_blobs.sort(key=len, reverse=True)  # the main listing blob is the big one
    parts: list[str] = []
    budget = EMBEDDED_DATA_MAX_CHARS
    for blob in ld_blocks + state_blobs:
        if budget <= 0:
            break
        if len(blob) > budget:
            blob = blob[:budget] + "…[embedded data truncated]"
        parts.append(blob)
        budget -= len(blob) + 1
    return "\n".join(parts), len(parts)
