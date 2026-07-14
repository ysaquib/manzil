"""The LLM client seam (DESIGN §11.1, IMPLEMENTATION §3, §6 — the ONLY module
that touches provider SDKs).

The seam resolves model + prompt from `llm/config.py` by stage, applies
`cache_control` per IMPLEMENTATION §4, emits the Langfuse trace (NFR6),
tallies cost onto the active tally (RunState wires in at P0-10), and honors
`MANZIL_LLM_MODE`:

- `live`    — real call, traced. Langfuse unconfigured is a hard error: an
              untraced call is a bug (NFR6), not a degraded mode.
- `record`  — live + traced, response saved to fixtures/recorded/.
- `replay`  — served from disk, fails on any miss (the CI default). A replay
              is not a model call, so it is not traced — CI has no keys and
              spends no tokens.

All live calls route through OpenRouter's OpenAI-compatible API. Structured
output is forced tool use: one tool whose input schema is the Pydantic model's
JSON schema, `tool_choice` pinned to it — the model cannot answer in prose.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from manzil_shared.config import AGENT_MAX_TURNS
from pydantic import BaseModel

from manzil_worker.llm.config import (
    cost_usd,
    max_tokens_for_stage,
    model_for_stage,
    openrouter_provider_order,
)
from manzil_worker.llm.prompt_loader import Prompt, PromptError, load_prompt
from manzil_worker.llm.recording import (
    Recording,
    content_sha256,
    load_recording,
    now_iso,
    request_hash,
    save_recording,
)
from manzil_worker.llm.tools import (
    AgentResult,
    ToolCall,
    ToolSpec,
    TurnResponse,
    run_agent_loop,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

STRUCTURED_TOOL_NAME = "emit_result"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class SeamConfigError(RuntimeError):
    """The seam refuses to run misconfigured — never silently untraced/unkeyed."""


def llm_mode() -> str:
    mode = os.environ.get("MANZIL_LLM_MODE", "live")
    if mode not in ("live", "record", "replay"):
        raise SeamConfigError(f"MANZIL_LLM_MODE={mode!r}: expected live | record | replay")
    return mode


# ── ambient call context ─────────────────────────────────────────────────────
# The pinned §11.1 signatures carry no trace/job arguments, so job identity and
# the cost tally travel as context vars. The runner (P0-10) sets both around
# each stage; bare CLI calls get sensible defaults.


@dataclass(frozen=True)
class RunContext:
    """Trace identity: name `{job_type}/{stage}`, session = job_id (IMPL §6)."""

    job_type: str = "ingest"
    job_id: str | None = None
    listing_slug: str | None = None  # bench runs label their traces
    mode: str = "workflow"  # workflow | agents (MANZIL_MODE)


@dataclass
class CostTally:
    """Accumulates across calls; P0-10's runner adds this onto RunState.cost_usd."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, usage: CallUsage) -> None:
        self.calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_tokens += usage.cache_read_tokens
        self.cache_write_tokens += usage.cache_write_tokens
        self.cost_usd += usage.cost_usd


@dataclass(frozen=True)
class CallUsage:
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float


_run_context: ContextVar[RunContext | None] = ContextVar("manzil_run_context", default=None)
_active_tally: ContextVar[CostTally | None] = ContextVar("manzil_cost_tally", default=None)


def _current_context() -> RunContext:
    return _run_context.get() or RunContext()


@contextmanager
def run_context(ctx: RunContext) -> Iterator[None]:
    token = _run_context.set(ctx)
    try:
        yield
    finally:
        _run_context.reset(token)


@contextmanager
def cost_tally() -> Iterator[CostTally]:
    tally = CostTally()
    token = _active_tally.set(tally)
    try:
        yield tally
    finally:
        _active_tally.reset(token)


# ── provider + tracer plumbing (private) ─────────────────────────────────────


@dataclass(frozen=True)
class ProviderResponse:
    """What the live call yields, normalized: the forced tool's input + usage."""

    output: dict[str, Any]
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reported_cost_usd: float | None = None  # OpenRouter usage.cost cross-check


@dataclass(frozen=True)
class VisionImage:
    """One P4 image block. Recordings hash ``data`` but never persist its bytes."""

    content_hash: str
    data: bytes
    media_type: str = "image/webp"
    label: str = "target"


@dataclass(frozen=True)
class _CallPlan:
    stage: str
    model: str
    prompt: Prompt
    content: str
    digest: str


