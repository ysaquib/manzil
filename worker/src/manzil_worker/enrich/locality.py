"""US locality parsing for DEDUPE geocoding (DESIGN §8.2, §20 2026-07-23).

Google address components are authoritative for state and county; city uses
Google `locality` first, then a strict parse of the original EXTRACT address
(never Google's `formatted_address`). `administrative_area_level_3` is never
treated as a city.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# 50 states + DC — checked-in mapping for address fallback and normalization.
US_STATE_CODES: frozenset[str] = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
    }
)

US_STATE_NAME_TO_CODE: dict[str, str] = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}

_POSTAL_TAIL = re.compile(
    r",\s*(?P<city>[^,]+),\s*(?P<state>[A-Za-z]{2}|[A-Za-z][A-Za-z\s]+?)"
    r"\s+(?P<zip>\d{5}(?:-\d{4})?)\s*(?:,\s*USA)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Locality:
    city: str | None
    state: str | None
    county: str | None


def normalize_us_state(raw: str | None) -> str | None:
    """Return an uppercase USPS code, or None when not a recognized US state."""
    if raw is None:
        return None
    token = raw.strip()
    if not token:
        return None
    upper = token.upper()
    if len(upper) == 2 and upper in US_STATE_CODES:
        return upper
    return US_STATE_NAME_TO_CODE.get(token.lower())


def _index_components(components: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = {}
    for component in components:
        for kind in component.get("types") or []:
            indexed.setdefault(kind, []).append(component)
    return indexed


def _first_long(components: list[dict[str, Any]] | None) -> str | None:
    if not components:
        return None
    value = components[0].get("long_name")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _first_short(components: list[dict[str, Any]] | None) -> str | None:
    if not components:
        return None
    value = components[0].get("short_name")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _parse_postal_tail(original_address: str) -> tuple[str | None, str | None]:
    """Strict US postal city/state from the original EXTRACT address only."""
    match = _POSTAL_TAIL.search(original_address.strip())
    if not match:
        return None, None
    city = match.group("city").strip()
    state = normalize_us_state(match.group("state"))
    if not city or state is None:
        return None, None
    return city, state


def parse_us_locality(
    components: list[dict[str, Any]],
    original_address: str,
) -> Locality:
    """Resolve city/state/county from Google components with US address fallback."""
    indexed = _index_components(components)
    country = _first_short(indexed.get("country"))
    is_us = country == "US"

    google_city = _first_long(indexed.get("locality"))
    google_state = normalize_us_state(_first_short(indexed.get("administrative_area_level_1")))
    county = _first_long(indexed.get("administrative_area_level_2")) if is_us else None

    address_city, address_state = _parse_postal_tail(original_address)

    if is_us:
        city = google_city or address_city
        state = google_state or address_state
    else:
        city = google_city
        state = None

    return Locality(city=city, state=state, county=county)
