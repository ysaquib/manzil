"""Deterministic search hint from a listing URL (§20 2026-07-07 stopgap).

Aggregator URLs embed the property's identity in the slug
(`apartments.com/park-west-detroit-mi/…` → "apartment complex name city state"). When every
tier fails, FETCH puts this hint in the job error so a human can find the
same property on a fetchable source and resubmit. Zero LLM, zero network —
the principled multi-source rescue is DISCOVER (P3-5); this is the Phase 0
human-in-the-loop version of it.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# Words that describe the *site*, not the property.
_NOISE = frozenset(
    {
        "apartment",
        "apartments",
        "apt",
        "apts",
        "rent",
        "rental",
        "rentals",
        "for",
        "forrent",
        "for-rent",
        "property",
        "properties",
        "listing",
        "listings",
        "home",
        "homes",
        "house",
        "houses",
        "unit",
        "units",
        "floorplans",
        "detail",
        "details",
        "search",
        "find",
    }
)

# Any digit marks an id-ish token (lc5933022, 5XjKcm, xk1234) — property
# identities live in the words, not the ids.
_ID_TOKEN = re.compile(r"\d")


def search_hint(url: str) -> str | None:
    """Best-effort property identity from the URL path, e.g.
    'autumn ridge detroit mi'. None when the path carries no usable identity
    (needs at least two tokens — one word is not an identity)."""
    try:
        path = urlsplit(url).path.lower()
    except ValueError:
        return None
    tokens: list[str] = []
    for segment in path.split("/"):
        for token in re.split(r"[-_+.,]", segment):
            if not token or token in _NOISE or _ID_TOKEN.search(token):
                continue
            if token not in tokens:
                tokens.append(token)
    return " ".join(tokens) if len(tokens) >= 2 else None
