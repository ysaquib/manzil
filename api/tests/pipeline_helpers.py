"""Deterministic LLM helpers for API-level pipeline integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from manzil_worker.llm.client import call_structured

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
    if stage != "extract":
        return await call_structured(stage, schema, content)
    recording = json.loads(_MAPLE_EXTRACT_RECORDING.read_text())
    return schema.model_validate(recording["output"])
