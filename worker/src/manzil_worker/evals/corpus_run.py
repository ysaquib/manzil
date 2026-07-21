"""Label-free EXTRACT -> VERIFY runner for one saved corpus page.

This is the diagnostic sibling of the graded bench harness: it uses the same
saved cleaned text, freezes ``StageCtx.today`` to ``meta.json.saved_at``, and
runs the real stages through the normal traced record/replay LLM seam. It
deliberately does not fetch, grade, score, or write application rows.
"""

from __future__ import annotations

import dataclasses
import json
import time
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from manzil_shared.errors import CheckpointRaised
from manzil_shared.models import CheckpointPrompt, FetchOutcome, JobType
from pydantic import BaseModel

from manzil_worker.evals.harness import _corpus_as_of_date
from manzil_worker.llm.client import RunContext, cost_tally, llm_mode, run_context
from manzil_worker.llm.config import model_for_stage
from manzil_worker.llm.prompt_loader import load_prompt
from manzil_worker.llm.recording import recorded_dir
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.extract import extract_stage
from manzil_worker.stages.verify import verify_stage
from manzil_worker.state import (
    FieldExtraction,
    FloorPlanIn,
    HeatingIn,
    MandatoryFeesIn,
    OneTimeFeesIn,
    PetCostsIn,
    PropertyIdentityIn,
    RunState,
    SourceState,
    UtilitiesIn,
    VerifyFlag,
)


class CorpusRunUsage(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    latency_s: float


class CorpusRunResult(BaseModel):
    slug: str
    job_id: str
    url: str
    as_of_date: date
    llm_mode: str
    models: dict[str, str]
    prompt_versions: dict[str, int]
    recordings_dir: str | None = None
    extractions: dict[str, list[FieldExtraction]]
    floor_plans: list[FloorPlanIn]
    property_identity: PropertyIdentityIn | None
    pet_costs: PetCostsIn | None
    utilities: UtilitiesIn | None
    mandatory_fees: MandatoryFeesIn | None
    one_time_fees: OneTimeFeesIn | None
    heating: HeatingIn | None
    verify_flags: list[VerifyFlag]
    checkpoint: CheckpointPrompt | None
    usage: CorpusRunUsage


def _load_meta(page_dir: Path) -> dict[str, Any]:
    meta_path = page_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text())
    except FileNotFoundError:
        raise ValueError(f"invalid corpus metadata at {meta_path}: missing meta.json") from None
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid corpus metadata at {meta_path}: {error}") from error
    if not isinstance(meta, dict):
        raise ValueError(f"invalid corpus metadata at {meta_path}: expected a JSON object")
    url = meta.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f"invalid corpus metadata at {meta_path}: missing url")
    return meta


async def run_corpus_extraction(
    slug: str,
    *,
    corpus_dir: Path,
    ctx: StageCtx,
) -> CorpusRunResult:
    """Run only EXTRACT and VERIFY for ``slug`` and return their raw output."""
    page_dir = corpus_dir / slug
    cleaned_path = page_dir / "cleaned.txt"
    if not cleaned_path.exists():
        raise ValueError(f"no corpus page at {page_dir} — run `manzil save-page`")

    meta = _load_meta(page_dir)
    as_of = _corpus_as_of_date(page_dir)
    url = str(meta["url"])
    listing_ctx = dataclasses.replace(ctx, today=lambda: as_of)
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url=url)
    state.sources = [
        SourceState(
            url=url,
            tier_used=meta.get("tier"),
            outcome=FetchOutcome.SUCCESS,
            cleaned_text=cleaned_path.read_text(),
            is_official=bool(meta.get("is_official", False)),
        )
    ]

    trace = RunContext(job_type="bench", job_id=str(state.job_id), listing_slug=slug)
    started = time.perf_counter()
    with run_context(trace), cost_tally() as tally:
        state = await extract_stage(state, listing_ctx)
        try:
            state = await verify_stage(state, listing_ctx)
        except CheckpointRaised as raised:
            # This command has no durable Job to park. Preserve VERIFY's completed
            # audit and surface the proposed checkpoint in the diagnostic result.
            state.checkpoint = raised.prompt

    mode = llm_mode()
    return CorpusRunResult(
        slug=slug,
        job_id=str(state.job_id),
        url=url,
        as_of_date=as_of,
        llm_mode=mode,
        models={stage: model_for_stage(stage) for stage in ("extract", "verify")},
        prompt_versions={stage: load_prompt(stage).version for stage in ("extract", "verify")},
        recordings_dir=str(recorded_dir()) if mode == "record" else None,
        extractions=state.extractions,
        floor_plans=state.floor_plans,
        property_identity=state.property_identity,
        pet_costs=state.pet_costs,
        utilities=state.utilities,
        mandatory_fees=state.mandatory_fees,
        one_time_fees=state.one_time_fees,
        heating=state.heating,
        verify_flags=state.verify_flags,
        checkpoint=state.checkpoint,
        usage=CorpusRunUsage(
            calls=tally.calls,
            input_tokens=tally.input_tokens,
            output_tokens=tally.output_tokens,
            cache_read_tokens=tally.cache_read_tokens,
            cache_write_tokens=tally.cache_write_tokens,
            cost_usd=tally.cost_usd,
            latency_s=round(time.perf_counter() - started, 3),
        ),
    )
