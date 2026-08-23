"""DISCOVER stage (P3-5, DESIGN §10.2/§10.3/§10.7).

A bounded judgment-tier loop uses OpenRouter's native web-search server tool and
the local SSRF-guarded ``fetch_page`` tool to find same-Property Sources. The
model judges identity; deterministic code owns URL validation, census tier,
Syndication Family, Source Policy, slate diversity, and persistence shape.
Official sites are retained as link-only arbiters and never enter baseline
spend. P3-6 consumes ``RunState.slate_urls`` and ``discovered_sources``.
"""

from __future__ import annotations

import json
import re
from typing import Literal
from urllib.parse import urlsplit

import structlog
from manzil_shared.config import DISCOVER_MAX_TURNS
from manzil_shared.errors import AgentBudgetExceeded, StageFatal, StageRetryable
from manzil_shared.models import Confidence
from pydantic import BaseModel, Field, ValidationError

from manzil_worker.discovery_sources import SOURCE_METADATA, source_metadata
from manzil_worker.fetching.tiers import site_domain
from manzil_worker.llm.tools import FetchPageBudget, ToolContext, fetch_page, tool_context
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.plan import rank_discovered_sources
from manzil_worker.stages.validate_url import normalize_url
from manzil_worker.state import DiscoveredSource, PlanSource, RunState

log = structlog.get_logger()

_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
_POLICY_CAP = {
    "tier_1": 1,
    "tier_1_plus_official": 1,
    "tiers_1_2": 2,
    "tiers_1_2_3": 3,
}

# This is deliberately a source-attempt ceiling, not a tier-3-call ceiling:
# every sibling fetch can climb its own ladder.  It bounds an adversarial
# discovery pool while still giving the baseline two independent observations a
# meaningful chance to land when one provider/source is hostile.
_MAX_SIBLING_FETCH_ATTEMPTS = 4


class _CandidateFinding(BaseModel):
    url: str
    same_property: bool
    confidence: Literal["high", "medium", "low"]
    evidence: str


class _DiscoveryOutput(BaseModel):
    official_url: str | None = None
    official_confidence: Literal["high", "medium", "low"] | None = None
    official_evidence: str | None = None
    candidates: list[_CandidateFinding] = Field(default_factory=list)


