"""P3-6 deterministic multi-Source reconciliation and bounded escalation."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import structlog
from manzil_shared.catalog import CATALOG
from manzil_shared.config import (
    ESCALATION_MAX_SIBLING_ROUNDS,
    ESCALATION_MAX_SIBLING_SOURCES,
    RECONCILE_SUPERMAJORITY,
    RENT_AGREE_PCT,
    SQFT_AGREE_PCT,
)
from manzil_shared.errors import CheckpointRaised
from manzil_shared.models import (
    CheckpointKind,
    CheckpointPrompt,
    Confidence,
    ConflictPolicy,
    EscalationPolicy,
    TargetScope,
)
from manzil_shared.scoring.engine import criterion_key, first_match
from pydantic import BaseModel, Field

from manzil_worker.llm.config import model_for_stage
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import (
    MandatoryFeesIn,
    OneTimeFeesIn,
    PendingDispute,
    PetCostsIn,
    PlanEscalation,
    PlanEscalationRound,
    PlanSource,
    RunState,
    SourceClaim,
    SourceResult,
    UtilitiesIn,
)

log = structlog.get_logger()

_CONFIDENCE_RANK = {
    Confidence.NOT_FOUND: 0,
    Confidence.LOW: 1,
    Confidence.MEDIUM: 2,
    Confidence.HIGH: 3,
}
_CATALOG = {entry.key: entry for entry in CATALOG}
_POLICY_CAP = {
    "trust_link": 0,
    "tier_1": 1,
    "tiers_1_2": 2,
    "tiers_1_2_3": 3,
    "tier_1_plus_official": 1,
}
_ALL_IN_INPUTS = {
    "all_in_monthly",
    "mandatory_fees",
    "utilities_included",
    "heating_type",
    "pet_costs",
}


class EquivalenceItem(BaseModel):
    item_id: str
    equivalence_key: str


class EquivalenceResponse(BaseModel):
    items: list[EquivalenceItem] = Field(default_factory=list)


def _target_key(claim: SourceClaim) -> str:
    if claim.target_scope is TargetScope.FLOOR_PLAN:
        concrete = claim.floor_plan_id or f"{claim.source_id}#{claim.floor_plan_ref}"
        return f"{claim.criterion_key}|floor_plan|{concrete}"
    return f"{claim.criterion_key}|property"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _freshness(result: SourceResult) -> datetime:
    return result.fetched_at or datetime.min.replace(tzinfo=UTC)


def _best_claim(claims: list[SourceClaim], results: dict[str, SourceResult]) -> SourceClaim:
    return max(
        claims,
        key=lambda claim: (
            _CONFIDENCE_RANK[claim.confidence],
            _freshness(results[claim.source_id or ""]),
            str(claim.claim_group_id),
        ),
    )


def _family_dedup(
    claims: list[SourceClaim], results: dict[str, SourceResult]
) -> list[SourceClaim]:
    by_family: dict[str, list[SourceClaim]] = defaultdict(list)
    for claim in claims:
        result = results.get(claim.source_id or "")
        family = result.syndication_family if result else (claim.source_id or "unknown")
        by_family[family].append(claim)
    return [
        max(
            family_claims,
            key=lambda claim: (
                _freshness(results[claim.source_id or ""]),
                _CONFIDENCE_RANK[claim.confidence],
                str(claim.claim_group_id),
            ),
        )
        for family_claims in by_family.values()
    ]


def _numeric_tolerance(key: str, claims: list[SourceClaim]) -> SourceClaim | None:
    values = [claim.value for claim in claims]
    if not values or any(
        isinstance(value, bool) or not isinstance(value, int | float)
        for value in values
    ):
        return None
    tolerance = SQFT_AGREE_PCT if key == "sqft" else (
        RENT_AGREE_PCT if "rent" in key or key == "all_in_monthly" else None
    )
    if tolerance is None:
        return None
    high = max(float(value) for value in values)
    low = min(float(value) for value in values)
    if high == 0 or ((high - low) / high) * 100 > tolerance:
        return None
    return next(claim for claim in claims if float(claim.value) == high)


async def _equivalence_keys(
    grouped: dict[str, list[SourceClaim]], state: RunState, ctx: StageCtx
) -> dict[tuple[str, UUID], str]:
    """Normalize every genuinely semantic conflict in one structured call."""
    exact = {
        (target_key, claim.claim_group_id): _canonical(claim.value)
        for target_key, claims in grouped.items()
        for claim in claims
    }
    requested: dict[str, tuple[str, UUID]] = {}
    semantic_claims: list[tuple[str, SourceClaim]] = []
    for target_key, claims in grouped.items():
        values = {_canonical(claim.value) for claim in claims}
        if len(values) <= 1 or all(
            isinstance(claim.value, (int, float, bool, type(None)))
            for claim in claims
        ):
            continue
        for claim in claims:
            item_id = f"{target_key}::{claim.claim_group_id}"
            requested[item_id] = (target_key, claim.claim_group_id)
            semantic_claims.append((item_id, claim))
    if not semantic_claims:
        return exact
    content = json.dumps(
        {
            "instruction": (
                "Assign the same equivalence_key only to semantically equivalent rental facts. "
                "Compare only items with the same target_key. Do not choose a winner "
                "and do not infer Floor Plan identity."
            ),
            "claims": [
                {
                    "item_id": item_id,
                    "target_key": item_id.rsplit("::", 1)[0],
                    "criterion_key": claim.criterion_key,
                    "value": claim.value,
                }
                for item_id, claim in semantic_claims
            ],
        },
        sort_keys=True,
    )
    try:
        response = await ctx.call_structured(
            "reconcile_equivalence", EquivalenceResponse, content
        )
        returned = {item.item_id: item.equivalence_key for item in response.items}
        if len(returned) != len(response.items) or set(returned) != set(requested):
            raise ValueError("equivalence response must contain every claim exactly once")
        return {
            **exact,
            **{
                requested[item_id]: equivalence_key
                for item_id, equivalence_key in returned.items()
            },
        }
    except Exception as error:
        log.warning(
            "reconcile_equivalence_fallback",
            job_id=str(state.job_id),
            error=repr(error),
        )
        return exact


def _decision_relevant_keys(ctx: StageCtx) -> set[str]:
    keys = set(_ALL_IN_INPUTS)
    for criterion in ctx.reconcile_rubric or ctx.rubric:
        key = criterion_key(criterion)
        if (
            criterion.non_negotiable is not None
            or criterion.unknown_delta < 0
            or any(
                option.delta < 0 or option.dealbreaker_set_score is not None
                for option in criterion.options
            )
        ):
            keys.add(key)
    return keys


def _gate_keys(ctx: StageCtx) -> set[str]:
    return {
        criterion_key(criterion)
        for criterion in (ctx.reconcile_rubric or ctx.rubric)
        if criterion.non_negotiable is not None
        or any(option.dealbreaker_set_score is not None for option in criterion.options)
    }


def _resolved(
    selected: SourceClaim,
    candidates: list[SourceClaim],
    rule: str,
    *,
    disputed: bool = False,
    confidence: Confidence | None = None,
) -> SourceClaim:
    return selected.model_copy(
        update={
            "confidence": confidence or selected.confidence,
            "resolution_rule": rule,
            "disputed": disputed,
            "candidate_claim_group_ids": [claim.claim_group_id for claim in candidates],
        },
        deep=True,
    )


def _conservative(
    claims: list[SourceClaim], ctx: StageCtx, results: dict[str, SourceResult]
) -> SourceClaim:
    key = claims[0].criterion_key
    if key in {"mandatory_fees", "one_time_fees"}:
        def fee_total(claim: SourceClaim) -> float:
            if not isinstance(claim.value, list):
                return 0.0
            amount_key = "amount_monthly" if key == "mandatory_fees" else "amount"
            return sum(
                float(item.get(amount_key, 0))
                for item in claim.value
                if isinstance(item, dict)
            )

        return max(claims, key=fee_total)
    if key == "pet_costs":
        return max(
            claims,
            key=lambda claim: sum(
                float(value or 0)
                for value in (claim.value.values() if isinstance(claim.value, dict) else [])
            ),
        )
    if key == "utilities_included":
        return min(
            claims,
            key=lambda claim: len(claim.value) if isinstance(claim.value, list) else 0,
        )
    criterion = next((item for item in ctx.rubric if criterion_key(item) == key), None)
    if criterion is not None:
        def delta(claim: SourceClaim) -> float:
            matched = first_match(criterion.options, claim.value)
            return matched.delta if matched is not None else criterion.unknown_delta

        worst = min(delta(claim) for claim in claims)
        return _best_claim([claim for claim in claims if delta(claim) == worst], results)
    numeric = [claim for claim in claims if isinstance(claim.value, int | float)]
    if len(numeric) == len(claims):
        return max(numeric, key=lambda claim: float(claim.value))
    return _best_claim(claims, results)


def _positive_preferred(
    claims: list[SourceClaim], results: dict[str, SourceResult]
) -> SourceClaim | None:
    positives = [
        claim
        for claim in claims
        if claim.value not in (None, False, "none", "not_found")
        and _CONFIDENCE_RANK[claim.confidence] >= _CONFIDENCE_RANK[Confidence.MEDIUM]
    ]
    authoritative_negatives = [
        claim
        for claim in claims
        if claim.value in (False, "none")
        and claim.confidence is Confidence.HIGH
        and results.get(claim.source_id or "") is not None
        and results[claim.source_id or ""].is_official
    ]
    if positives and not authoritative_negatives:
        return _best_claim(positives, results)
    return None


def _official_allowed(state: RunState, result: SourceResult | None) -> bool:
    if result is None:
        return False
    if state.source_policy in {"tiers_1_2_3", "tier_1_plus_official"}:
        return True
    source = next(
        (item for item in state.discovered_sources if item.url == result.source_url),
        None,
    )
    required_tier = source.required_tier if source else 1
    return required_tier <= _POLICY_CAP[state.source_policy]


def _record_round(
    state: RunState,
    *,
    kind: str,
    target_keys: list[str],
    urls: list[str],
    tiers: dict[str, int],
) -> None:
    assert state.plan is not None
    if state.plan.escalation is None:
        state.plan.escalation = PlanEscalation()
    entries = [
        PlanSource(url=url, action="fetch", tier=tiers.get(url, 1))
        for url in urls
    ]
    state.plan.escalation.rounds.append(
        PlanEscalationRound(
            kind=kind,  # type: ignore[arg-type]
            trigger_targets=target_keys,
            sources=entries,
        )
    )
    for entry in entries:
        if not any(item.url == entry.url for item in state.plan.sources):
            state.plan.sources.append(entry)
    insertion = ["FETCH", "EXTRACT", "VERIFY", "RECONCILE"]
    state.plan.stages[state.cursor + 1 : state.cursor + 1] = insertion


def _plan_official(state: RunState, target_keys: list[str]) -> bool:
    if (
        state.plan is None
        or state.reconcile_escalation.official_attempted
        or state.source_policy == "trust_link"
        or not state.official_source_url
    ):
        return False
    if any(
        result.source_url == state.official_source_url
        for result in state.source_results
    ):
        state.reconcile_escalation.official_attempted = True
        return False
    discovered = next(
        (item for item in state.discovered_sources if item.url == state.official_source_url),
        None,
    )
    tier = discovered.required_tier if discovered else 1
    if (
        state.source_policy not in {"tiers_1_2_3", "tier_1_plus_official"}
        and tier > _POLICY_CAP[state.source_policy]
    ):
        state.reconcile_escalation.official_attempted = True
        return False
    url = state.official_source_url
    state.reconcile_escalation.official_attempted = True
    state.reconcile_escalation.source_urls_tried.append(url)
    state.slate_urls.append(url)
    existing = next((source for source in state.sources if source.url == url), None)
    if existing is not None:
        existing.is_official = True
        existing.role = "official_arbiter"
    _record_round(
        state,
        kind="official_arbiter",
        target_keys=target_keys,
        urls=[url],
        tiers={url: tier},
    )
    return True


def _plan_sibling_round(state: RunState, target_keys: list[str]) -> bool:
    if (
        state.plan is None
        or state.reconcile_escalation.sibling_rounds_used >= ESCALATION_MAX_SIBLING_ROUNDS
    ):
        return False
    used_urls = {result.source_url for result in state.source_results}
    used_families = {result.syndication_family for result in state.source_results}
    selected = []
    used_tiers: set[int] = set()
    for candidate in sorted(state.discovered_sources, key=lambda item: (item.rank, item.url)):
        if (
            candidate.is_official
            or candidate.url in used_urls
            or candidate.syndication_family in used_families
            or candidate.required_tier > _POLICY_CAP[state.source_policy]
            or candidate.required_tier in used_tiers
        ):
            continue
        selected.append(candidate)
        used_families.add(candidate.syndication_family)
        used_tiers.add(candidate.required_tier)
        if len(selected) == ESCALATION_MAX_SIBLING_SOURCES:
            break
    state.reconcile_escalation.sibling_rounds_used += 1
    if not selected:
        return False
    urls = [item.url for item in selected]
    state.reconcile_escalation.source_urls_tried.extend(urls)
    state.slate_urls.extend(urls)
    _record_round(
        state,
        kind="sibling_round",
        target_keys=target_keys,
        urls=urls,
        tiers={item.url: item.required_tier for item in selected},
    )
    return True


def _apply_dispute_answer(state: RunState) -> bool:
    pending = state.pending_dispute
    answer = state.checkpoint_answer
    if pending is None or not answer:
        return False
    choice = answer.get("choice")
    candidates = pending.candidate_claims
    if choice == "Leave unknown":
        selected = candidates[0].model_copy(
            update={"value": None, "confidence": Confidence.NOT_FOUND}
        )
        resolution = _resolved(
            selected, candidates, "dispute_left_unknown", disputed=True
        )
    else:
        group_id = pending.option_claim_groups.get(str(choice))
        selected = next(
            (claim for claim in candidates if claim.claim_group_id == group_id),
            None,
        )
        if selected is None:
            return False
        resolution = _resolved(selected, candidates, "user_dispute_resolution")
    state.resolved_claims.append(resolution)
    state.reconcile_escalation.settled_targets.append(pending.target_key)
    state.pending_dispute = None
    state.checkpoint_answer = None
    return True


def _apply_auxiliary_resolutions(state: RunState) -> None:
    by_key = {claim.criterion_key: claim for claim in state.resolved_claims}
    pet = by_key.get("pet_costs")
    if pet is not None and isinstance(pet.value, dict):
        state.pet_costs = PetCostsIn.model_validate(
            {**pet.value, "evidence_quote": pet.evidence_quote}
        )
    utilities = by_key.get("utilities_included")
    if utilities is not None and isinstance(utilities.value, list):
        state.utilities = UtilitiesIn(
            included=utilities.value,
            evidence_quote=utilities.evidence_quote,
        )
    mandatory = by_key.get("mandatory_fees")
    if mandatory is not None and isinstance(mandatory.value, list):
        state.mandatory_fees = MandatoryFeesIn(
            fees=mandatory.value,
            evidence_quote=mandatory.evidence_quote,
        )
    one_time = by_key.get("one_time_fees")
    if one_time is not None and isinstance(one_time.value, list):
        state.one_time_fees = OneTimeFeesIn(
            fees=one_time.value,
            evidence_quote=one_time.evidence_quote,
        )


def _checkpoint_for(
    state: RunState, target_key: str, claims: list[SourceClaim]
) -> None:
    labels: dict[str, UUID] = {}
    for claim in claims:
        host = (urlsplit(claim.source_id or "").hostname or claim.source_id or "Source")
        base = f"{claim.value!s} — {host}"
        label = base
        suffix = 2
        while label in labels:
            label = f"{base} ({suffix})"
            suffix += 1
        labels[label] = claim.claim_group_id
    state.pending_dispute = PendingDispute(
        target_key=target_key,
        option_claim_groups=labels,
        candidate_claims=claims,
    )
    options = [*labels, "Leave unknown"]
    raise CheckpointRaised(
        CheckpointPrompt(
            kind=CheckpointKind.RESOLVE_DISPUTE,
            question=f"Sources disagree on {claims[0].criterion_key}. Which value should be used?",
            options=options,
            default="Leave unknown",
            context_ref=target_key,
        )
    )


async def reconcile_stage(state: RunState, ctx: StageCtx) -> RunState:
    """Resolve verified candidates and schedule at most one official + sibling round."""
    if not ctx.reconcile_rubric and state.property_id is not None:
        ctx.reconcile_rubric = await ctx.reconcile_rubric_lookup(state.property_id)
    if state.plan is not None and state.plan.escalation is not None:
        verified_urls = {
            result.source_url for result in state.source_results if result.verified
        }
        for round_ in state.plan.escalation.rounds:
            if round_.status == "planned" and all(
                source.url in verified_urls for source in round_.sources
            ):
                round_.status = "completed"
                round_.rung_reached = round_.kind
    _apply_dispute_answer(state)
    if not state.source_results:
        state.resolved_claims = [
            _resolved(claim, [claim], "single_source") for claim in state.source_claims
        ]
        _apply_auxiliary_resolutions(state)
        return state

    results = {result.source_url: result for result in state.source_results if result.verified}
    grouped: dict[str, list[SourceClaim]] = defaultdict(list)
    for result in results.values():
        for claim in result.source_claims:
            grouped[_target_key(claim)].append(claim)
    settled = set(state.reconcile_escalation.settled_targets)
    vote_groups = {
        target_key: _family_dedup(raw_claims, results)
        for target_key, raw_claims in grouped.items()
        if target_key not in settled
    }
    equivalence_keys = await _equivalence_keys(vote_groups, state, ctx)

    decision_relevant = _decision_relevant_keys(ctx)
    gate_keys = _gate_keys(ctx)
    unresolved: dict[str, list[SourceClaim]] = {}

    for target_key, raw_claims in sorted(grouped.items()):
        if target_key in settled:
            continue
        claims = _family_dedup(raw_claims, results)
        if len(claims) == 1:
            state.resolved_claims.append(_resolved(claims[0], raw_claims, "single_source"))
            state.reconcile_escalation.settled_targets.append(target_key)
            continue

        tolerance = _numeric_tolerance(claims[0].criterion_key, claims)
        if tolerance is not None:
            state.resolved_claims.append(
                _resolved(tolerance, raw_claims, "numeric_tolerance_conservative")
            )
            state.reconcile_escalation.settled_targets.append(target_key)
            continue

        classes: dict[str, list[SourceClaim]] = defaultdict(list)
        for claim in claims:
            classes[equivalence_keys[(target_key, claim.claim_group_id)]].append(claim)
        winner = max(classes.values(), key=len)
        if len(winner) / len(claims) >= RECONCILE_SUPERMAJORITY:
            selected = _best_claim(winner, results)
            # Value agreement does not invent applicability. Per DESIGN v3.21,
            # the best verified/fresh evidence supplies generalized scope.
            state.resolved_claims.append(
                _resolved(selected, raw_claims, "family_supermajority")
            )
            state.reconcile_escalation.settled_targets.append(target_key)
            continue

        official = [
            claim
            for claim in claims
            if results[claim.source_id or ""].is_official
            and _CONFIDENCE_RANK[claim.confidence] >= _CONFIDENCE_RANK[Confidence.MEDIUM]
        ]
        if official and _official_allowed(state, results[official[0].source_id or ""]):
            state.resolved_claims.append(
                _resolved(_best_claim(official, results), raw_claims, "official_arbiter")
            )
            state.reconcile_escalation.settled_targets.append(target_key)
            continue

        policy = _CATALOG.get(claims[0].criterion_key)
        positive = (
            _positive_preferred(claims, results)
            if policy is not None
            and policy.conflict_policy is ConflictPolicy.VERIFIED_POSITIVE_PREFERRED
            else None
        )
        if positive is not None and claims[0].criterion_key not in gate_keys:
            state.resolved_claims.append(
                _resolved(
                    positive,
                    raw_claims,
                    "verified_positive_preferred",
                    disputed=True,
                )
            )
            state.reconcile_escalation.settled_targets.append(target_key)
            continue

        may_escalate = claims[0].criterion_key in decision_relevant and (
            policy is None
            or policy.escalation_policy is EscalationPolicy.DECISION_RELEVANT
            or claims[0].criterion_key in gate_keys
        )
        if may_escalate:
            unresolved[target_key] = raw_claims
            continue

        majority = max(classes.values(), key=len)
        if len(majority) / len(claims) > 0.5:
            selected = _best_claim(majority, results)
            state.resolved_claims.append(_resolved(selected, raw_claims, "family_majority"))
        else:
            selected = _conservative(claims, ctx, results)
            state.resolved_claims.append(
                _resolved(
                    selected,
                    raw_claims,
                    "conservative_disputed",
                    disputed=True,
                    confidence=Confidence.LOW,
                )
            )
        state.reconcile_escalation.settled_targets.append(target_key)

    target_keys = list(unresolved)
    if target_keys and _plan_official(state, target_keys):
        return state
    if target_keys and _plan_sibling_round(state, target_keys):
        return state

    for target_key, raw_claims in unresolved.items():
        claims = _family_dedup(raw_claims, results)
        classes: dict[str, list[SourceClaim]] = defaultdict(list)
        for claim in claims:
            classes[equivalence_keys[(target_key, claim.claim_group_id)]].append(claim)
        winner = max(classes.values(), key=len)
        if len(winner) / len(claims) > 0.5:
            selected = _best_claim(winner, results)
            state.resolved_claims.append(_resolved(selected, raw_claims, "family_majority"))
            state.reconcile_escalation.settled_targets.append(target_key)
            continue
        selected = _conservative(claims, ctx, results)
        state.resolved_claims.append(
            _resolved(
                selected,
                raw_claims,
                "conservative_disputed",
                disputed=True,
                confidence=Confidence.LOW,
            )
        )
        state.reconcile_escalation.settled_targets.append(target_key)
        if raw_claims[0].criterion_key in gate_keys:
            _checkpoint_for(state, target_key, raw_claims)

    state.floor_plans = [
        plan.model_copy(deep=True)
        for result in state.source_results
        for plan in result.floor_plans
    ]
    _apply_auxiliary_resolutions(state)
    log.info(
        "reconciled",
        job_id=str(state.job_id),
        candidates=sum(len(result.source_claims) for result in state.source_results),
        resolved=len(state.resolved_claims),
        model=model_for_stage("reconcile_equivalence"),
    )
    return state
