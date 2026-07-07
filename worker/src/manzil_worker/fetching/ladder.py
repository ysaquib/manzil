"""Tier ladder (P0-6, DESIGN §10.7): start at the domain's registered tier,
classify every fetch, escalate on shell/blocked, record outcomes so the
registry self-tunes."""

from __future__ import annotations

import structlog
from manzil_shared.models import FetchOutcome
from pydantic import BaseModel

from manzil_worker.fetching.classifier import classify
from manzil_worker.fetching.cleaner import clean_html
from manzil_worker.fetching.registry import MAX_TIER, AdapterRegistry
from manzil_worker.fetching.results import CleanedPage, FetchResult
from manzil_worker.fetching.tiers import Fetcher, site_domain

log = structlog.get_logger()


class LadderResult(BaseModel):
    result: FetchResult
    cleaned: CleanedPage
    outcome: FetchOutcome
    attempts: list[tuple[int, FetchOutcome]]  # (tier, outcome) per rung climbed


async def fetch_with_ladder(
    url: str,
    registry: AdapterRegistry,
    fetchers: dict[int, Fetcher],
    *,
    capture_screenshot: bool = False,
) -> LadderResult:
    """Climb from the registered tier; escalation happens per domain, not per
    fetch — the outcome recorded on each rung is what makes the next fetch of
    this domain start at the right tier."""
    domain = site_domain(url)
    # Clamp the start tier to what's actually runnable: the registry may say a
    # domain needs tier 3 while this run has no tier-3 fetcher configured.
    available = sorted(fetchers)
    wanted = min(await registry.required_tier(domain), MAX_TIER)
    runnable = [t for t in available if t <= wanted]
    tier = runnable[-1] if runnable else available[0]
    attempts: list[tuple[int, FetchOutcome]] = []

    while True:
        fetcher = fetchers[tier]
        result = await fetcher.fetch(url, capture_screenshot=capture_screenshot)
        cleaned = (
            clean_html(result.body)
            if result.body
            else CleanedPage(text="", text_hash="", fee_tables_found=0)
        )
        outcome = classify(result, cleaned)
        attempts.append((tier, outcome))
        await registry.record(domain, tier, outcome)
        log.info("fetch_classified", url=url, tier=tier, outcome=outcome.value)

        escalate = outcome in (FetchOutcome.SHELL, FetchOutcome.BLOCKED)
        # Next *available* rung (tiers may have gaps, e.g. {1, 3} under --no-tier2).
        higher = [t for t in available if tier < t <= MAX_TIER]
        if not escalate or not higher:
            return LadderResult(result=result, cleaned=cleaned, outcome=outcome, attempts=attempts)
        tier = higher[0]
