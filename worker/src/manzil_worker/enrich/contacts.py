"""Property contact normalization + provenance precedence (P3-21, DESIGN §8.2, §16).

Contact info is unscored display metadata: a leasing office line and a generic
contact URL, resolved by strict provenance precedence rather than the §10.6
conflict ladder. This module owns the deterministic guards that sit between a
model-emitted or API-emitted string and the `property_contacts` table — no LLM,
no network.

PII posture (§16 as amended 2026-07-27): property-level business contact only.
There is no name or role anywhere in this path; `ContactRecord` carries a value
and a provenance and nothing else, so a named agent's identity has nowhere to
land even if a page tries to supply one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse


class ContactKind(StrEnum):
    PHONE = "phone"
    CONTACT_URL = "contact_url"


class ContactProvenance(StrEnum):
    """Precedence order, best first — the one rung that replaces the ladder."""

    OFFICIAL_SITE = "official_site"
    GOOGLE_PLACES = "google_places"
    LISTING = "listing"


# Lower sorts better. Mirrors the `property_contacts_current` view's CASE so the
# worker and the database can never disagree about who wins.
PROVENANCE_RANK: dict[ContactProvenance, int] = {
    ContactProvenance.OFFICIAL_SITE: 1,
    ContactProvenance.GOOGLE_PLACES: 2,
    ContactProvenance.LISTING: 3,
}


@dataclass(frozen=True)
class ContactRecord:
    """One normalized contact observation, ready to persist."""

    kind: ContactKind
    value: str
    provenance: ContactProvenance


_DIGITS = re.compile(r"\d")
# Extension suffixes ("x123", "ext. 4") are dropped: the main line is what a
# renter dials, and keeping extensions would make dedupe miss identical numbers.
_EXTENSION = re.compile(r"\s*(?:x|ext\.?|extension)\s*\d+\s*$", re.IGNORECASE)


def normalize_phone(raw: str | None) -> str | None:
    """A US phone as `(555) 555-5555`, or None when the input is not one.

    Deliberately strict and US-only: the rent catalog is a US slice (§8.2), and a
    permissive parser would let page noise — prices, unit counts, zip codes —
    through as phone numbers. Accepts an optional `+1`/`1` country prefix and any
    punctuation; rejects everything else rather than guessing.
    """
    if not raw:
        return None
    text = _EXTENSION.sub("", raw.strip())
    digits = "".join(_DIGITS.findall(text))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    # NANP: area code and exchange both start 2-9. This is what rejects zip
    # codes, years, and concatenated rent figures that happen to be ten digits.
    if digits[0] in "01" or digits[3] in "01":
        return None
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def registrable_domain(host: str) -> str:
    """The last two labels of a hostname, lowercased and `www.`-stripped.

    A deliberately simple approximation of the public-suffix rule: it is used
    only to compare a contact URL against a known official host, where the
    failure mode of the naive version (treating `example.co.uk` as `co.uk`) makes
    the guard *stricter* on multi-label TLDs, never looser.
    """
    labels = host.lower().removeprefix("www.").split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host.lower()


def normalize_contact_url(raw: str | None, *, official_url: str | None = None) -> str | None:
    """An http(s) contact URL, or None when it fails the guards.

    When we know the property's official host, the contact URL must share its
    registrable domain — an aggregator's "contact us" page is a lead form for the
    aggregator, not a way to reach the property.
    """
    if not raw:
        return None
    parsed = urlparse(raw.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if official_url:
        official_host = urlparse(official_url).hostname
        if official_host and registrable_domain(parsed.hostname or "") != registrable_domain(
            official_host
        ):
            return None
    return parsed.geturl()


def build_contact_records(
    *,
    phone: str | None,
    contact_url: str | None,
    provenance: ContactProvenance,
    official_url: str | None = None,
) -> list[ContactRecord]:
    """Normalize a (phone, url) pair into the records worth persisting.

    Anything that fails normalization is dropped silently: a missing contact is
    the designed give-up state (the drawer falls back to the official link), so a
    bad parse must never become a job error.
    """
    records: list[ContactRecord] = []
    normalized_phone = normalize_phone(phone)
    if normalized_phone is not None:
        records.append(ContactRecord(ContactKind.PHONE, normalized_phone, provenance))
    normalized_url = normalize_contact_url(contact_url, official_url=official_url)
    if normalized_url is not None:
        records.append(ContactRecord(ContactKind.CONTACT_URL, normalized_url, provenance))
    return records
