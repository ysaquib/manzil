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

Structured output is forced tool use: one tool whose input schema is the
Pydantic model's JSON schema, `tool_choice` pinned to it — the model cannot
answer in prose.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from manzil_worker.llm.config import cost_usd, max_tokens_for_stage, model_for_stage
from manzil_worker.llm.prompt_loader import Prompt, load_prompt
from manzil_worker.llm.recording import (
    Recording,
    content_sha256,
    load_recording,
    now_iso,
    request_hash,
    save_recording,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

STRUCTURED_TOOL_NAME = "emit_result"


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
    # runs (CI) never touch either SDK's import-time machinery.
    from langfuse import Langfuse

    return Langfuse(host=os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com"))


async def _live_call(plan: _CallPlan, schema: type[BaseModel]) -> ProviderResponse:
    """One real Anthropic call: cached prefix + per-call system, forced tool."""
    from anthropic import AsyncAnthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SeamConfigError("ANTHROPIC_API_KEY unset — cannot make a live call")

    system: list[dict[str, Any]] = []
    if plan.prompt.cacheable_prefix:
        system.append(
            {
                "type": "text",
                "text": plan.prompt.cacheable_prefix,
                "cache_control": {"type": "ephemeral"},
            }
        )
    if plan.prompt.per_call:
        system.append({"type": "text", "text": plan.prompt.per_call})

    client = AsyncAnthropic()
    response = await client.messages.create(
        model=plan.model,
        max_tokens=max_tokens_for_stage(plan.stage),
        temperature=0.0,
        system=system,  # type: ignore[arg-type]
        messages=[{"role": "user", "content": plan.content}],
        tools=[
            {
                "name": STRUCTURED_TOOL_NAME,
                "description": "Emit the structured result. Always call this tool.",
                "input_schema": schema.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": STRUCTURED_TOOL_NAME},
    )
    tool_blocks = [b for b in response.content if b.type == "tool_use"]
    if not tool_blocks:
        raise SeamConfigError(
            f"stage {plan.stage!r}: model returned no tool_use block despite forced tool_choice"
        )
    usage = response.usage
    return ProviderResponse(
        output=dict(tool_blocks[0].input),  # type: ignore[arg-type]
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_write_tokens=usage.cache_creation_input_tokens or 0,
    )


async def _traced_live_call(plan: _CallPlan, schema: type[BaseModel]) -> ProviderResponse:
    """Live call wrapped in its Langfuse generation (IMPL §6): trace named
    `{job_type}/{stage}`, session = job_id, metadata carries mode / model /
    prompt_version / listing_slug plus token and cost figures."""
    _require_langfuse_configured()
    ctx = _current_context()
    from langfuse import Langfuse
    lf: Langfuse = _langfuse()
    with lf.start_as_current_observation(
        name=f"{ctx.job_type}/{plan.stage}",
        model=plan.model,
        input=plan.content,
        as_type="generation",
        metadata={
            "mode": ctx.mode,
            "model": plan.model,
            "prompt_version": plan.prompt.version,
            "listing_slug": ctx.listing_slug,
            "llm_mode": llm_mode(),
        },
    ) as generation:
        lf.update_current_trace(name=f"{ctx.job_type}/{plan.stage}", session_id=ctx.job_id)
        response = await _live_call(plan, schema)
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


async def call_agent(stage: str, task: str, tools: list[Any], max_turns: int = 8) -> Any:
    """Bounded tool loop (§10.2 pattern P3). No Phase 0 stage uses tool loops —
    only DISCOVER and location-type custom criteria do, and both land in
    Phase 3. Defined here because the seam's surface is pinned (§11.1)."""
    raise NotImplementedError("call_agent lands with its first consumer (P3-5 DISCOVER)")


async def call_vision[T: BaseModel](stage: str, schema: type[T], images: list[Any]) -> T:
    """Vision call (§10.2 pattern P4). First consumer is P3-7 IMAGES/VISION."""
    raise NotImplementedError("call_vision lands with its first consumer (P3-7 VISION)")
