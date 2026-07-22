"""Deterministic Source metadata used by DISCOVER (P3-5).

The hostile-domain census is evidence, not a runtime database. Its settled
tier and Syndication Family assignments live here so selection remains stable
in packaged deployments where ``docs/`` is absent. A test pins this table to
the tracked CSV. Unknown domains start at the adapter registry's observed tier
and form their own family; that is conservative against false vote collapse.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceMetadata:
    census_tier: int
    syndication_family: str


SOURCE_METADATA: dict[str, SourceMetadata] = {
    "apartments.com": SourceMetadata(3, "costar"),
    "zillow.com": SourceMetadata(3, "zillow"),
    "rent.com": SourceMetadata(1, "rent_group"),
    "apartmentguide.com": SourceMetadata(1, "rent_group"),
    "zumper.com": SourceMetadata(2, "zumper"),
    "padmapper.com": SourceMetadata(2, "zumper"),
    "forrent.com": SourceMetadata(3, "costar"),
    "realtor.com": SourceMetadata(3, "realtor"),
    "hotpads.com": SourceMetadata(2, "zillow"),
    "trulia.com": SourceMetadata(3, "zillow"),
    "apartmentlist.com": SourceMetadata(1, "apartmentlist"),
    "apartmentfinder.com": SourceMetadata(3, "costar"),
    "rentable.co": SourceMetadata(1, "rentable"),
    "rentcafe.com": SourceMetadata(2, "rentcafe"),
    "renthop.com": SourceMetadata(2, "renthop"),
    "rentberry.com": SourceMetadata(1, "rentberry"),
    "redfin.com": SourceMetadata(1, "redfin"),
}


def source_metadata(domain: str, observed_tier: int) -> SourceMetadata:
    """Return conservative tier + family metadata for a normalized domain."""
    known = SOURCE_METADATA.get(domain)
    if known is None:
        return SourceMetadata(census_tier=observed_tier, syndication_family=domain)
    return SourceMetadata(
        census_tier=max(observed_tier, known.census_tier),
        syndication_family=known.syndication_family,
    )
