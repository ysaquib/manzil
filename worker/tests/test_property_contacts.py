"""P3-21: property contact normalization, provenance precedence, and the PII
guards (DESIGN §8.2, §16 as amended §20 2026-07-27).

Contact info is unscored display metadata resolved by strict provenance
precedence, not the §10.6 ladder. These tests pin the deterministic half: what
survives normalization, what the domain guard rejects, and that the worker's
precedence order matches the `property_contacts_current` view's.
"""

from __future__ import annotations

import pytest
from manzil_worker.enrich.contacts import (
    PROVENANCE_RANK,
    ContactKind,
    ContactProvenance,
    build_contact_records,
    normalize_contact_url,
    normalize_phone,
    registrable_domain,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(313) 555-0142", "(313) 555-0142"),
        ("313-555-0142", "(313) 555-0142"),
        ("313.555.0142", "(313) 555-0142"),
        ("3135550142", "(313) 555-0142"),
        ("+1 (313) 555-0142", "(313) 555-0142"),
        ("1-313-555-0142", "(313) 555-0142"),
        ("  (313) 555-0142  ", "(313) 555-0142"),
        # Extensions are dropped: the main line is what a renter dials, and
        # keeping them would make dedupe miss otherwise-identical numbers.
        ("(313) 555-0142 x204", "(313) 555-0142"),
        ("(313) 555-0142 ext. 204", "(313) 555-0142"),
    ],
)
def test_normalize_phone_accepts_us_formats(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "call us",
        "48187",  # zip code
        "123456789",  # nine digits
        "123456789012",  # twelve digits
        "(013) 555-0142",  # NANP area codes never start 0/1
        "(313) 155-0142",  # NANP exchanges never start 0/1
        "$1,450 / 2 bed",  # page noise that happens to carry digits
    ],
)
def test_normalize_phone_rejects_non_phones(raw: str | None) -> None:
    """Strict by design: a permissive parser would let rent figures, unit counts,
    and zip codes through as phone numbers."""
    assert normalize_phone(raw) is None


def test_registrable_domain_strips_www_and_subdomains() -> None:
    assert registrable_domain("www.maplecourt.com") == "maplecourt.com"
    assert registrable_domain("leasing.maplecourt.com") == "maplecourt.com"
    assert registrable_domain("MapleCourt.COM") == "maplecourt.com"


def test_contact_url_requires_http_scheme() -> None:
    assert normalize_contact_url("ftp://maplecourt.com/contact") is None
    assert normalize_contact_url("javascript:alert(1)") is None
    assert normalize_contact_url("/contact") is None
    assert normalize_contact_url("https://maplecourt.com/contact") == (
        "https://maplecourt.com/contact"
    )


def test_contact_url_must_share_the_official_registrable_domain() -> None:
    """An aggregator's 'contact us' page is a lead form for the aggregator, not a
    way to reach the property."""
    official = "https://www.maplecourt.com/"
    assert (
        normalize_contact_url("https://leasing.maplecourt.com/tour", official_url=official)
        == "https://leasing.maplecourt.com/tour"
    )
    assert normalize_contact_url("https://apartments.com/contact", official_url=official) is None


def test_contact_url_unguarded_when_no_official_url_is_known() -> None:
    assert (
        normalize_contact_url("https://apartments.com/contact", official_url=None)
        == "https://apartments.com/contact"
    )


def test_build_contact_records_drops_unparseable_values() -> None:
    """A missing contact is the designed give-up state, so a bad parse yields no
    record rather than an error."""
    records = build_contact_records(
        phone="call the office",
        contact_url="not a url",
        provenance=ContactProvenance.LISTING,
    )
    assert records == []


def test_build_contact_records_emits_both_kinds() -> None:
    records = build_contact_records(
        phone="313-555-0142",
        contact_url="https://maplecourt.com/contact",
        provenance=ContactProvenance.OFFICIAL_SITE,
        official_url="https://maplecourt.com",
    )
    assert [(r.kind, r.value, r.provenance) for r in records] == [
        (ContactKind.PHONE, "(313) 555-0142", ContactProvenance.OFFICIAL_SITE),
        (
            ContactKind.CONTACT_URL,
            "https://maplecourt.com/contact",
            ContactProvenance.OFFICIAL_SITE,
        ),
    ]


def test_provenance_precedence_is_official_then_places_then_listing() -> None:
    """The one rung that replaces the ladder. Mirrors the CASE in the
    `property_contacts_current` view — worker and database must not disagree."""
    assert (
        PROVENANCE_RANK[ContactProvenance.OFFICIAL_SITE]
        < PROVENANCE_RANK[ContactProvenance.GOOGLE_PLACES]
        < PROVENANCE_RANK[ContactProvenance.LISTING]
    )


def test_contact_record_carries_no_person_identity() -> None:
    """§16 PII control by construction: there is nowhere to store who answered
    the phone, so a named agent's identity cannot be persisted even if a page
    supplies one."""
    records = build_contact_records(
        phone="313-555-0142",
        contact_url=None,
        provenance=ContactProvenance.LISTING,
    )
    assert set(vars(records[0])) == {"kind", "value", "provenance"}
