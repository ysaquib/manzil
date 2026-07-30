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

import json
from uuid import uuid4

import structlog
from manzil_shared.catalog import SCOPED_UNIT_CLAIM_KEYS, TYPED_MULTI_CLAIM_KEYS
from manzil_shared.errors import ExtractionInvalid
from manzil_shared.models import Confidence, FactScope, TargetScope, UnitApplicability
from pydantic import ValidationError

from manzil_worker.llm.config import model_for_stage
from manzil_worker.llm.prompt_loader import load_prompt
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.schema_gen import build_extraction_schema, extractable_entries
from manzil_worker.state import (
    FloorPlanIn,
    MandatoryFeesIn,
    OneTimeFeesIn,
    PetCostsIn,
    PropertyContactIn,
    PropertyIdentityIn,
    RunState,
    SourceClaim,
    SourceResult,
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


async def _extract_single(state: RunState, ctx: StageCtx) -> RunState:
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
            "result. Most common cause: a field emitted as a JSON-encoded "
            "STRING. Property criterion fields must be JSON OBJECTS; scoped "
            "unit criterion fields and floor_plans must be JSON ARRAYS. The "
            "tool call handles all escaping, including quotes "
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
    plans = extraction.floor_plans
    assert isinstance(plans, list)
    state.floor_plans = [FloorPlanIn.model_validate(p, from_attributes=True) for p in plans]
    for plan in state.floor_plans:
        plan.source_url = source.url
    state.source_claims = []
    for entry in extractable_entries():
        raw = getattr(extraction, entry.key)
        if entry.key in SCOPED_UNIT_CLAIM_KEYS:
            for scoped in raw:
                claim_group_id = uuid4()
                refs = (
                    scoped.floor_plan_refs
                    if scoped.applicability is UnitApplicability.SPECIFIC_FLOOR_PLANS
                    else [None]
                )
                for ref in refs:
                    state.source_claims.append(
                        SourceClaim(
                            criterion_key=entry.key,
                            value=scoped.value,
                            confidence=scoped.confidence,
                            evidence_quote=scoped.evidence_quote,
                            source_id=source.url,
                            model=model,
                            prompt_version=prompt_version,
                            target_scope=(
                                TargetScope.FLOOR_PLAN if ref is not None else TargetScope.PROPERTY
                            ),
                            floor_plan_ref=ref,
                            applicability=scoped.applicability,
                            claim_variant=(
                                json.dumps(sorted(scoped.value), separators=(",", ":"))
                                if entry.key == "flooring_materials"
                                else str(scoped.value)
                                if entry.key in TYPED_MULTI_CLAIM_KEYS
                                else None
                            ),
                            claim_group_id=claim_group_id,
                        )
                    )
            continue
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
    for scoped in extraction.heating:
        claim_group_id = uuid4()
        refs = (
            scoped.floor_plan_refs
            if scoped.applicability is UnitApplicability.SPECIFIC_FLOOR_PLANS
            else [None]
        )
        for ref in refs:
            state.source_claims.append(
                SourceClaim(
                    criterion_key="heating_type",
                    value=scoped.value,
                    confidence=scoped.confidence,
                    evidence_quote=scoped.evidence_quote,
                    source_id=source.url,
                    model=model,
                    prompt_version=prompt_version,
                    target_scope=(
                        TargetScope.FLOOR_PLAN if ref is not None else TargetScope.PROPERTY
                    ),
                    floor_plan_ref=ref,
                    applicability=scoped.applicability,
                    claim_variant=str(scoped.value),
                    claim_group_id=claim_group_id,
                )
            )
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
    state.heating = None
    # P3-21: page-derived contact. Provenance (official_site vs listing) is not
    # decided here — persistence reads `source.is_official`, so one block serves
    # both the top and bottom rung without a second extraction pass.
    property_contact = getattr(extraction, "property_contact", None)
    state.property_contact = (
        PropertyContactIn.model_validate(property_contact, from_attributes=True)
        if property_contact is not None
        else None
    )
    one_time = getattr(extraction, "one_time_fees", None)
    state.one_time_fees = (
        OneTimeFeesIn.model_validate(one_time, from_attributes=True)
        if one_time is not None
        else None
    )
    auxiliary: list[tuple[str, object, str | None]] = []
    if state.pet_costs is not None:
        auxiliary.append(
            (
                "pet_costs",
                state.pet_costs.model_dump(mode="json", exclude={"evidence_quote"}),
                state.pet_costs.evidence_quote,
            )
        )
    if state.utilities is not None and state.utilities.included is not None:
        auxiliary.append(
            ("utilities_included", list(state.utilities.included), state.utilities.evidence_quote)
        )
    if state.mandatory_fees is not None and state.mandatory_fees.fees:
        auxiliary.append(
            (
                "mandatory_fees",
                [fee.model_dump(mode="json") for fee in state.mandatory_fees.fees],
                state.mandatory_fees.evidence_quote,
            )
        )
    if state.one_time_fees is not None and state.one_time_fees.fees:
        auxiliary.append(
            (
                "one_time_fees",
                [fee.model_dump(mode="json") for fee in state.one_time_fees.fees],
                state.one_time_fees.evidence_quote,
            )
        )
    for key, value, evidence in auxiliary:
        state.source_claims.append(
            SourceClaim(
                criterion_key=key,
                value=value,
                confidence=Confidence.HIGH,
                evidence_quote=evidence,
                source_id=source.url,
                model=model,
                prompt_version=prompt_version,
                target_scope=TargetScope.PROPERTY,
            )
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


def _empty_source_slice(state: RunState, source_index: int) -> RunState:
    """Clone run metadata while clearing outputs that belong to another Source."""
    isolated = state.model_copy(deep=True)
    isolated.sources = [state.sources[source_index].model_copy(deep=True)]
    isolated.source_claims = []
    isolated.floor_plans = []
    isolated.property_identity = None
    isolated.pet_costs = None
    isolated.utilities = None
    isolated.mandatory_fees = None
    isolated.heating = None
    isolated.one_time_fees = None
    isolated.property_contact = None
    isolated.verify_flags = []
    return isolated


def _result_from_state(extracted: RunState) -> SourceResult:
    source = extracted.sources[0]
    return SourceResult(
        source_url=source.url,
        syndication_family=source.syndication_family or source.url,
        role=source.role,
        is_official=source.is_official,
        fetched_at=source.fetched_at,
        source_claims=extracted.source_claims,
        floor_plans=extracted.floor_plans,
        property_identity=extracted.property_identity,
        pet_costs=extracted.pet_costs,
        utilities=extracted.utilities,
        mandatory_fees=extracted.mandatory_fees,
        heating=extracted.heating,
        one_time_fees=extracted.one_time_fees,
        property_contact=extracted.property_contact,
    )


def _mirror_primary_result(state: RunState, result: SourceResult) -> None:
    state.source_claims = [claim.model_copy(deep=True) for claim in result.source_claims]
    state.floor_plans = [plan.model_copy(deep=True) for plan in result.floor_plans]
    state.property_identity = (
        result.property_identity.model_copy(deep=True)
        if result.property_identity is not None
        else None
    )
    state.pet_costs = result.pet_costs.model_copy(deep=True) if result.pet_costs else None
    state.utilities = result.utilities.model_copy(deep=True) if result.utilities else None
    state.mandatory_fees = (
        result.mandatory_fees.model_copy(deep=True) if result.mandatory_fees else None
    )
    state.heating = result.heating.model_copy(deep=True) if result.heating else None
    state.one_time_fees = (
        result.one_time_fees.model_copy(deep=True) if result.one_time_fees else None
    )
    state.property_contact = (
        result.property_contact.model_copy(deep=True) if result.property_contact else None
    )


async def extract_stage(state: RunState, ctx: StageCtx) -> RunState:
    """EXTRACT each fetched Source once, retaining isolated Source-local output."""
    completed = {result.source_url for result in state.source_results}
    for index, source in enumerate(state.sources):
        if source.url in completed or not source.cleaned_text:
            continue
        isolated = _empty_source_slice(state, index)
        extracted = await _extract_single(isolated, ctx)
        result = _result_from_state(extracted)
        state.source_results.append(result)
        source.authoritative_extraction = True
        completed.add(source.url)

    primary = next(
        (result for result in state.source_results if result.source_url == state.url),
        None,
    )
    if primary is not None:
        _mirror_primary_result(state, primary)
    return state