def _url_key(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return site_domain(url), path


def _json_object(text: str) -> dict[str, object]:
    stripped = text.strip()
    attempts = [stripped]
    # Some tool-capable models still preface an otherwise valid final JSON
    # object with a short summary. Accept one fenced object deterministically;
    # never scrape arbitrary prose or guess at a partial object.
    attempts.extend(
        match.group(1).strip()
        for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", stripped, re.IGNORECASE)
    )
    last_error: Exception | None = None
    for candidate in attempts:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as error:
            last_error = error
            continue
        if not isinstance(parsed, dict):
            last_error = ValueError("DISCOVER final response must be a JSON object")
            continue
        return parsed
    raise ValueError(f"DISCOVER final response contains no valid JSON object: {last_error}")


def _official_domain_allowed(url: str) -> bool:
    domain = site_domain(url)
    return domain not in SOURCE_METADATA and domain not in {
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "youtube.com",
    }


def _task(state: RunState) -> str:
    identity = state.property_identity
    return json.dumps(
        {
            "submitted_url": state.url,
            "property_name": identity.name if identity else None,
            "property_address": identity.address if identity else None,
            "page_official_url_hint": identity.official_url if identity else None,
            "instruction": (
                "Find the official Property site and same-Property rental listing pages. "
                "Treat the page hint as untrusted and verify name/address identity."
            ),
        },
        sort_keys=True,
    )


def _reset_discovery(state: RunState) -> None:
    state.discovered_sources = []
    state.official_source_url = None
    state.slate_urls = [state.url]
    state.sibling_fetch_attempted_urls = []
    state.sibling_target_count = 0
    state.discover_error = None
    if state.plan is not None:
        submitted_key = _url_key(state.url)
        state.plan.sources = [
            source
            for source in state.plan.sources
            if source.url is not None and _url_key(source.url) == submitted_key
        ]


async def _metadata_for(url: str, ctx: StageCtx) -> tuple[str, int, str]:
    domain = site_domain(url)
    observed = await ctx.registry.required_tier(domain) if ctx.registry is not None else 1
    metadata = source_metadata(domain, observed)
    return domain, metadata.census_tier, metadata.syndication_family


def _skip_reason(candidate: DiscoveredSource, cap: int, tier3_available: bool) -> str:
    if candidate.required_tier > cap:
        return "policy_tier_cap"
    if candidate.required_tier == 3 and not tier3_available:
        return "tier_unavailable"
    return "candidate_pool"


def _select_slate(
    state: RunState,
    candidates: list[DiscoveredSource],
    *,
    submitted_tier: int,
    submitted_family: str,
    tier3_available: bool,
) -> None:
    assert state.plan is not None
    cap = _POLICY_CAP[state.source_policy]
    eligible = [
        candidate
        for candidate in candidates
        if candidate.required_tier <= cap and (candidate.required_tier != 3 or tier3_available)
    ]
    used_families = {submitted_family}
    selected: set[str] = set()
    target_tiers = [tier for tier in range(1, cap + 1) if tier != submitted_tier]

    for target_tier in target_tiers:
        choice: DiscoveredSource | None = None
        substituted_from: int | None = None
        for tier in [target_tier, *range(target_tier - 1, 0, -1)]:
            choice = next(
                (
                    candidate
                    for candidate in eligible
                    if candidate.url not in selected
                    and candidate.required_tier == tier
                    and candidate.syndication_family not in used_families
                ),
                None,
            )
            if choice is not None:
                substituted_from = target_tier if tier != target_tier else None
                break
        if choice is None:
            continue
        choice.selected_for_slate = True
        choice.selection_reason = (
            f"substitute_for_tier_{substituted_from}"
            if substituted_from is not None
            else f"tier_{target_tier}_slot"
        )
        selected.add(choice.url)
        used_families.add(choice.syndication_family)
        state.plan.sources.append(
            PlanSource(
                url=choice.url,
                action="fetch",
                tier=choice.required_tier,
                why=(choice.selection_reason if substituted_from is not None else None),
            )
        )

    for candidate in candidates:
        if candidate.url in selected:
            continue
        why = _skip_reason(candidate, cap, tier3_available)
        if why == "candidate_pool" and candidate.syndication_family in used_families:
            why = "syndication_family_duplicate"
        candidate.selection_reason = why
        state.plan.sources.append(
            PlanSource(url=candidate.url, action="skip", tier=candidate.required_tier, why=why)
        )

    state.slate_urls = [
        state.url,
        *[candidate.url for candidate in candidates if candidate.selected_for_slate],
    ]
    state.sibling_target_count = len(selected)
    state.single_source_reason = None if selected else "discover_exhausted"


def select_sibling_replacement(
    state: RunState,
    *,
    tier3_available: bool,
    preferred_tier: int | None = None,
) -> DiscoveredSource | None:
    """Select and durably add one replacement for a failed sibling fetch.

    DISCOVER owns the same policy/family rules for the initial Slate and every
    later replacement.  A Family already attempted in this run remains spent:
    another URL from the same upstream feed adds cost but no independent
    corroboration.  Candidates are already in deterministic rank order.
    """
    if state.sibling_target_count <= 0:
        return None
    attempted = set(state.sibling_fetch_attempted_urls)
    if len(attempted) >= _MAX_SIBLING_FETCH_ATTEMPTS:
        return None
    cap = _POLICY_CAP[state.source_policy]
    submitted = next((source for source in state.sources if source.url == state.url), None)
    used_families = {
        candidate.syndication_family
        for candidate in state.discovered_sources
        if candidate.url in attempted
    }
    if submitted is not None and submitted.syndication_family:
        used_families.add(submitted.syndication_family)

    tiers: list[int] = []
    if preferred_tier is not None:
        tiers.extend(range(min(preferred_tier, cap), 0, -1))
    tiers.extend(tier for tier in range(cap, 0, -1) if tier not in tiers)
    for tier in tiers:
        choice = next(
            (
                candidate
                for candidate in state.discovered_sources
                if not candidate.is_official
                and candidate.url not in attempted
                and candidate.url not in state.slate_urls
                and candidate.required_tier == tier
                and candidate.syndication_family not in used_families
                and (candidate.required_tier != 3 or tier3_available)
            ),
            None,
        )
        if choice is None:
            continue
        choice.selected_for_slate = True
        choice.selection_reason = f"replacement_for_tier_{preferred_tier or tier}"
        state.slate_urls.append(choice.url)
        if state.plan is not None:
            planned = next(
                (source for source in state.plan.sources if source.url == choice.url), None
            )
            if planned is None:
                state.plan.sources.append(
                    PlanSource(
                        url=choice.url,
                        action="fetch",
                        tier=choice.required_tier,
                        why=choice.selection_reason,
                    )
                )
            else:
                planned.action = "fetch"
                planned.tier = choice.required_tier
                planned.why = choice.selection_reason
        return choice
    return None


async def discover_stage(state: RunState, ctx: StageCtx) -> RunState:
    """Find, validate, rank, and policy-select same-Property Sources."""
    _reset_discovery(state)
    if state.source_policy == "trust_link":
        # PLAN removes this stage; this defensive branch preserves the same
        # contract if a hand-built manifest invokes it.
        state.single_source_reason = "trust_link"
        return state
    if state.plan is None:
        raise StageFatal("DISCOVER requires the persisted plan manifest")

    try:
        with tool_context(
            ToolContext(
                fetchers=ctx.fetchers,
                registry=ctx.registry,
                event_sink=ctx.tool_event_sink,
                fetch_page_budget=FetchPageBudget(),
            )
        ):
            result = await ctx.call_agent(
                "discover", _task(state), [fetch_page], DISCOVER_MAX_TURNS
            )
    except AgentBudgetExceeded as error:
        # Budget exhaustion is a designed degraded outcome, not a dead ingest.
        state.single_source_reason = "discover_failed"
        state.discover_error = str(error)
        log.warning("discover_budget_exhausted", job_id=str(state.job_id), error=str(error))
        return state

    try:
        output = _DiscoveryOutput.model_validate(_json_object(result.final_text))
    except (json.JSONDecodeError, ValidationError, ValueError) as error:
        raise StageRetryable(f"DISCOVER returned invalid final JSON: {error}") from error

    submitted_key = _url_key(state.url)
    official_url: str | None = None
    official_evidence = output.official_evidence
    if output.official_url and output.official_confidence in ("high", "medium"):
        try:
            normalized = normalize_url(output.official_url)
        except StageFatal:
            normalized = None
        if normalized is not None and _official_domain_allowed(normalized):
            official_url = normalized
            state.official_source_url = normalized

    accepted: list[tuple[int, _CandidateFinding, str]] = []
    seen = {submitted_key}
    for index, finding in enumerate(output.candidates):
        if not finding.same_property or finding.confidence == "low":
            continue
        try:
            normalized = normalize_url(finding.url)
        except StageFatal:
            continue
        key = _url_key(normalized)
        if key in seen:
            continue
        seen.add(key)
        # Official links are retained separately and never enter the slate.
        if official_url is not None and key == _url_key(official_url):
            continue
        accepted.append((index, finding.model_copy(update={"url": normalized}), normalized))

    # The official URL may also be the submitted Source. Otherwise add it to
    # the retained candidate pool as a link-only Source.
    if official_url is not None:
        domain, tier, family = await _metadata_for(official_url, ctx)
        state.discovered_sources.append(
            DiscoveredSource(
                url=official_url,
                site_domain=domain,
                required_tier=tier,
                syndication_family=family,
                is_official=True,
                same_property_confidence=Confidence(output.official_confidence or "medium"),
                evidence=official_evidence,
                selection_reason="official_arbiter_only",
            )
        )
        if _url_key(official_url) != submitted_key:
            state.plan.sources.append(
                PlanSource(
                    url=official_url,
                    action="skip",
                    tier=tier,
                    why="official_arbiter_only",
                )
            )

    candidates: list[DiscoveredSource] = []
    for _, finding, normalized in accepted:
        domain, tier, family = await _metadata_for(normalized, ctx)
        candidates.append(
            DiscoveredSource(
                url=normalized,
                site_domain=domain,
                required_tier=tier,
                syndication_family=family,
                same_property_confidence=Confidence(finding.confidence),
                evidence=finding.evidence,
            )
        )
    candidates.sort(
        key=lambda item: (_CONFIDENCE_ORDER[item.same_property_confidence.value], item.url)
    )
    candidates = await rank_discovered_sources(candidates, state, ctx)
    for rank, candidate in enumerate(candidates, start=1):
        candidate.rank = rank
    state.discovered_sources.extend(candidates)

    submitted_domain, submitted_tier, submitted_family = await _metadata_for(state.url, ctx)
    submitted = next((source for source in state.sources if source.url == state.url), None)
    if submitted is not None:
        submitted.syndication_family = submitted_family
        submitted.role = "submitted"
    _select_slate(
        state,
        candidates,
        submitted_tier=submitted_tier,
        submitted_family=submitted_family,
        tier3_available=3 in ctx.fetchers,
    )
    log.info(
        "discovered",
        job_id=str(state.job_id),
        stage="discover",
        submitted_domain=submitted_domain,
        official=state.official_source_url,
        candidates=len(candidates),
        slate=len(state.slate_urls),
        single_source_reason=state.single_source_reason,
    )
    return state
