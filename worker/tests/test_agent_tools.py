"""P3-3: the @tool registry (schema derivation), the per-stage allow-list as the
§16 zero-tool control, and clean handling of a hallucinated tool name."""

from __future__ import annotations

from typing import Any, Literal

import pytest
from manzil_shared.errors import StageFatal
from manzil_worker.enrich.maps import commute_time, geocode, places_nearby
from manzil_worker.llm.client import call_agent
from manzil_worker.llm.config import allowed_tools
from manzil_worker.llm.tools import (
    ToolNotAllowed,
    fetch_page,
    run_agent_loop,
    tool,
    tool_spec,
)


@tool
async def _sample_tool(
    address: str,
    radius: int,
    weight: float,
    exact: bool = False,
    label: str | None = None,
    mode: Literal["fast", "slow"] = "fast",
) -> dict[str, Any]:
    """Sample tool for schema derivation. Second line ignored."""
    return {"ok": True}


def test_tool_schema_derivation_is_a_stable_contract() -> None:
    spec = tool_spec(_sample_tool)
    assert spec.name == "_sample_tool"
    assert spec.description == "Sample tool for schema derivation. Second line ignored."
    assert spec.parameters == {
        "type": "object",
        "properties": {
            "address": {"type": "string"},
            "radius": {"type": "integer"},
            "weight": {"type": "number"},
            "exact": {"type": "boolean"},
            "label": {"type": "string"},  # Optional → present but not required
            "mode": {"type": "string", "enum": ["fast", "slow"]},
        },
        # defaults and Optionals drop out of `required`
        "required": ["address", "radius", "weight"],
        "additionalProperties": False,
    }


def test_fetch_page_and_maps_tool_schemas() -> None:
    assert tool_spec(fetch_page).parameters == {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
        "additionalProperties": False,
    }
    assert tool_spec(geocode).parameters["required"] == ["address"]
    assert tool_spec(places_nearby).parameters["properties"]["lat"] == {"type": "number"}
    assert tool_spec(places_nearby).parameters["required"] == ["lat", "lng"]
    assert tool_spec(commute_time).parameters["required"] == ["origin_latlng", "destination"]


def test_extraction_stages_resolve_to_zero_tools() -> None:
    # The §16 hard invariant: extraction stages get NO tools, ever.
    for stage in ("extract", "verify", "validate", "score", "reconcile_equivalence"):
        assert allowed_tools(stage) == ()


def test_exactly_two_stages_may_run_a_loop() -> None:
    from manzil_worker.llm.config import STAGE_TOOLS

    non_empty = {s for s, tools in STAGE_TOOLS.items() if tools}
    assert non_empty == {"discover", "custom_match_location"}


async def test_call_agent_refuses_an_extraction_stage() -> None:
    # A stage absent from STAGE_TOOLS cannot run a tool loop at all — enforced in
    # the seam, before any model turn (so no key/network is touched).
    with pytest.raises(ToolNotAllowed, match="not an allow-listed tool-loop stage"):
        await call_agent("extract", "do it", [fetch_page])


async def test_call_agent_refuses_a_tool_outside_the_stage_allow_list() -> None:
    # discover may fetch_page but not geocode.
    with pytest.raises(ToolNotAllowed, match="may not use tool 'geocode'"):
        await call_agent("discover", "do it", [geocode])


async def test_unknown_tool_name_in_a_loop_response_is_a_clean_error() -> None:
    # The model hallucinates a tool the stage never offered: the loop feeds an
    # error result back and keeps going — no crash.
    seen: list[dict] = []

    async def turn_fn(messages, specs):  # type: ignore[no-untyped-def]
        from manzil_worker.llm.tools import ToolCall, TurnResponse

        seen.append(messages[-1])
        if len(seen) == 1:
            return TurnResponse(tool_calls=[ToolCall(name="does_not_exist", input={})])
        return TurnResponse(tool_calls=[], text="recovered")

    result = await run_agent_loop(
        stage="discover", task="go", tools=[fetch_page], turn_fn=turn_fn, max_turns=4
    )
    assert result.final_text == "recovered"
    # The second turn saw a tool result carrying the error, not an exception.
    assert "unknown tool" in seen[1]["content"]


def test_tool_not_allowed_is_fatal() -> None:
    assert issubclass(ToolNotAllowed, StageFatal)