def _require_langfuse_configured() -> None:
    missing = [k for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY") if not os.environ.get(k)]
    if missing:
        raise SeamConfigError(
            f"Langfuse not configured ({', '.join(missing)} unset) — every live LLM call "
            "must be traced (NFR6). Set the keys or run with MANZIL_LLM_MODE=replay."
        )


def _langfuse() -> Any:
    # Provider SDK imports stay lazy and inside this module: replay-mode test
    # runs (CI) never touch the SDK's import-time machinery.
    from langfuse import Langfuse

    return Langfuse(host=os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com"))


def _usage_int(details: Any, field: str) -> int:
    if details is None:
        return 0
    if isinstance(details, dict):
        return int(details.get(field) or 0)
    return int(getattr(details, field, 0) or 0)


async def _live_call(plan: _CallPlan, schema: type[BaseModel]) -> ProviderResponse:
    """One real OpenRouter call: cached prefix + per-call system, forced tool."""
    return await _live_call_openrouter(plan, schema)


async def _live_call_openrouter(plan: _CallPlan, schema: type[BaseModel]) -> ProviderResponse:
    from openai import AsyncOpenAI

    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SeamConfigError("OPENROUTER_API_KEY unset — cannot make a live call")

    messages: list[dict[str, Any]] = []
    system_parts: list[dict[str, Any]] = []
    if plan.prompt.cacheable_prefix:
        system_parts.append(
            {
                "type": "text",
                "text": plan.prompt.cacheable_prefix,
                "cache_control": {"type": "ephemeral"},
            }
        )
    if plan.prompt.per_call:
        system_parts.append({"type": "text", "text": plan.prompt.per_call})
    if system_parts:
        messages.append({"role": "system", "content": system_parts})
    messages.append({"role": "user", "content": plan.content})

    client = AsyncOpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=OPENROUTER_BASE_URL,
    )
    response = await client.chat.completions.create(
        model=plan.model,
        max_tokens=max_tokens_for_stage(plan.stage),
        temperature=0.0,
        messages=messages,  # type: ignore[arg-type]
        tools=[
            {
                "type": "function",
                "function": {
                    "name": STRUCTURED_TOOL_NAME,
                    "description": "Emit the structured result. Always call this tool.",
                    "parameters": schema.model_json_schema(),
                },
            }
        ],
        tool_choice={
            "type": "function",
            "function": {"name": STRUCTURED_TOOL_NAME},
        },
        extra_body={
            "provider": {
                "order": openrouter_provider_order(plan.model),
                "allow_fallbacks": False,
            },
        },
    )

    message = response.choices[0].message
    if not message.tool_calls:
        raise SeamConfigError(
            f"stage {plan.stage!r}: model returned no tool_calls despite forced tool_choice"
        )
    output = json.loads(message.tool_calls[0].function.arguments)

    usage = response.usage
    if usage is None:
        raise SeamConfigError(f"stage {plan.stage!r}: OpenRouter response missing usage")

    details = getattr(usage, "prompt_tokens_details", None)
    cached = _usage_int(details, "cached_tokens")
    cache_write = _usage_int(details, "cache_write_tokens")
    prompt_tokens = usage.prompt_tokens or 0
    uncached = max(0, prompt_tokens - cached - cache_write)
    reported_cost = getattr(usage, "cost", None)

    return ProviderResponse(
        output=output,
        input_tokens=uncached,
        output_tokens=usage.completion_tokens or 0,
        cache_read_tokens=cached,
        cache_write_tokens=cache_write,
        reported_cost_usd=float(reported_cost) if reported_cost is not None else None,
    )


async def _live_call_openrouter_vision(
    plan: _CallPlan, schema: type[BaseModel], images: list[VisionImage]
) -> ProviderResponse:
    """One real P4 call. Image bytes exist only in the provider request."""
    from openai import AsyncOpenAI

    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SeamConfigError("OPENROUTER_API_KEY unset — cannot make a live call")
    system_parts: list[dict[str, Any]] = []
    if plan.prompt.cacheable_prefix:
        system_parts.append(
            {
                "type": "text",
                "text": plan.prompt.cacheable_prefix,
                "cache_control": {"type": "ephemeral"},
            }
        )
    if plan.prompt.per_call:
        system_parts.append({"type": "text", "text": plan.prompt.per_call})
    content: list[dict[str, Any]] = [{"type": "text", "text": plan.content}]
    for image in images:
        content.extend(
            [
                {
                    "type": "text",
                    "text": f"Image role: {image.label}; sha256: {image.content_hash}",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": (
                            f"data:{image.media_type};base64,"
                            f"{base64.b64encode(image.data).decode('ascii')}"
                        )
                    },
                },
            ]
        )
    messages: list[dict[str, Any]] = []
    if system_parts:
        messages.append({"role": "system", "content": system_parts})
    messages.append({"role": "user", "content": content})
    client = AsyncOpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url=OPENROUTER_BASE_URL)
    response = await client.chat.completions.create(
        model=plan.model,
        max_tokens=max_tokens_for_stage(plan.stage),
        temperature=0.0,
        messages=messages,  # type: ignore[arg-type]
        tools=[
            {
                "type": "function",
                "function": {
                    "name": STRUCTURED_TOOL_NAME,
                    "description": "Emit the structured result. Always call this tool.",
                    "parameters": schema.model_json_schema(),
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": STRUCTURED_TOOL_NAME}},
        extra_body={
            "provider": {
                "order": openrouter_provider_order(plan.model),
                "allow_fallbacks": False,
            }
        },
    )
    message = response.choices[0].message
    if not message.tool_calls:
        raise SeamConfigError(f"stage {plan.stage!r}: vision model returned no tool_calls")
    usage = response.usage
    if usage is None:
        raise SeamConfigError(f"stage {plan.stage!r}: OpenRouter response missing usage")
    details = getattr(usage, "prompt_tokens_details", None)
    cached = _usage_int(details, "cached_tokens")
    cache_write = _usage_int(details, "cache_write_tokens")
    prompt_tokens = usage.prompt_tokens or 0
    return ProviderResponse(
        output=json.loads(message.tool_calls[0].function.arguments),
        input_tokens=max(0, prompt_tokens - cached - cache_write),
        output_tokens=usage.completion_tokens or 0,
        cache_read_tokens=cached,
        cache_write_tokens=cache_write,
        reported_cost_usd=float(usage.cost) if getattr(usage, "cost", None) is not None else None,
    )


async def _traced_live_vision_call(
    plan: _CallPlan, schema: type[BaseModel], images: list[VisionImage]
) -> ProviderResponse:
    """Trace a live vision call without copying image bytes into Langfuse input."""
    _require_langfuse_configured()
    ctx = _current_context()
    from langfuse import Langfuse, propagate_attributes

    lf: Langfuse = _langfuse()
    metadata = {
        "mode": ctx.mode,
        "model": plan.model,
        "prompt_version": plan.prompt.version,
        "image_hashes": [image.content_hash for image in images],
        "llm_mode": llm_mode(),
    }
    with (
        propagate_attributes(trace_name=f"{ctx.job_type}/{plan.stage}", session_id=ctx.job_id),
        lf.start_as_current_observation(
            name=f"{ctx.job_type}/{plan.stage}",
            model=plan.model,
            input=plan.content,
            as_type="generation",
            metadata=metadata,
        ) as generation,
    ):
        response = await _live_call_openrouter_vision(plan, schema, images)
        if response.reported_cost_usd is not None:
            generation.update(
                metadata={**metadata, "openrouter_cost_usd": response.reported_cost_usd}
            )
        generation.update(
            output=response.output,
            usage_details={
                "input": response.input_tokens,
                "output": response.output_tokens,
                "cache_read_input_tokens": response.cache_read_tokens,
                "cache_creation_input_tokens": response.cache_write_tokens,
            },
            cost_details={"total": _usage_from(plan.model, response).cost_usd},
        )
    lf.flush()
    return response


async def _traced_live_call(plan: _CallPlan, schema: type[BaseModel]) -> ProviderResponse:
    """Live call wrapped in its Langfuse generation (IMPL §6): trace named
    `{job_type}/{stage}`, session = job_id, metadata carries mode / model /
    prompt_version / listing_slug plus token and cost figures."""
    _require_langfuse_configured()
    ctx = _current_context()
    from langfuse import Langfuse, propagate_attributes

    lf: Langfuse = _langfuse()
    metadata: dict[str, Any] = {
        "mode": ctx.mode,
        "model": plan.model,
        "prompt_version": plan.prompt.version,
        "listing_slug": ctx.listing_slug,
        "llm_mode": llm_mode(),
    }
    # v4 SDK: trace-level attributes (name, session) propagate via context, not
    # the removed v3 `update_current_trace`.
    with (
        propagate_attributes(trace_name=f"{ctx.job_type}/{plan.stage}", session_id=ctx.job_id),
        lf.start_as_current_observation(
            name=f"{ctx.job_type}/{plan.stage}",
            model=plan.model,
            input=plan.content,
            as_type="generation",
            metadata=metadata,
        ) as generation,
    ):
        response = await _live_call(plan, schema)
        if response.reported_cost_usd is not None:
            generation.update(
                metadata={**metadata, "openrouter_cost_usd": response.reported_cost_usd}
            )
        generation.update(
            output=response.output,
            usage_details={
                "input": response.input_tokens,
                "output": response.output_tokens,
                "cache_read_input_tokens": response.cache_read_tokens,
                "cache_creation_input_tokens": response.cache_write_tokens,
            },
            cost_details={"total": _usage_from(plan.model, response).cost_usd},
        )
    lf.flush()  # Phase 0 is CLI-driven and low-volume; never lose a trace to exit
    return response


def _usage_from(model: str, response: ProviderResponse) -> CallUsage:
    return CallUsage(
        model=model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cache_read_tokens=response.cache_read_tokens,
        cache_write_tokens=response.cache_write_tokens,
        cost_usd=cost_usd(
            model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cache_read_tokens=response.cache_read_tokens,
            cache_write_tokens=response.cache_write_tokens,
        ),
    )


def _tally(usage: CallUsage) -> None:
    tally = _active_tally.get()
    if tally is not None:
        tally.add(usage)


# ── the pinned §11.1 surface ─────────────────────────────────────────────────


async def call_structured[T: BaseModel](stage: str, schema: type[T], content: str) -> T:
    """Forced-schema call (§10.2 pattern P1): facts in, validated model out."""
    prompt = load_prompt(stage)
    model = model_for_stage(stage)
    digest = request_hash(stage, model, prompt.version, content)
    plan = _CallPlan(stage=stage, model=model, prompt=prompt, content=content, digest=digest)

    mode = llm_mode()
    if mode == "replay":
        recording = load_recording(stage, digest)
        response = ProviderResponse(
            output=dict(recording.output),
            input_tokens=recording.input_tokens,
            output_tokens=recording.output_tokens,
            cache_read_tokens=recording.cache_read_tokens,
            cache_write_tokens=recording.cache_write_tokens,
        )
    else:
        response = await _traced_live_call(plan, schema)
        if mode == "record":
            save_recording(
                digest,
                Recording(
                    stage=stage,
                    model=model,
                    prompt_version=prompt.version,
                    content_sha256=content_sha256(content),
                    output=response.output,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    cache_read_tokens=response.cache_read_tokens,
                    cache_write_tokens=response.cache_write_tokens,
                    recorded_at=now_iso(),
                ),
            )

    _tally(_usage_from(model, response))
    return schema.model_validate(response.output)


@dataclass(frozen=True)
class _AgentTurnRaw:
    """One live agent turn, normalized like ProviderResponse but tool-shaped."""

    tool_calls: list[ToolCall]
    text: str | None
    stop_reason: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reported_cost_usd: float | None = None


def _optional_prompt(stage: str) -> Prompt | None:
    """A stage's prompt file if one exists (tool-using stages may run prompt-less
    on `task` alone until their prompt lands, e.g. DISCOVER before P3-5)."""
    try:
        return load_prompt(stage)
    except PromptError:
        return None


def _agent_usage(model: str, raw: _AgentTurnRaw) -> CallUsage:
    return CallUsage(
        model=model,
        input_tokens=raw.input_tokens,
        output_tokens=raw.output_tokens,
        cache_read_tokens=raw.cache_read_tokens,
        cache_write_tokens=raw.cache_write_tokens,
        cost_usd=cost_usd(
            model,
            input_tokens=raw.input_tokens,
            output_tokens=raw.output_tokens,
            cache_read_tokens=raw.cache_read_tokens,
            cache_write_tokens=raw.cache_write_tokens,
        ),
    )


async def _live_agent_turn_openrouter(
    stage: str,
    model: str,
    prompt: Prompt | None,
    messages: list[dict[str, Any]],
    specs: list[ToolSpec],
) -> _AgentTurnRaw:
    from openai import AsyncOpenAI

    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SeamConfigError("OPENROUTER_API_KEY unset — cannot make a live call")

    convo: list[dict[str, Any]] = []
    if prompt is not None:
        system_parts: list[dict[str, Any]] = []
        if prompt.cacheable_prefix:
            system_parts.append(
                {
                    "type": "text",
                    "text": prompt.cacheable_prefix,
                    "cache_control": {"type": "ephemeral"},
                }
            )
        if prompt.per_call:
            system_parts.append({"type": "text", "text": prompt.per_call})
        if system_parts:
            convo.append({"role": "system", "content": system_parts})
    convo.extend(messages)

    client = AsyncOpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url=OPENROUTER_BASE_URL)
    response = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens_for_stage(stage),
        temperature=0.0,
        messages=convo,  # type: ignore[arg-type]
        tools=[
            {
                "type": "function",
                "function": {
                    "name": s.name,
                    "description": s.description,
                    "parameters": s.parameters,
                },
            }
            for s in specs
        ],
        tool_choice="auto",
        extra_body={
            "provider": {"order": openrouter_provider_order(model), "allow_fallbacks": False},
        },
    )

    message = response.choices[0].message
    tool_calls = [
        ToolCall(name=tc.function.name, input=json.loads(tc.function.arguments or "{}"))
        for tc in (message.tool_calls or [])
    ]
    usage = response.usage
    if usage is None:
        raise SeamConfigError(f"stage {stage!r}: OpenRouter response missing usage")
    details = getattr(usage, "prompt_tokens_details", None)
    cached = _usage_int(details, "cached_tokens")
    cache_write = _usage_int(details, "cache_write_tokens")
    uncached = max(0, (usage.prompt_tokens or 0) - cached - cache_write)
    reported_cost = getattr(usage, "cost", None)
    return _AgentTurnRaw(
        tool_calls=tool_calls,
        text=message.content,
        stop_reason="tool_use" if tool_calls else "stop",
        input_tokens=uncached,
        output_tokens=usage.completion_tokens or 0,
        cache_read_tokens=cached,
        cache_write_tokens=cache_write,
        reported_cost_usd=float(reported_cost) if reported_cost is not None else None,
    )


async def _traced_agent_turn(
    stage: str,
    model: str,
    prompt: Prompt | None,
    messages: list[dict[str, Any]],
    specs: list[ToolSpec],
) -> _AgentTurnRaw:
    """One agent turn wrapped in its own Langfuse generation — every turn is
    traced (NFR6: an untraced call is a bug)."""
    _require_langfuse_configured()
    ctx = _current_context()
    from langfuse import Langfuse, propagate_attributes

    lf: Langfuse = _langfuse()
    metadata: dict[str, Any] = {
        "mode": ctx.mode,
        "model": model,
        "prompt_version": prompt.version if prompt is not None else 0,
        "listing_slug": ctx.listing_slug,
        "llm_mode": llm_mode(),
        "pattern": "agent_loop",
    }
    with (
        propagate_attributes(trace_name=f"{ctx.job_type}/{stage}", session_id=ctx.job_id),
        lf.start_as_current_observation(
            name=f"{ctx.job_type}/{stage}",
            model=model,
            input=messages,
            as_type="generation",
            metadata=metadata,
        ) as generation,
    ):
        raw = await _live_agent_turn_openrouter(stage, model, prompt, messages, specs)
        if raw.reported_cost_usd is not None:
            generation.update(metadata={**metadata, "openrouter_cost_usd": raw.reported_cost_usd})
        generation.update(
            output={
                "text": raw.text,
                "tool_calls": [{"name": c.name, "input": c.input} for c in raw.tool_calls],
            },
            usage_details={
                "input": raw.input_tokens,
                "output": raw.output_tokens,
                "cache_read_input_tokens": raw.cache_read_tokens,
                "cache_creation_input_tokens": raw.cache_write_tokens,
            },
            cost_details={"total": _agent_usage(model, raw).cost_usd},
        )
    lf.flush()
    return raw


async def _agent_turn(
    stage: str,
    model: str,
    prompt: Prompt | None,
    messages: list[dict[str, Any]],
    specs: list[ToolSpec],
) -> TurnResponse:
    """One model turn with record/replay over the conversation-so-far (fixture per
    turn, keyed by the same `{stage}--{hash16}` convention as structured calls).
    The usage feeds the active cost tally in every mode, exactly like
    `call_structured`."""
    content = json.dumps(messages, sort_keys=True)
    prompt_version = prompt.version if prompt is not None else 0
    digest = request_hash(stage, model, prompt_version, content)
    mode = llm_mode()

    if mode == "replay":
        rec = load_recording(stage, digest)
        raw = _AgentTurnRaw(
            tool_calls=[
                ToolCall(name=tc["name"], input=tc["input"]) for tc in (rec.tool_calls or [])
            ],
            text=rec.text,
            stop_reason=rec.stop_reason or "stop",
            input_tokens=rec.input_tokens,
            output_tokens=rec.output_tokens,
            cache_read_tokens=rec.cache_read_tokens,
            cache_write_tokens=rec.cache_write_tokens,
        )
    else:
        raw = await _traced_agent_turn(stage, model, prompt, messages, specs)
        if mode == "record":
            save_recording(
                digest,
                Recording(
                    stage=stage,
                    model=model,
                    prompt_version=prompt_version,
                    content_sha256=content_sha256(content),
                    output={},
                    input_tokens=raw.input_tokens,
                    output_tokens=raw.output_tokens,
                    cache_read_tokens=raw.cache_read_tokens,
                    cache_write_tokens=raw.cache_write_tokens,
                    recorded_at=now_iso(),
                    tool_calls=[{"name": c.name, "input": c.input} for c in raw.tool_calls],
                    text=raw.text,
                    stop_reason=raw.stop_reason,
                ),
            )

    _tally(_agent_usage(model, raw))
    return TurnResponse(tool_calls=raw.tool_calls, text=raw.text)


async def call_agent(
    stage: str,
    task: str,
    tools: list[Any],
    max_turns: int = AGENT_MAX_TURNS,
) -> AgentResult:
    """Bounded tool loop (§10.2 pattern P3, IMPLEMENTATION §3 pinned signature).
    Only DISCOVER and location-type custom criteria may run one — the per-stage
    allow-list (`llm/config.STAGE_TOOLS`) is enforced inside `run_agent_loop`, not
    in stage code, so this seam is where the §16 zero-tool rule bites. Each turn
    routes through OpenRouter (traced, record/replay, usage → cost tally); budget
    exhaustion raises `AgentBudgetExceeded`."""
    model = model_for_stage(stage)
    prompt = _optional_prompt(stage)

    async def turn_fn(messages: list[dict[str, Any]], specs: list[ToolSpec]) -> TurnResponse:
        return await _agent_turn(stage, model, prompt, messages, specs)

    return await run_agent_loop(
        stage=stage, task=task, tools=tools, turn_fn=turn_fn, max_turns=max_turns
    )


async def call_vision[T: BaseModel](stage: str, schema: type[T], images: list[Any]) -> T:
    """Vision call (§10.2 pattern P4), with hash-only record/replay fixtures."""
    typed_images: list[VisionImage] = []
    for image in images:
        if not isinstance(image, VisionImage):
            raise TypeError("call_vision images must be VisionImage instances")
        if hashlib.sha256(image.data).hexdigest() != image.content_hash:
            raise ValueError(f"vision image hash mismatch for {image.label!r}")
        typed_images.append(image)
    prompt = load_prompt(stage)
    model = model_for_stage(stage)
    content = json.dumps(
        [
            {"sha256": image.content_hash, "media_type": image.media_type, "label": image.label}
            for image in typed_images
        ],
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = request_hash(stage, model, prompt.version, content)
    plan = _CallPlan(stage=stage, model=model, prompt=prompt, content=content, digest=digest)
    mode = llm_mode()
    if mode == "replay":
        recording = load_recording(stage, digest)
        response = ProviderResponse(
            output=dict(recording.output),
            input_tokens=recording.input_tokens,
            output_tokens=recording.output_tokens,
            cache_read_tokens=recording.cache_read_tokens,
            cache_write_tokens=recording.cache_write_tokens,
        )
    else:
        response = await _traced_live_vision_call(plan, schema, typed_images)
        if mode == "record":
            save_recording(
                digest,
                Recording(
                    stage=stage,
                    model=model,
                    prompt_version=prompt.version,
                    content_sha256=content_sha256(content),
                    output=response.output,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    cache_read_tokens=response.cache_read_tokens,
                    cache_write_tokens=response.cache_write_tokens,
                    recorded_at=now_iso(),
                    image_hashes=[image.content_hash for image in typed_images],
                ),
            )
    _tally(_usage_from(model, response))
    return schema.model_validate(response.output)
