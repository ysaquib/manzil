"""VISION stage boundary.

P3-7a lands the resume-safe boundary and fails closed.  P3-7b enables the
anchored call only after the human reference manifest and prompt migration are
reviewed; see docs/p3-7-vision-guide.md.
"""

from __future__ import annotations

from manzil_shared.errors import StageFatal

from manzil_worker.stages.base import StageCtx
from manzil_worker.state import RunState
from manzil_worker.vision_refs import vision_references_ready


async def vision_stage(state: RunState, ctx: StageCtx) -> RunState:
    if not vision_references_ready():
        if state.plan is not None:
            state.plan.skipped["VISION"] = "missing_reference_set"
        return state
    raise StageFatal(
        "VISION reference assets exist but the P3-7b prompt/aggregation migration "
        "has not been enabled; follow docs/p3-7-vision-guide.md"
    )
