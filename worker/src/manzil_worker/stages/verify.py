"""VERIFY stage (P0-9, DESIGN §10.5): per-source audit — the anti-hallucination
and primary anti-prompt-injection control (§16).

Checks 1-3 are deterministic code (P2 discipline: resist making them
smarter); check 4 is exactly one cheap P1 call. Failures demote confidence to
`low` and record a VerifyFlag; the value is kept — provenance shows the doubt.
Phase 1 (P1-14): gate-relevant demotions below `min_confidence` raise a
`confirm_value` checkpoint; the resume path upgrades confidence on "yes".
"""

from __future__ import annotations

from datetime import date
from typing import Any

import structlog
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
)
from manzil_shared.scoring.engine import criterion_key
from pydantic import BaseModel, Field, ValidationError
from rapidfuzz import fuzz

from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.schema_gen import extractable_entries, field_model
from manzil_worker.stages.score import meets_confidence
from manzil_worker.state import FieldExtraction, RunState, VerifyCheck, VerifyFlag

log = structlog.get_logger()


class Contradiction(BaseModel):
    criterion_key: str
    note: str


class ConsistencyReport(BaseModel):
    contradictions: list[Contradiction] = Field(default_factory=list)


def _demote(
    state: RunState, extraction: FieldExtraction, key: str, check: VerifyCheck, note: str
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


def evidence_locatable(quote: str, page_text: str) -> bool:
    """Check 1: the quote must fuzzy-match text actually present in the page."""
    return fuzz.partial_ratio(quote.lower(), page_text.lower()) >= EVIDENCE_FUZZY_THRESHOLD


def _check_evidence(state: RunState, page_text: str) -> None:
    for key, extractions in state.extractions.items():
        for extraction in extractions:
            if extraction.value is None:
                continue
            if not extraction.evidence_quote:
                _demote(state, extraction, key, "evidence", "non-null value without evidence quote")
            elif not evidence_locatable(extraction.evidence_quote, page_text):
                _demote(
                    state,
                    extraction,
                    key,
                    "evidence",
                    f"evidence quote not found in page: {extraction.evidence_quote!r}",
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
    for key, extractions in state.extractions.items():
        model = _FIELD_MODELS.get(key)
        if model is None:
            continue
        for extraction in extractions:
            if extraction.value is None:
                continue
            try:
                model.model_validate({"value": extraction.value, "confidence": "high"})
            except ValidationError as error:
                _demote(
                    state,
                    extraction,
                    key,
                    "conformance",
                    f"value no longer conforms to catalog schema: {error.errors()[0]['msg']}",
                )


def _first_value(state: RunState, key: str) -> tuple[FieldExtraction | None, Any]:
    extractions = state.extractions.get(key, [])
    if extractions and extractions[0].value is not None:
        return extractions[0], extractions[0].value
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
    known = {
        key: {"value": exts[0].value, "evidence": exts[0].evidence_quote}
        for key, exts in state.extractions.items()
        if exts and exts[0].value is not None
    }
    if not known:
        return
    lines = [
        f"- {key}: {entry['value']!r} (evidence: {entry['evidence']!r})"
        for key, entry in known.items()
    ]
    for plan in state.floor_plans:
        lines.append(f"- floor plan: {plan.model_dump(exclude_none=True)!r}")
    content = "Extracted values:\n" + "\n".join(lines) + f"\n\nPage text:\n{page_text}"
    report = await ctx.call_structured("verify", ConsistencyReport, content)
    for contradiction in report.contradictions:
        extractions = state.extractions.get(contradiction.criterion_key)
        if extractions and extractions[0].value is not None:
            _demote(
                state,
                extractions[0],
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
        extractions = state.extractions.get(key, [])
        if extractions:
            extractions[0].confidence = ctx.min_confidence
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
        extractions = state.extractions.get(flag.criterion_key, [])
        if not extractions or extractions[0].value is None:
            continue
        extraction = extractions[0]
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


async def verify_stage(state: RunState, ctx: StageCtx) -> RunState:
    page_text = state.sources[0].cleaned_text
    _check_evidence(state, page_text)
    _check_conformance(state)
    _check_plausibility(state, ctx.today())
    await _check_consistency(state, ctx, page_text)
    _apply_checkpoint_answer(state, ctx)
    _maybe_raise_confirm_value(state, ctx)
    log.info(
        "verified",
        job_id=str(state.job_id),
        stage="verify",
        flags=len(state.verify_flags),
    )
    return state
