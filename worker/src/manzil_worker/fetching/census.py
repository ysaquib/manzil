"""Hostile-domain census (P0-6, DESIGN §19): which target-market sources demand
which fetch tier? Feeds the Phase 0 decision gate on Tier-3/Apify work.

Input: a text file of candidate URLs (one per line, `#` comments). Output: a
CSV of per-URL outcomes at each tier tried plus the settled tier requirement.
"""

from __future__ import annotations

import csv
from pathlib import Path

from manzil_shared.models import FetchOutcome

from manzil_worker.fetching.ladder import fetch_with_ladder
from manzil_worker.fetching.registry import InMemoryRegistry
from manzil_worker.fetching.tiers import Fetcher, site_domain

CSV_FIELDS = [
    "site_domain",
    "url",
    "tier1_outcome",
    "tier2_outcome",
    "required_tier",
    "verdict",
]


def read_url_file(path: Path) -> list[str]:
    urls: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def _verdict(required_tier: int, final_outcome: FetchOutcome) -> str:
    if final_outcome is FetchOutcome.SUCCESS:
        return f"tier{required_tier}_ok"
    if final_outcome in (FetchOutcome.SHELL, FetchOutcome.BLOCKED):
        return "hostile_needs_tier3"
    return final_outcome.value


async def run_census(urls: list[str], fetchers: dict[int, Fetcher], out_path: Path) -> Path:
    registry = InMemoryRegistry()  # census is a probe: never pollutes the real registry
    rows: list[dict[str, str]] = []
    for url in urls:
        ladder = await fetch_with_ladder(url, registry, fetchers)
        by_tier = dict(ladder.attempts)
        settled_tier = ladder.attempts[-1][0]
        rows.append(
            {
                "site_domain": site_domain(url),
                "url": url,
                "tier1_outcome": by_tier.get(1, FetchOutcome.ERROR).value if 1 in by_tier else "",
                "tier2_outcome": by_tier.get(2).value if 2 in by_tier else "",  # type: ignore[union-attr]
                "required_tier": str(settled_tier),
                "verdict": _verdict(settled_tier, ladder.outcome),
            }
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return out_path
