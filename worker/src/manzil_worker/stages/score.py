"""SCORE stage (P0-10, DESIGN §9.3-9.4, §10.3): deterministic engine, per
floor plan. No LLM — this stage only assembles facts and calls the shared
engine.

Assembly semantics (Phase 0, single source):
- `reconciled` = the single source's extractions verbatim (the RECONCILE
  ladder arrives with multi-source in P3-6).
- Effective values are **confidence-thresholded** (§9.3, hunt settings v2.3):
  a value below `ctx.min_confidence` (default `medium`) scores as unknown —
  a VERIFY demotion means suspect data cannot pass a gate. The value itself
  stays on `reconciled`/extractions as provenance; a Phase 1 `confirm_value`
  checkpoint answer is what upgrades it back. Floor-plan figures carry no
  confidence dimension yet, so the plan overlay is not thresholded.
- VISION uses its separate `ctx.min_vision_confidence` threshold (default
  `low`) for point values. A low-confidence VISION value never enters the Gate
  map, even when retained for points and display.
- `all_in_monthly` interim composition: the plan's conservative advertised
  rent (rent_max, else rent_min) — never cheaper than a worst realistic
  month. Full §9.5 composition (fees, utilities) lands P3-9.
- Each extracted floor plan scores independently (§9.4); a page with no plans
  scores once property-level. Display score = best plan (no pins in Phase 0).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

import structlog
from manzil_shared.catalog import (
    BOOLEAN_PRESENCE_KEYS,
    CONFIRMED_SCOPE_ONLY_KEYS,
    PRESENCE_LIKE_KEYS,
)
from manzil_shared.models import Confidence, FloorPlan
from manzil_shared.scoped_facts import (
    ScopedValue,
    resolve_effective_facts,
    resolve_effective_values,
    scoring_values_for_policy,
)
from manzil_shared.scoped_facts import (
    meets_confidence as scoped_meets_confidence,
)
from manzil_shared.scoring.engine import criterion_key, score, select_display_score

from manzil_worker.enrich.utility_baselines import region_estimate_note
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.move_in import (
    Household,
    charge_from_extracted_fee,
    compose_move_in,
)
from manzil_worker.stages.pet_costs import beds_bucket, compose_all_in, pet_monthly
from manzil_worker.state import FloorPlanIn, PlanScore, RunState

log = structlog.get_logger()


def meets_confidence(confidence: Confidence, minimum: Confidence) -> bool:
    return scoped_meets_confidence(confidence, minimum)


def floor_plan_runtime_id(plan: FloorPlanIn, source_url: str, index: int) -> UUID:
    identity = (
        plan.response_key
        or plan.source_native_id
        or (f"{plan.plan_name or 'unnamed'}|{plan.beds}|{plan.baths}|{index}")
    )
    return uuid5(NAMESPACE_URL, f"{source_url}#{identity}")


def _to_floor_plan(plan: FloorPlanIn, source_url: str, index: int) -> FloorPlan | None:
    """Engine overlay needs the shared model; beds+baths are its required core.
    Placeholder UUIDs — Phase 0 has no property/source rows yet."""
    if plan.beds is None or plan.baths is None:
        return None
    return FloorPlan(
        id=floor_plan_runtime_id(plan, source_url, index),
        property_id=uuid5(NAMESPACE_URL, source_url),
        source_id=uuid5(NAMESPACE_URL, source_url),
        plan_name=plan.plan_name or "unnamed",
        beds=plan.beds,
        baths=plan.baths,
        unit_types=list(plan.unit_types),
        sqft_min=plan.sqft_min,
        sqft_max=plan.sqft_max,
        rent_min=Decimal(str(plan.rent_min)) if plan.rent_min is not None else None,
        rent_max=Decimal(str(plan.rent_max)) if plan.rent_max is not None else None,
        deposit=Decimal(str(plan.deposit)) if plan.deposit is not None else None,
        availability_date=(
            date.fromisoformat(plan.availability_date)
            if plan.availability_date is not None
            else None
        ),
    )


def conservative_rent(plan: FloorPlanIn) -> float | None:
    return plan.rent_max if plan.rent_max is not None else plan.rent_min


async def score_stage(state: RunState, ctx: StageCtx) -> RunState:
    if state.job_type.value == "refresh" and state.custom_criterion_keys:
        # Terminal projection persists the Hunt-scoped claims and invokes the
        # database-backed rescore resolver, which also has Catalog facts and Overrides.
        return state
    # ENRICH-only refreshes persist their new API-derived facts and reuse the
    # database-backed rescore seam in the terminal projection. That seam owns
    # current Floor Plan IDs, Overrides, fees, and utility corrections; trying
    # to rebuild them from a page-less RunState would create a second resolver.
    if (
        state.job_type.value == "refresh"
        and set(state.refresh_fields) <= {"reviews", "location"}
        and not state.floor_plans
    ):
        return state
    if not state.resolved_claims:
        state.resolved_claims = [
            claim.model_copy(
                update={
                    "resolution_rule": "single_source",
                    "candidate_claim_group_ids": [claim.claim_group_id],
                },
                deep=True,
            )
            for claim in state.source_claims
        ]
    criterion_keys = [criterion_key(criterion) for criterion in ctx.rubric]
    plan_ids_by_ref = {
        (plan.source_url or state.sources[0].url, plan.response_key): floor_plan_runtime_id(
            plan,
            plan.source_url or state.sources[0].url,
            index,
        )
        for index, plan in enumerate(state.floor_plans)
        if plan.response_key is not None
    }
    scoped_rows = [
        ScopedValue(
            criterion_key=claim.criterion_key,
            value=claim.value,
            confidence=claim.confidence,
            target_scope=claim.target_scope,
            floor_plan_id=(
                plan_ids_by_ref.get((claim.source_id or state.sources[0].url, claim.floor_plan_ref))
                if claim.floor_plan_ref is not None
                else claim.floor_plan_id
            ),
            applicability=claim.applicability,
            claim_variant=claim.claim_variant,
            origin_key=claim.origin_key,
            resolution_rule=claim.resolution_rule,
        )
        for claim in [*state.resolved_claims, *state.custom_claims]
    ]

    # §9.5 v1: pet rent folds into all_in_monthly. Counts are hunt settings (ctx);
    # per-pet rents are this run's extracted pet_costs. Composed once — same for
    # every plan on the page.
    pc = state.pet_costs
    pet_add = pet_monthly(
        cats=ctx.cats,
        dogs=ctx.dogs,
        cat_rent=pc.cat_rent_monthly if pc else None,
        dog_rent=pc.dog_rent_monthly if pc else None,
        generic_rent=pc.pet_rent_monthly if pc else None,
    )

    # §9.5 P3-9 composition inputs, identical for every plan on the page; the
    # per-plan pieces (rent, beds bucket) vary inside the loop.
    geocode = state.geocode
    city = geocode.city if geocode else None
    state_code = geocode.state if geocode else None
    county = geocode.county if geocode else None
    fees = (
        [(f.name, f.amount_monthly) for f in state.mandatory_fees.fees]
        if (state.mandatory_fees)
        else []
    )
    included = (
        list(state.utilities.included)
        if (state.utilities and state.utilities.included is not None)
        else None
    )
    # §9.5 P3-SC8: the page's one-time move-in charges for THIS household.
    # Ingest has no human decisions yet (the fee_checklist rows are written by
    # the projection after SCORE), so this is the extraction's own reading;
    # rescore recomposes with any human required/refundable/credited edits.
    household = Household(occupants=ctx.occupants, cats=ctx.cats, dogs=ctx.dogs)
    one_time_charges = [
        charge_from_extracted_fee(fee.model_dump(), household)
        for fee in (state.one_time_fees.fees if state.one_time_fees else [])
    ]
    scorable = [
        (plan, floor_plan)
        for index, plan in enumerate(state.floor_plans)
        if (
            floor_plan := _to_floor_plan(
                plan,
                plan.source_url or state.sources[0].url,
                index,
            )
        )
        is not None
    ]
    if scorable:
        breakdowns = []
        compositions = []
        move_ins = []
        for plan_in, floor_plan in scorable:
            facts = resolve_effective_facts(
                criterion_keys=criterion_keys,
                floor_plan_id=floor_plan.id,
                extractions=scoped_rows,
                min_confidence=ctx.min_confidence,
                min_vision_confidence=ctx.min_vision_confidence,
                presence_like_keys=PRESENCE_LIKE_KEYS,
                boolean_presence_keys=BOOLEAN_PRESENCE_KEYS,
                generalized_unknown_keys=CONFIRMED_SCOPE_ONLY_KEYS,
            )
            values, gate_values = scoring_values_for_policy(facts, ctx.generalized_vision_policy)
            rent = conservative_rent(plan_in)
            composition = None
            if rent is not None:
                baseline_set = (
                    await ctx.utility_baselines_lookup(
                        city, state_code, county, beds_bucket(floor_plan.beds)
                    )
                    if state_code is not None
                    else None
                )
                heating_value = resolve_effective_values(
                    criterion_keys=["heating_type"],
                    floor_plan_id=floor_plan.id,
                    extractions=scoped_rows,
                    min_confidence=ctx.min_confidence,
                    presence_like_keys=frozenset({"heating_type"}),
                ).get("heating_type")
                plan_heating = (
                    heating_value[0]
                    if isinstance(heating_value, list)
                    and len(heating_value) == 1
                    and heating_value[0] in {"gas", "electric"}
                    else None
                )
                composition = compose_all_in(
                    rent=rent,
                    pet_add=pet_add,
                    mandatory_fees=fees,
                    included=included,
                    heating=plan_heating,
                    baselines=baseline_set.values if baseline_set else None,
                    baseline_scope_note=(
                        region_estimate_note(baseline_set.region) if baseline_set else None
                    ),
                    mode=ctx.cost_estimate_mode,
                    occupants=ctx.occupants,
                    beds=floor_plan.beds,
                )
                # total None = the strict-unknown branch: the criterion scores
                # unknown_delta rather than a fabricated number (§9.5).
                if composition.total is not None:
                    values["all_in_monthly"] = composition.total
                    gate_values["all_in_monthly"] = composition.total
            move_in = compose_move_in(
                first_month_rent=rent,
                security_deposit=(
                    float(floor_plan.deposit) if floor_plan.deposit is not None else None
                ),
                charges=[replace(charge) for charge in one_time_charges],
            )
            # Incomplete ⇒ total None ⇒ the Criterion stays unknown (§9.5): a
            # partial cash figure is never scored as if it were the whole.
            if move_in.total is not None:
                values["estimated_move_in_cost"] = move_in.total
                gate_values["estimated_move_in_cost"] = move_in.total
            move_ins.append(move_in)
            compositions.append(composition)
            breakdowns.append(
                (
                    floor_plan.plan_name,
                    score(
                        ctx.rubric,
                        values,
                        floor_plan,
                        rubric_version=ctx.rubric_version,
                        gate_values=gate_values,
                    ),
                )
            )
        state.scores = [
            PlanScore(
                plan_name=name,
                breakdown=b.to_contract(),
                all_in_components=comp.to_json() if comp is not None else None,
                move_in_components=move_in.to_json(),
            )
            for (name, b), comp, move_in in zip(breakdowns, compositions, move_ins, strict=True)
        ]
        state.display_score_index = select_display_score([b for _, b in breakdowns])
        display_floor_plan = scorable[state.display_score_index][1]
        state.effective_values = resolve_effective_values(
            criterion_keys=criterion_keys,
            floor_plan_id=display_floor_plan.id,
            extractions=scoped_rows,
            min_confidence=ctx.min_confidence,
            min_vision_confidence=ctx.min_vision_confidence,
            presence_like_keys=PRESENCE_LIKE_KEYS,
            boolean_presence_keys=BOOLEAN_PRESENCE_KEYS,
            generalized_unknown_keys=CONFIRMED_SCOPE_ONLY_KEYS,
        )
        display_composition = compositions[state.display_score_index]
        state.all_in_components = (
            display_composition.to_json() if display_composition is not None else None
        )
        state.move_in_components = move_ins[state.display_score_index].to_json()
    else:
        facts = resolve_effective_facts(
            criterion_keys=criterion_keys,
            floor_plan_id=None,
            extractions=scoped_rows,
            min_confidence=ctx.min_confidence,
            min_vision_confidence=ctx.min_vision_confidence,
            presence_like_keys=PRESENCE_LIKE_KEYS,
            boolean_presence_keys=BOOLEAN_PRESENCE_KEYS,
            generalized_unknown_keys=CONFIRMED_SCOPE_ONLY_KEYS,
        )
        base_values, gate_values = scoring_values_for_policy(facts, ctx.generalized_vision_policy)
        state.effective_values = dict(base_values)
        breakdown = score(
            ctx.rubric,
            base_values,
            None,
            rubric_version=ctx.rubric_version,
            gate_values=gate_values,
        )
        state.scores = [PlanScore(plan_name=None, breakdown=breakdown.to_contract())]
        state.display_score_index = 0

    log.info(
        "scored",
        job_id=str(state.job_id),
        stage="score",
        plans=len(state.scores),
        display_total=state.scores[state.display_score_index].breakdown["total"],
    )
    return state
