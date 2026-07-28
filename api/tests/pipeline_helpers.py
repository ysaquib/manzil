"""Deterministic LLM helpers for API-level pipeline integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from manzil_shared.catalog import SCOPED_UNIT_CLAIM_KEYS
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
    # This API integration fixture predates the P3-SC3 Property tranche and
    # P3-SC4 scoped-unit shape. Adapt only this frozen synthetic boundary; the
    # production schema and new recordings stay strict.
    for entry in extractable_entries():
        if entry.key in SCOPED_UNIT_CLAIM_KEYS:
            legacy = output.get(entry.key)
            if isinstance(legacy, dict) and legacy.get("value") is not None:
                output[entry.key] = [
                    {
                        **legacy,
                        "applicability": (
                            "all_units"
                            if entry.key == "in_unit_laundry"
                            else "unit_scope_unspecified"
                        ),
                        "floor_plan_refs": [],
                    }
                ]
            else:
                output[entry.key] = []
        else:
            output.setdefault(
                entry.key,
                {"value": None, "confidence": "not_found", "evidence_quote": None},
            )
    legacy_heating = output.get("heating")
    if isinstance(legacy_heating, dict) and legacy_heating.get("heating") is not None:
        output["heating"] = [
            {
                "value": legacy_heating["heating"],
                "confidence": "high",
                "evidence_quote": legacy_heating.get("evidence_quote") or "",
                "applicability": "unit_scope_unspecified",
                "floor_plan_refs": [],
            }
        ]
    else:
        output["heating"] = []
    return schema.model_validate(output)


async def empty_discovery_agent(stage, task, tools, max_turns):  # type: ignore[no-untyped-def]
    assert stage == "discover"
    return AgentResult(final_text='{"candidates": []}', turns=1)
