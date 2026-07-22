"""Deterministic LLM helpers for API-level pipeline integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from manzil_worker.llm.client import call_structured
from manzil_worker.llm.tools import AgentResult
from manzil_worker.stages.schema_gen import extractable_entries

_MAPLE_EXTRACT_RECORDING = (
    Path(__file__).resolve().parents[2]
    / "worker"
    / "tests"
    / "fixtures"
    / "recorded"
    / "extract--5c2ab4abc7ec5991.json"
)


async def maple_recorded_llm(stage: str, schema: type[Any], content: str) -> Any:
    """Use the saved Maple EXTRACT response while replaying all other stages.

    These tests cover API/queue integration, not prompt-version hashing. Pinning
    their EXTRACT result keeps prompt changes gated by the worker bench instead
    of breaking unrelated database and lifespan coverage.
    """
    if stage == "verify":
        return schema.model_validate({"contradictions": []})
    if stage != "extract":
        return await call_structured(stage, schema, content)
    recording = json.loads(_MAPLE_EXTRACT_RECORDING.read_text())
    output = dict(recording["output"])
    # This API integration fixture predates the P3-SC3 Property tranche. The
    # production schema stays strict; P3-SC4 will replace this compatibility
    # boundary when it refreshes the canonical scoped recordings.
    for entry in extractable_entries():
        output.setdefault(
            entry.key,
            {"value": None, "confidence": "not_found", "evidence_quote": None},
        )
    return schema.model_validate(output)


async def empty_discovery_agent(stage, task, tools, max_turns):  # type: ignore[no-untyped-def]
    assert stage == "discover"
    return AgentResult(final_text='{"candidates": []}', turns=1)
