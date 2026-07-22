"""EXTRACT stage (P0-8, DESIGN §10.2 P1, §10.3).

Full-catalog structured extraction from cleaned text through the forced-tool
schema generated from `criteria_catalog`. Zero tools by design (§16) — the
page is untrusted input; worst-case injection is a bad value for VERIFY to
catch, never an action.

Validation failure handling per §10.2 P1: retry once with the validation
error appended to the content; a second failure raises ExtractionInvalid
(job error), not another retry.
"""

from __future__ import annotations

import structlog
from manzil_shared.errors import ExtractionInvalid
from manzil_shared.models import FactScope, TargetScope, UnitApplicability
from pydantic import ValidationError

from manzil_worker.llm.config import model_for_stage
from manzil_worker.llm.prompt_loader import load_prompt
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.schema_gen import build_extraction_schema, extractable_entries
from manzil_worker.state import (
    FloorPlanIn,
    HeatingIn,
    MandatoryFeesIn,
    OneTimeFeesIn,
    PetCostsIn,
    PropertyIdentityIn,
    RunState,
    SourceClaim,
    UtilitiesIn,
)

log = structlog.get_logger()

# Transient EXTRACT token for immediate-availability phrasing ("Available Now",
# "Now", "Immediately"). Rewritten to ctx.today() before VERIFY/persist —
# never stored or scored (DESIGN §20 2026-07-16).
AVAILABLE_NOW_SENTINEL = "available_now"


def normalize_availability_dates(state: RunState, today_iso: str) -> None:
    """Rewrite available_now sentinels to the run date in place."""
    for claim in state.source_claims:
        if claim.criterion_key == "availability_date" and claim.value == AVAILABLE_NOW_SENTINEL:
            claim.value = today_iso
    for plan in state.floor_plans:
        if plan.availability_date == AVAILABLE_NOW_SENTINEL:
            plan.availability_date = today_iso


async def extract_stage(state: RunState, ctx: StageCtx) -> RunState:
    source = state.sources[0]
    schema = build_extraction_schema()
    content = f"URL: {source.url}\n\n{source.cleaned_text}"

    try:
        extraction = await ctx.call_structured("extract", schema, content)
    except ValidationError as first_error:
        log.warning(
            "extract_invalid_retry",
            job_id=str(state.job_id),
            stage="extract",
            errors=first_error.error_count(),
        )
        # Correction leads the content: appended at the end of a 30k-char page
        # it gets ignored (observed: byte-identical retry output at temp 0).
        corrective = (
            "Your previous attempt failed schema validation — emit a corrected "
            "result. Most common cause: a criterion field emitted as a "
            "JSON-encoded STRING. Every criterion field must be a JSON OBJECT "
            "with keys value/confidence/evidence_quote (floor_plans a JSON "
            "array); the tool call handles all escaping, including quotes "
            f"inside evidence. The validation errors:\n{first_error}\n\n{content}"
        )
        try:
            extraction = await ctx.call_structured("extract", schema, corrective)
        except ValidationError as second_error:
            raise ExtractionInvalid(
                f"extraction failed schema validation twice: {second_error}"
            ) from second_error

    model = model_for_stage("extract")
    prompt_version = load_prompt("extract").version
    state.source_claims = []
    for entry in extractable_entries():
        raw = getattr(extraction, entry.key)
        generalized_unit = entry.fact_scope in {FactScope.FLOOR_PLAN, FactScope.MIXED}
        state.source_claims.append(
            SourceClaim(
                criterion_key=entry.key,
                value=raw.value,
                confidence=raw.confidence,
                evidence_quote=raw.evidence_quote,
                source_id=source.url,
                model=model,
                prompt_version=prompt_version,
                target_scope=TargetScope.PROPERTY,
                applicability=(
                    UnitApplicability.UNIT_SCOPE_UNSPECIFIED if generalized_unit else None
                ),
            )
        )
    plans = extraction.floor_plans
    assert isinstance(plans, list)
    state.floor_plans = [FloorPlanIn.model_validate(p, from_attributes=True) for p in plans]
    identity = extraction.property_identity
    state.property_identity = (
        PropertyIdentityIn.model_validate(identity, from_attributes=True)
        if identity is not None
        else None
    )
    pet_costs = extraction.pet_costs
    state.pet_costs = (
        PetCostsIn.model_validate(pet_costs, from_attributes=True)
        if pet_costs is not None
        else None
    )
    utilities = extraction.utilities
    state.utilities = (
        UtilitiesIn.model_validate(utilities, from_attributes=True)
        if utilities is not None
        else None
    )
    # §9.5 P3-9 blocks — absent on pre-P3-9 recordings, so getattr-with-None.
    mandatory_fees = getattr(extraction, "mandatory_fees", None)
    state.mandatory_fees = (
        MandatoryFeesIn.model_validate(mandatory_fees, from_attributes=True)
        if mandatory_fees is not None
        else None
    )
    heating = getattr(extraction, "heating", None)
    state.heating = (
        HeatingIn.model_validate(heating, from_attributes=True) if heating is not None else None
    )
    one_time = getattr(extraction, "one_time_fees", None)
    state.one_time_fees = (
        OneTimeFeesIn.model_validate(one_time, from_attributes=True)
        if one_time is not None
        else None
    )
    normalize_availability_dates(state, ctx.today().isoformat())
    source.authoritative_extraction = True
    log.info(
        "extracted",
        job_id=str(state.job_id),
        stage="extract",
        fields=len(state.source_claims),
        floor_plans=len(state.floor_plans),
        identity=state.property_identity is not None,
        pet_costs=state.pet_costs is not None,
        utilities=state.utilities is not None,
    )
    return state
