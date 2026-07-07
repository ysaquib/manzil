"""VALIDATE_URL (DESIGN v2.4): deterministic pre-fetch URL check — garbage,
binaries, and private hosts are rejected before any fetch or token."""

from __future__ import annotations

import asyncio

import pytest
from conftest import make_state
from manzil_shared.errors import StageFatal
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.validate_url import normalize_url, validate_url_stage


@pytest.mark.parametrize(
    "url",
    [
        "https://www.rent.com/michigan/detroit-apartments",
        "http://maplecourt.example/floorplans",
        "https://example.com/listing?unit=4b",
    ],
)
def test_plausible_listing_urls_pass(url: str) -> None:
    assert normalize_url(url) == url


def test_whitespace_and_fragment_are_normalized_away() -> None:
    assert (
        normalize_url("  https://example.com/listing?y=2#photos\n")
        == "https://example.com/listing?y=2"
    )


def test_stage_writes_the_normalized_url_back_to_state() -> None:
    state = make_state(url="https://example.com/listing#reviews")
    state = asyncio.run(validate_url_stage(state, StageCtx()))
    assert state.url == "https://example.com/listing"


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("ftp://example.com/listing", "not http"),
        ("mailto:leasing@example.com", "not http"),
        ("not a url at all", "not http"),
        ("https:///just-a-path", "no resolvable host"),
        ("https://intranet/listings", "no resolvable host"),
        ("https://localhost/admin", "private/loopback"),
        ("https://127.0.0.1:8000/x", "private/loopback"),
        ("https://192.168.1.1/router", "private/loopback"),
        ("https://10.0.0.7/internal", "private/loopback"),
        ("https://supabase.local/studio", "private/loopback"),
        ("https://example.com/brochure.pdf", "file, not a listing"),
        ("https://example.com/tour.MP4", "file, not a listing"),
    ],
)
def test_garbage_binaries_and_private_hosts_are_fatal(url: str, reason: str) -> None:
    with pytest.raises(StageFatal, match=reason):
        normalize_url(url)
