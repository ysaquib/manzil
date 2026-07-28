"""VERIFY stage (P0-9, DESIGN §10.5): per-source audit — the anti-hallucination
and primary anti-prompt-injection control (§16).

Checks 1-3 are deterministic code (P2 discipline: resist making them
smarter); check 4 is exactly one cheap P1 call. Failures demote confidence to
`low` and record a VerifyFlag; the value is kept — provenance shows the doubt.
Phase 1 (P1-14): gate-relevant demotions below `min_confidence` raise a
`confirm_value` checkpoint; the resume path upgrades confidence on "yes".
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import structlog
from manzil_shared.catalog import SCOPED_UNIT_CLAIM_KEYS
from manzil_shared.config import (
    DEPOSIT_MAX_RENT_MULTIPLIER,
    EVIDENCE_FUZZY_THRESHOLD,
    RENT_PLAUSIBLE_MAX,
    RENT_PLAUSIBLE_MIN,
    SQFT_PER_BED_MAX,
    SQFT_PER_BED_MIN,
)
from manzil_shared.errors import CheckpointRaised
from manzil_shared.models import (
    CheckpointKind,
    CheckpointPrompt,
    Confidence,
    RubricCriterion,
    TargetScope,
    UnitApplicability,
)
from manzil_shared.scoring.engine import criterion_key
from pydantic import BaseModel, Field, ValidationError
from rapidfuzz import fuzz

from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.schema_gen import extractable_entries, field_model
from manzil_worker.stages.score import meets_confidence
from manzil_worker.state import RunState, SourceClaim, VerifyCheck, VerifyFlag

log = structlog.get_logger()


class Contradiction(BaseModel):
    criterion_key: str
    note: str


class ConsistencyReport(BaseModel):
    contradictions: list[Contradiction] = Field(default_factory=list)


def _demote(
    state: RunState, extraction: SourceClaim, key: str, check: VerifyCheck, note: str
) -> None:
    if extraction.confidence in (Confidence.HIGH, Confidence.MEDIUM):
        extraction.confidence = Confidence.LOW
    state.verify_flags.append(
        VerifyFlag(criterion_key=key, check=check, note=note, source_id=extraction.source_id)
    )


def _flag(state: RunState, key: str, check: VerifyCheck, note: str, source_id: str) -> None:
    state.verify_flags.append(
        VerifyFlag(criterion_key=key, check=check, note=note, source_id=source_id)
    )


_ELLIPSIS_RE = re.compile(r"\s*(?:\.{3,}|…)\s*")
_MIN_FRAGMENT_LEN = 4
_WHITESPACE_RE = re.compile(r"\s+")


def _fragment_locatable(fragment: str, page_text: str) -> bool:
    if fuzz.partial_ratio(fragment.lower(), page_text.lower()) >= EVIDENCE_FUZZY_THRESHOLD:
        return True
    # Whitespace divergence must not demote: models often quote pretty-printed
    # JSON ({"a": 1}) while the page's embedded digest is compact ({"a":1}). Retry
    # with all whitespace stripped from both sides before giving up on a fragment.
    stripped_fragment = _WHITESPACE_RE.sub("", fragment).lower()
    stripped_page = _WHITESPACE_RE.sub("", page_text).lower()
    return fuzz.partial_ratio(stripped_fragment, stripped_page) >= EVIDENCE_FUZZY_THRESHOLD


def evidence_locatable(quote: str, page_text: str) -> bool:
    """Check 1: the quote must fuzzy-match text actually present in the page.

    Models stitch multiple VERBATIM fragments with an ellipsis ("A … B") when a
    fact spans locations; each fragment is on the page but the stitched whole is
    not, which would falsely demote. So the quote is split on ellipsis separators
    and every non-trivial fragment must locate independently. A quote with no
    ellipsis is a single fragment and matches exactly as before.
    """
    fragments = [f for f in _ELLIPSIS_RE.split(quote) if len(f.strip()) >= _MIN_FRAGMENT_LEN]
    if not fragments:
        # Nothing survived the length filter (e.g. a very short no-ellipsis quote)
        # — fall back to matching the whole quote, preserving prior behavior.
        fragments = [quote]
    return all(_fragment_locatable(fragment, page_text) for fragment in fragments)


def _check_evidence(state: RunState, page_text: str) -> None:
    for claim in state.source_claims:
        if claim.value is None:
            continue
        if not claim.evidence_quote:
            _demote(
                state,
                claim,
                claim.criterion_key,
                "evidence",
                "non-null value without evidence quote",
            )
        elif not evidence_locatable(claim.evidence_quote, page_text):
            _demote(
                state,
                claim,
                claim.criterion_key,
                "evidence",
                f"evidence quote not found in page: {claim.evidence_quote!r}",
            )
    for plan in state.floor_plans:
        if plan.evidence_quote and not evidence_locatable(plan.evidence_quote, page_text):
            _flag(
                state,
                "floor_plans",
                "evidence",
                f"plan {plan.plan_name!r}: evidence quote not found in page",
                state.sources[0].url,
            )


_FIELD_MODELS = {entry.key: field_model(entry) for entry in extractable_entries()}


def _check_conformance(state: RunState) -> None:
    """Check 2: schema conformance re-checked post-parse — guards against any
    mutation between EXTRACT and here."""
    plan_refs = {plan.response_key for plan in state.floor_plans if plan.response_key is not None}
    for claim in state.source_claims:
        key = claim.criterion_key
        model = _FIELD_MODELS.get(key)
        if model is None:
            continue
        if claim.target_scope.value == "floor_plan" and (
            claim.floor_plan_ref is None or claim.floor_plan_ref not in plan_refs
        ):
            _demote(
                state,
                claim,
                key,
                "conformance",
                "exact claim references no Source-local Floor Plan in this response",
            )
        exact = claim.applicability is UnitApplicability.SPECIFIC_FLOOR_PLANS
        if exact != (claim.target_scope is TargetScope.FLOOR_PLAN):
            _demote(
                state,
                claim,
                key,
                "conformance",
                "specific applicability and Floor Plan target must appear together",
            )
        if (
            claim.target_scope is TargetScope.PROPERTY
            and claim.applicability is None
            and (key in SCOPED_UNIT_CLAIM_KEYS or key == "heating_type")
        ):
            # True Property facts are valid; the migrated unit tranche and
            # heating_type must never fall back to the legacy shape.
            _demote(
                state,
                claim,
                key,
                "conformance",
                "scoped unit claim is missing unit applicability",
            )
        if claim.value is None:
            continue
        if key == "heating_type":
            if claim.value not in {"gas", "electric"}:
                _demote(
                    state,
                    claim,
                    key,
                    "conformance",
                    "heating_type must be gas or electric",
                )
            continue
        try:
            model.model_validate({"value": claim.value, "confidence": "high"})
        except ValidationError as error:
            _demote(
                state,
                claim,
                key,
                "conformance",
                f"value no longer conforms to catalog schema: {error.errors()[0]['msg']}",
            )


def _first_value(state: RunState, key: str) -> tuple[SourceClaim | None, Any]:
    claim = next(
        (
            claim
            for claim in state.source_claims
            if claim.criterion_key == key and claim.value is not None
        ),
        None,
    )
    if claim is not None:
        return claim, claim.value
    return None, None


def _check_plausibility(state: RunState, today: date) -> None:
    source_url = state.sources[0].url

    # Floor plans: rent band, sqft/bed ratio, deposit multiple, availability.
    plan_rents: list[float] = []
    for plan in state.floor_plans:
        label = plan.plan_name or "unnamed"
        for rent in (plan.rent_min, plan.rent_max):
            if rent is None:
                continue
            plan_rents.append(rent)
            if not RENT_PLAUSIBLE_MIN <= rent <= RENT_PLAUSIBLE_MAX:
                _flag(
                    state,
                    "floor_plans",
                    "plausibility",
                    f"plan {label!r}: rent {rent} outside "
                    f"[{RENT_PLAUSIBLE_MIN}, {RENT_PLAUSIBLE_MAX}]",
                    source_url,
                )
        sqft = plan.sqft_min or plan.sqft_max
        if plan.beds and sqft is not None:
            ratio = sqft / plan.beds
            if not SQFT_PER_BED_MIN <= ratio <= SQFT_PER_BED_MAX:
                _flag(
                    state,
                    "floor_plans",
                    "plausibility",
                    f"plan {label!r}: {sqft} sqft / {plan.beds} beds = {ratio:.0f} outside "
                    f"[{SQFT_PER_BED_MIN}, {SQFT_PER_BED_MAX}]",
                    source_url,
                )
        rent_basis = plan.rent_min or plan.rent_max
        if (
            plan.deposit is not None
            and rent_basis
            and plan.deposit > DEPOSIT_MAX_RENT_MULTIPLIER * rent_basis
        ):
            _flag(
                state,
                "floor_plans",
                "plausibility",
                f"plan {label!r}: deposit {plan.deposit} exceeds "
                f"{DEPOSIT_MAX_RENT_MULTIPLIER}x rent {rent_basis}",
                source_url,
            )
        if plan.availability_date is not None and plan.availability_date < today.isoformat():
            _flag(
                state,
                "floor_plans",
                "plausibility",
                f"plan {label!r}: availability {plan.availability_date} is in the past",
                source_url,
            )

    # Criterion-level values.
    deposit_ext, deposit = _first_value(state, "security_deposit")
    if (
        deposit_ext is not None
        and plan_rents
        and deposit > DEPOSIT_MAX_RENT_MULTIPLIER * min(plan_rents)
    ):
        _demote(
            state,
            deposit_ext,
            "security_deposit",
            "plausibility",
            f"deposit {deposit} exceeds {DEPOSIT_MAX_RENT_MULTIPLIER}x "
            f"lowest advertised rent {min(plan_rents)}",
        )
    sqft_ext, sqft_value = _first_value(state, "sqft")
    _, beds_value = _first_value(state, "beds")
    if sqft_ext is not None and isinstance(beds_value, int) and beds_value > 0:
        ratio = sqft_value / beds_value
        if not SQFT_PER_BED_MIN <= ratio <= SQFT_PER_BED_MAX:
            _demote(
                state,
                sqft_ext,
                "sqft",
                "plausibility",
                f"{sqft_value} sqft / {beds_value} beds = {ratio:.0f} outside "
                f"[{SQFT_PER_BED_MIN}, {SQFT_PER_BED_MAX}]",
            )
    avail_ext, avail = _first_value(state, "availability_date")
    if avail_ext is not None and isinstance(avail, str) and avail < today.isoformat():
        _demote(
            state,
            avail_ext,
            "availability_date",
            "plausibility",
            f"availability {avail} is in the past",
        )


async def _check_consistency(state: RunState, ctx: StageCtx, page_text: str) -> None:
    """Check 4 — the one narrow LLM judgment in this P2 stage."""
    known = [claim for claim in state.source_claims if claim.value is not None]
    if not known:
        return
    lines = [
        f"- {claim.criterion_key}: {claim.value!r}; "
        f"target={claim.target_scope.value}; "
        f"applicability={claim.applicability.value if claim.applicability else None}; "
        f"floor_plan_ref={claim.floor_plan_ref!r} "
        f"(evidence: {claim.evidence_quote!r})"
        for claim in known
    ]
    for plan in state.floor_plans:
        lines.append(f"- floor plan: {plan.model_dump(exclude_none=True)!r}")
    content = "Extracted values:\n" + "\n".join(lines) + f"\n\nPage text:\n{page_text}"
    report = await ctx.call_structured("verify", ConsistencyReport, content)
    for contradiction in report.contradictions:
        claim = next(
            (
                claim
                for claim in state.source_claims
                if claim.criterion_key == contradiction.criterion_key and claim.value is not None
            ),
            None,
        )
        if claim is not None:
            _demote(
                state,
                claim,
                contradiction.criterion_key,
                "consistency",
                contradiction.note,
            )
        else:
            _flag(
                state,
                contradiction.criterion_key,
                "consistency",
                contradiction.note,
                state.sources[0].url,
            )


def _is_gate_relevant(criterion: RubricCriterion) -> bool:
    if criterion.non_negotiable is not None:
        return True
    return any(o.dealbreaker_set_score is not None for o in criterion.options)


def _criterion_by_key(ctx: StageCtx) -> dict[str, RubricCriterion]:
    return {criterion_key(c): c for c in ctx.rubric}


def _apply_checkpoint_answer(state: RunState, ctx: StageCtx) -> None:
    answer = state.checkpoint_answer
    if not answer:
        return
    key = answer.get("context_ref")
    choice = answer.get("choice", "yes")
    if key and choice == "yes":
        claim = next((claim for claim in state.source_claims if claim.criterion_key == key), None)
        if claim is not None:
            claim.confidence = ctx.min_confidence
    if key:
        state.confirm_value_resolved.append(key)
    state.checkpoint_answer = None


def _maybe_raise_confirm_value(state: RunState, ctx: StageCtx) -> None:
    by_key = _criterion_by_key(ctx)
    for flag in state.verify_flags:
        if flag.criterion_key in state.confirm_value_resolved:
            continue
        criterion = by_key.get(flag.criterion_key)
        if criterion is None or not _is_gate_relevant(criterion):
            continue
        extraction = next(
            (claim for claim in state.source_claims if claim.criterion_key == flag.criterion_key),
            None,
        )
        if extraction is None or extraction.value is None:
            continue
        if meets_confidence(extraction.confidence, ctx.min_confidence):
            continue
        label = criterion.catalog_key or str(
            (criterion.custom_def or {}).get("label", flag.criterion_key)
        )
        prompt = CheckpointPrompt(
            kind=CheckpointKind.CONFIRM_VALUE,
            question=(
                f"VERIFY flagged {label} = {extraction.value!r} ({flag.note}). "
                "Accept at low confidence?"
            ),
            options=["yes", "no"],
            default="yes",
            context_ref=flag.criterion_key,
        )
        raise CheckpointRaised(prompt)


async def _verify_single(
    state: RunState, ctx: StageCtx, *, allow_checkpoint: bool = True
) -> RunState:
    page_text = state.sources[0].cleaned_text
    _check_evidence(state, page_text)
    _check_conformance(state)
    _check_plausibility(state, ctx.today())
    await _check_consistency(state, ctx, page_text)
    _apply_checkpoint_answer(state, ctx)
    if allow_checkpoint:
        _maybe_raise_confirm_value(state, ctx)
    log.info(
        "verified",
        job_id=str(state.job_id),
        stage="verify",
        flags=len(state.verify_flags),
    )
    return state


async def verify_stage(state: RunState, ctx: StageCtx) -> RunState:
    """VERIFY every Source slice without allowing one suspect sibling to park
    the run before RECONCILE can use stronger evidence from another Source."""
    multi_source = state.plan is not None and "RECONCILE" in state.plan.stages
    if not multi_source or not state.source_results:
        return await _verify_single(state, ctx)

    for result in state.source_results:
        if result.verified:
            continue
        source = next((item for item in state.sources if item.url == result.source_url), None)
        if source is None:
            continue
        isolated = state.model_copy(deep=True)
        isolated.sources = [source.model_copy(deep=True)]
        isolated.source_claims = [claim.model_copy(deep=True) for claim in result.source_claims]
        isolated.floor_plans = [plan.model_copy(deep=True) for plan in result.floor_plans]
        isolated.property_identity = result.property_identity
        isolated.pet_costs = result.pet_costs
        isolated.utilities = result.utilities
        isolated.mandatory_fees = result.mandatory_fees
        isolated.heating = result.heating
        isolated.one_time_fees = result.one_time_fees
        isolated.property_contact = result.property_contact
        isolated.verify_flags = []
        verified = await _verify_single(isolated, ctx, allow_checkpoint=False)
        result.source_claims = verified.source_claims
        result.floor_plans = verified.floor_plans
        result.verify_flags = verified.verify_flags
        result.verified = True

    primary = next(
        (result for result in state.source_results if result.source_url == state.url),
        None,
    )
    if primary is not None:
        state.source_claims = [claim.model_copy(deep=True) for claim in primary.source_claims]
        state.floor_plans = [plan.model_copy(deep=True) for plan in primary.floor_plans]
        state.verify_flags = [flag.model_copy(deep=True) for flag in primary.verify_flags]
    return state
