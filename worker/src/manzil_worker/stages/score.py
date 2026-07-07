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
- `all_in_monthly` interim composition: the plan's conservative advertised
  rent (rent_max, else rent_min) — never cheaper than a worst realistic
  month. Full §9.5 composition (fees, utilities) lands P3-9.
- Each extracted floor plan scores independently (§9.4); a page with no plans
  scores once property-level. Display score = best plan (no pins in Phase 0).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import structlog
from manzil_shared.models import Confidence, FloorPlan
from manzil_shared.scoring.engine import score, select_display_score

from manzil_worker.stages.base import StageCtx
from manzil_worker.state import FloorPlanIn, PlanScore, RunState

log = structlog.get_logger()

_CONFIDENCE_RANK = {
    Confidence.NOT_FOUND: 0,
    Confidence.LOW: 1,
    Confidence.MEDIUM: 2,
    Confidence.HIGH: 3,
}


def meets_confidence(confidence: Confidence, minimum: Confidence) -> bool:
    return _CONFIDENCE_RANK[confidence] >= _CONFIDENCE_RANK[minimum]


def _to_floor_plan(plan: FloorPlanIn) -> FloorPlan | None:
    """Engine overlay needs the shared model; beds+baths are its required core.
    Placeholder UUIDs — Phase 0 has no property/source rows yet."""
    if plan.beds is None or plan.baths is None:
        return None
    return FloorPlan(
        property_id=uuid4(),
        source_id=uuid4(),
        plan_name=plan.plan_name or "unnamed",
        beds=plan.beds,
        baths=plan.baths,
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
    state.reconciled = {
        key: extractions[0] for key, extractions in state.extractions.items() if extractions
    }
    base_values = {
        key: extraction.value
        for key, extraction in state.reconciled.items()
        if extraction.value is not None
        and meets_confidence(extraction.confidence, ctx.min_confidence)
    }
    state.effective_values = dict(base_values)

    scorable = [(p, fp) for p in state.floor_plans if (fp := _to_floor_plan(p)) is not None]
    if scorable:
        breakdowns = []
        for plan_in, floor_plan in scorable:
            values = dict(base_values)
            rent = conservative_rent(plan_in)
            if rent is not None:
                values["all_in_monthly"] = rent
            breakdowns.append(
                (
                    floor_plan.plan_name,
                    score(ctx.rubric, values, floor_plan, rubric_version=ctx.rubric_version),
                )
            )
        state.scores = [
            PlanScore(plan_name=name, breakdown=b.to_contract()) for name, b in breakdowns
        ]
        state.display_score_index = select_display_score([b for _, b in breakdowns])
    else:
        breakdown = score(ctx.rubric, base_values, None, rubric_version=ctx.rubric_version)
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
