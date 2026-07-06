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
    tier = max(min(await registry.required_tier(domain), MAX_TIER), min(fetchers))
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
        next_tier = tier + 1
        if not escalate or next_tier > MAX_TIER or next_tier not in fetchers:
            return LadderResult(result=result, cleaned=cleaned, outcome=outcome, attempts=attempts)
        tier = next_tier
