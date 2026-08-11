"""FETCH stage (Phase 0: single source — the submitted URL).

Runs the tier ladder (§10.7) and lands the cleaned page on RunState. Outcome
routing: `success` and `not_listing` proceed (the classifier's not_listing is
a candidate verdict — VALIDATE is the authority); `error` is retryable;
`shell`/`blocked` at the top tier is fatal — §10.1: hard failure only when
zero sources are fetchable, and in Phase 0 there is exactly one source.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from manzil_shared.errors import FetchProviderError, StageFatal, StageRetryable
from manzil_shared.models import FetchOutcome

from manzil_worker.enrich.images import discover_images
from manzil_worker.fetching.ladder import fetch_with_ladder
from manzil_worker.fetching.registry import MAX_TIER
from manzil_worker.fetching.slug_hint import search_hint
from manzil_worker.fetching.tier3 import missing_provider_env, tier3_provider
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import RunState, SourceState

log = structlog.get_logger()

_PROCEED = (FetchOutcome.SUCCESS, FetchOutcome.NOT_LISTING)


def _planned_skip(state: RunState, url: str) -> bool:
    """True when PLAN marked this run's source `action: skip` (why: hash_fresh):
    the persisted cleaned text is already on `state.sources`, so FETCH must use it
    rather than hit the network (DESIGN §10.4, P3-2)."""
    if state.plan is None:
        return False
    entry = next((s for s in state.plan.sources if s.url == url), None)
    return (
        entry is not None
        and entry.action == "skip"
        and any(source.url == url and source.cleaned_text for source in state.sources)
    )


async def _fetch_one(state: RunState, ctx: StageCtx, url: str) -> SourceState:
    existing = next((source for source in state.sources if source.url == url), None)
    if _planned_skip(state, url) and existing is not None:
        log.info(
            "fetch_skipped",
            job_id=str(state.job_id),
            stage="fetch",
            why="hash_fresh",
            hash=existing.cleaned_hash,
            url=url,
        )
        return existing
    if ctx.registry is None:
        raise StageFatal("fetch: no adapter registry in StageCtx")
    try:
        ladder = await fetch_with_ladder(url, ctx.registry, ctx.fetchers)
    except FetchProviderError as error:
        # The unblocker's API refused us; the target said nothing. Report it as
        # what it is (§20 2026-08-11) rather than as a status on the listing URL,
        # and do not buy the same refusal three more times when it is one of the
        # deterministic ones.
        message = f"{error} (fetching {url})"
        raise (StageRetryable(message) if error.retryable else StageFatal(message)) from error
    discovered_images = discover_images(ladder.result.body, ladder.result.final_url)
    discovered = next((item for item in state.discovered_sources if item.url == url), None)
    rounds = (
        state.plan.escalation.rounds
        if state.plan is not None and state.plan.escalation is not None
        else []
    )
    round_kind = next(
        (round_.kind for round_ in rounds if any(entry.url == url for entry in round_.sources)),
        None,
    )
    source = SourceState(
        url=url,
        is_official=url == state.official_source_url or bool(discovered and discovered.is_official),
        syndication_family=(
            discovered.syndication_family
            if discovered is not None
            else (existing.syndication_family if existing is not None else url)
        ),
        role=(
            existing.role
            if existing is not None
            else ("submitted" if url == state.url else (round_kind or "baseline"))
        ),
        tier_used=ladder.result.tier,
        fetched_at=datetime.now(UTC),
        outcome=ladder.outcome,
        cleaned_text=ladder.cleaned.text,
        cleaned_hash=ladder.cleaned.text_hash,
        fee_tables_found=ladder.cleaned.fee_tables_found,
        image_urls=[image.url for image in discovered_images],
        image_candidates=[image.__dict__ for image in discovered_images],
        content_changed=(
            ladder.cleaned.text_hash != state.prior_source_hashes[url]
            if url in state.prior_source_hashes
            else True
        )
        if state.job_type.value == "refresh"
        else None,
    )
    log.info(
        "fetched",
        job_id=str(state.job_id),
        stage="fetch",
        tier=ladder.result.tier,
        outcome=ladder.outcome.value,
        url=url,
    )

    if ladder.outcome is FetchOutcome.ERROR:
        # Name the rung and, when one carried the request, the provider — a bare
        # status reads as if the target returned it, which at tier 3 it may not
        # have (§20 2026-08-11).
        via = f" via {ladder.result.provider}" if ladder.result.provider else ""
        detail = f": {ladder.result.error}" if ladder.result.error else ""
        raise StageRetryable(
            f"fetch error for {url} — the page returned status "
            f"{ladder.result.status_code} at tier {ladder.result.tier}{via}{detail}"
        )
    if ladder.outcome not in _PROCEED:
        message = (
            f"source unfetchable: {ladder.outcome.value} at tier {ladder.result.tier} "
            f"(attempts: {[(t, o.value) for t, o in ladder.attempts]})"
        )
        # Say when the ladder topped out early: tier 3 off the ladder (§10.7)
        # reads very differently from tier 3 tried-and-blocked — and name the
        # settings that are missing, because "not configured" sends an operator
        # looking at the key when it is the zone that is absent.
        if MAX_TIER not in ctx.fetchers:
            try:
                provider = tier3_provider()
                missing = missing_provider_env(provider)
                why = (
                    f"{provider.name} is missing {', '.join(missing)}"
                    if missing
                    else "no provider configured"
                )
            except KeyError as error:  # unknown MANZIL_TIER3_PROVIDER
                why = str(error).strip("\"'")
            message += (
                f"; tier 3 (unblocker) was not attempted — {why} in this process's environment"
            )
        # §20 2026-07-07 stopgap: the URL slug usually names the property —
        # hand the human the search that DISCOVER (P3-5) will one day run.
        hint = search_hint(url)
        if hint:
            message += (
                f'; property identity from the URL: try searching "{hint}" on a '
                "fetchable source (e.g. rent.com, apartmentguide.com) and resubmit"
            )
        raise StageFatal(message)
    return source


def _target_urls(state: RunState) -> list[str]:
    if state.slate_urls:
        return list(dict.fromkeys(state.slate_urls))
    return [state.url]


async def fetch_stage(state: RunState, ctx: StageCtx) -> RunState:
    """Fetch every not-yet-fetched Source in the current slate.

    The submitted Source remains fatal because the run has no usable listing
    without it. Sibling/arbiter failures are isolated and retained as Source
    outcomes so one hostile page cannot discard otherwise usable evidence.
    """
    for url in _target_urls(state):
        existing = next((source for source in state.sources if source.url == url), None)
        if existing is not None and existing.outcome in _PROCEED and existing.cleaned_text:
            continue
        try:
            fetched = await _fetch_one(state, ctx, url)
        except (StageFatal, StageRetryable):
            if url == state.url:
                raise
            log.warning("source_fetch_skipped", job_id=str(state.job_id), url=url)
            continue
        if existing is None:
            state.sources.append(fetched)
        else:
            state.sources[state.sources.index(existing)] = fetched
    if not any(source.outcome in _PROCEED and source.cleaned_text for source in state.sources):
        raise StageFatal("no Source in the slate was fetchable")
    if (
        state.job_type.value == "refresh"
        and state.plan is not None
        and set(state.refresh_fields) & {"pricing", "listing_details"}
        and not set(state.refresh_fields) & {"images", "reviews", "location"}
        and state.sources
        and all(source.content_changed is False for source in state.sources)
    ):
        state.plan.skipped.update(
            {
                "EXTRACT": "content_hash_unchanged",
                "VERIFY": "content_hash_unchanged",
                "RECONCILE": "content_hash_unchanged",
                "CUSTOM_MATCH": "content_hash_unchanged",
            }
        )
        if not set(state.refresh_fields) & {"images", "reviews", "location"}:
            state.plan.skipped["SCORE"] = "content_hash_unchanged"
    return state
