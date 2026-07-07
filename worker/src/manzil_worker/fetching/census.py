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
    "tier3_outcome",
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


def _verdict(settled_tier: int, final_outcome: FetchOutcome, top_tier: int) -> str:
    if final_outcome is FetchOutcome.SUCCESS:
        return f"tier{settled_tier}_ok"
    if final_outcome in (FetchOutcome.SHELL, FetchOutcome.BLOCKED):
        # Blocked with tier 3 on the ladder = even the unblocker failed;
        # blocked without it = the pre-tier-3 verdict, still open.
        return "hostile_unfetchable" if top_tier >= 3 else "hostile_needs_tier3"
    return final_outcome.value


async def run_census(urls: list[str], fetchers: dict[int, Fetcher], out_path: Path) -> Path:
    registry = InMemoryRegistry()  # census is a probe: never pollutes the real registry
    rows: list[dict[str, str]] = []
    for url in urls:
        ladder = await fetch_with_ladder(url, registry, fetchers)
        by_tier = dict(ladder.attempts)
        settled_tier = ladder.attempts[-1][0]
        outcomes = {f"tier{t}_outcome": by_tier[t].value if t in by_tier else "" for t in (1, 2, 3)}
        rows.append(
            {
                "site_domain": site_domain(url),
                "url": url,
                **outcomes,
                "required_tier": str(settled_tier),
                "verdict": _verdict(settled_tier, ladder.outcome, max(fetchers)),
            }
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return out_path
