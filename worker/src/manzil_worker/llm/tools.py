"""Tool registry + bounded agent-loop mechanics (DESIGN §10.2 pattern P3).

Three things live here, all SDK-free (the provider seam stays in `client.py`):

- the ``@tool`` decorator — a name→callable registry whose JSON schemas are
  derived from each function's signature + docstring, so the registry and the
  schemas the model sees cannot drift;
- ``run_agent_loop`` — the §10.2 turn-budgeted loop, verbatim in shape: call
  the model, execute its tool calls through the registry, feed results back,
  stop when it answers, and raise ``AgentBudgetExceeded`` when the budget is
  spent. The per-turn model call is injected (``turn_fn``) so the loop is pure
  and unit-testable and the OpenRouter/Langfuse machinery stays in the seam;
- the per-stage allow-list enforcement (``STAGE_TOOLS`` in ``llm/config.py``) —
  a §16 security control: extraction stages resolve to zero tools, and only the
  two allow-listed stages may run a loop at all.

Runtime dependencies a tool needs (fetchers, adapter registry, a DB connection,
the job-event sink) travel as an ambient ``ToolContext`` — the same contextvar
pattern the seam already uses for ``run_context`` / ``cost_tally`` — because the
pinned ``call_agent`` signature carries no context argument and the §10.2
pseudocode invokes a tool with only ``**call.input``.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import types
import typing
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog
from manzil_shared.config import AGENT_TOOL_RESULT_SUMMARY_CAP
from manzil_shared.errors import AgentBudgetExceeded, StageFatal

from manzil_worker.llm.config import allowed_tools

if TYPE_CHECKING:
    from collections.abc import Iterator

    from manzil_worker.fetching.registry import AdapterRegistry
    from manzil_worker.fetching.tiers import Fetcher

log = structlog.get_logger()


class ToolNotAllowed(StageFatal):
    """A stage requested a tool outside its §16 allow-list (or is not an
    allow-listed tool-loop stage at all). Fatal: this is a security-control
    violation, not a transient condition."""


# ── the tool registry + @tool decorator ──────────────────────────────────────


@dataclass(frozen=True)
class ToolSpec:
    """A registered tool: its LLM-facing name/description/JSON-schema and the
    async callable that runs it."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema (object) derived from the signature
    func: Callable[..., Awaitable[Any]]
    # How this tool's result should be recorded in its `tool_called` job event,
    # when the default -- truncate the result -- would disclose something. See
    # `_summarize`. None means the default.
    summarize: Callable[[Any], str] | None = None


REGISTRY: dict[str, ToolSpec] = {}

_JSON_SCALARS: dict[type, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _annotation_schema(annotation: Any) -> tuple[dict[str, Any], bool]:
    """(JSON-schema fragment, required-by-type) for one parameter annotation.
    `required-by-type` is False for Optional (``X | None``) — the model may omit
    it — and True otherwise; a default on the parameter also drops `required`."""
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return {"type": "string", "enum": list(typing.get_args(annotation))}, True
    if origin in (types.UnionType, typing.Union):
        non_none = [a for a in typing.get_args(annotation) if a is not type(None)]
        base, _ = _annotation_schema(non_none[0]) if non_none else ({"type": "string"}, True)
        return base, False  # Optional → never required by type
    if origin in (list, tuple):
        return {"type": "array"}, True
    if annotation in _JSON_SCALARS:
        return {"type": _JSON_SCALARS[annotation]}, True
    return {"type": "string"}, True  # conservative fallback


def _schema_from_signature(func: Callable[..., Any]) -> dict[str, Any]:
    sig = inspect.signature(func)
    # `from __future__ import annotations` makes annotations lazy strings; resolve
    # them to real types so `float` maps to "number", not the string fallback.
    try:
        hints = typing.get_type_hints(func)
    except Exception:  # pragma: no cover - unresolvable forward ref: fall back
        hints = {}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        annotation = hints.get(pname, param.annotation)
        schema, required_by_type = _annotation_schema(annotation)
        properties[pname] = schema
        if param.default is inspect.Parameter.empty and required_by_type:
            required.append(pname)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def tool(
    func: Callable[..., Awaitable[Any]] | None = None,
    *,
    name: str | None = None,
    summarize: Callable[[Any], str] | None = None,
) -> Any:
    """Register an async function as a tool. The JSON schema is derived from the
    signature (every parameter is LLM-facing — runtime deps come from
    ``ToolContext``); the description is the docstring's first line. The wrapped
    function is returned unchanged, so tools remain directly callable/testable.

    ``summarize`` overrides how the result is recorded in the tool's job event —
    declared here, next to the tool, because whether a result is safe to store
    is a property of the tool and not of the loop."""

    def wrap(f: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        if not inspect.iscoroutinefunction(f):
            raise TypeError(f"@tool {f.__name__!r} must be async (tools are awaited)")
        doc = (inspect.getdoc(f) or "").strip()
        spec = ToolSpec(
            name=name or f.__name__,
            description=doc.split("\n", 1)[0],
            parameters=_schema_from_signature(f),
            func=f,
            summarize=summarize,
        )
        REGISTRY[spec.name] = spec
        f._tool_spec = spec  # type: ignore[attr-defined]
        return f

    return wrap(func) if func is not None else wrap


def tool_spec(t: Callable[..., Any]) -> ToolSpec:
    """The ToolSpec attached to a @tool-decorated function."""
    spec = getattr(t, "_tool_spec", None)
    if spec is None:
        raise TypeError(f"{t!r} is not a @tool-decorated function")
    assert isinstance(spec, ToolSpec)
    return spec


# ── ambient tool context (runtime deps the model never sees) ──────────────────

# (stage, tool_name, tool_input, result_summary) -> None. The DISCOVER/ENRICH
# stages build a Postgres-backed sink (see `postgres_persistence.make_tool_event_sink`);
# CLI/file runs leave it None and the loop logs instead (graceful degradation).
ToolEventSink = Callable[[str, str, dict[str, Any], str], Awaitable[None]]


@dataclass
class ToolContext:
    """Runtime dependencies for a tool run, ambient so they never enter the
    model-facing schema. Set by the stage (or a test) around ``call_agent``."""

    fetchers: dict[int, Fetcher] = field(default_factory=dict)
    registry: AdapterRegistry | None = None
    conn: Any = None  # asyncpg connection/pool for geocode_property's cache
    event_sink: ToolEventSink | None = None
    maps_transport: Any = None  # httpx transport injected by tests; None → real


_tool_context: ContextVar[ToolContext | None] = ContextVar("manzil_tool_context", default=None)


def current_tool_context() -> ToolContext:
    """The active ToolContext, or an empty one (no deps wired) outside a loop."""
    return _tool_context.get() or ToolContext()


@contextmanager
def tool_context(ctx: ToolContext) -> Iterator[None]:
    token = _tool_context.set(ctx)
    try:
        yield
    finally:
        _tool_context.reset(token)


# ── the bounded loop (§10.2 pattern P3) ───────────────────────────────────────


@dataclass(frozen=True)
class ToolCall:
    """One tool call the model asked for this turn (provider ids are ignored —
    the loop assigns deterministic ids so record/replay conversations hash
    identically)."""

    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class TurnResponse:
    """One model turn, normalized: either tool calls or a final message."""

    tool_calls: list[ToolCall]
    text: str | None = None
    server_tool_events: tuple[ServerToolEvent, ...] = ()


@dataclass(frozen=True)
class ServerToolEvent:
    """One provider-hosted tool use already executed inside a model turn."""

    name: str
    input: dict[str, Any]
    result: str


@dataclass(frozen=True)
class AgentResult:
    """What a completed loop yields to the calling stage."""

    final_text: str
    turns: int


# The injected per-turn model call: conversation-so-far + the offered tool specs
# -> the normalized response. `client.call_agent` supplies the OpenRouter/traced
# implementation; tests supply a fake, so the loop needs no provider.
TurnFn = Callable[[list[dict[str, Any]], "list[ToolSpec]"], Awaitable[TurnResponse]]


def _summarize(result: Any, spec: ToolSpec | None = None) -> tuple[str, str]:
    """(full JSON string for the model, capped summary for the job event).

    The two halves are not the same text for every tool, and assuming they were
    is what put a raw page prefix in `job_events.detail`: `fetch_page` returns a
    whole cleaned page body, the default summary stored its first 2 KB, and that
    table is member- and demo-readable. Truncation is not redaction. A tool whose
    result is not safe to store declares its own event summary (`@tool(
    summarize=...)`); the default stays for tools whose results are already
    bounded facts.

    Structural residual: this is per-tool, so the next body-returning tool
    inherits the same hazard unless its author remembers. A general fix belongs
    with the tool registry (DESIGN §17)."""
    full = result if isinstance(result, str) else json.dumps(result, default=str)
    if spec is not None and spec.summarize is not None:
        return full, spec.summarize(result)[:AGENT_TOOL_RESULT_SUMMARY_CAP]
    return full, full[:AGENT_TOOL_RESULT_SUMMARY_CAP]


async def _emit_tool_event(stage: str, name: str, tool_input: dict[str, Any], summary: str) -> None:
    ctx = current_tool_context()
    if ctx.event_sink is not None:
        await ctx.event_sink(stage, name, tool_input, summary)
    else:  # CLI/file mode: no Postgres → log only (graceful degradation)
        log.info("tool_called", stage=stage, tool=name, input=tool_input, result=summary)


async def _execute_tool(stage: str, call: ToolCall, offered: dict[str, ToolSpec]) -> str:
    """Run one tool call and emit its `tool_called` event. An unknown or
    disallowed tool name yields a clean error result fed back to the model —
    never a crash — so a hallucinated tool call cannot break the loop."""
    spec = offered.get(call.name)
    if spec is None:
        log.warning("tool_unknown", stage=stage, tool=call.name)
        return json.dumps({"error": f"unknown tool {call.name!r}"})
    try:
        result = await spec.func(**call.input)
        full, summary = _summarize(result, spec)
    except Exception as exc:  # a tool failure is a result, not a loop crash
        log.warning("tool_failed", stage=stage, tool=call.name, error=repr(exc))
        full, summary = _summarize({"error": str(exc)}, spec)
    await _emit_tool_event(stage, call.name, call.input, summary)
    return full


def _enforce_allow_list(stage: str, specs: list[ToolSpec]) -> None:
    allowed = allowed_tools(stage)
    if stage not in _allowed_stages():
        raise ToolNotAllowed(
            f"stage {stage!r} is not an allow-listed tool-loop stage (§16) — "
            f"only {sorted(_allowed_stages())} may run a bounded tool loop"
        )
    for spec in specs:
        if spec.name not in allowed:
            raise ToolNotAllowed(
                f"stage {stage!r} may not use tool {spec.name!r}; allow-list is {allowed}"
            )


def _allowed_stages() -> set[str]:
    from manzil_worker.llm.config import STAGE_TOOLS

    return {s for s, tools in STAGE_TOOLS.items() if tools}


async def run_agent_loop(
    *,
    stage: str,
    task: str,
    tools: list[Callable[..., Awaitable[Any]]],
    turn_fn: TurnFn,
    max_turns: int,
) -> AgentResult:
    """The §10.2 bounded loop. Enforces the per-stage allow-list first (a §16
    control), then walks up to `max_turns` model turns, executing tool calls
    through the offered set. Returns the final non-tool message; raises
    ``AgentBudgetExceeded`` once the budget is spent — a real outcome the calling
    stage handles."""
    specs = [tool_spec(t) for t in tools]
    _enforce_allow_list(stage, specs)
    offered = {s.name: s for s in specs}

    messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
    for turn in range(max_turns):
        response = await turn_fn(messages, specs)
        # Server tools have already executed provider-side; emit the same
        # observable `tool_called` event as local tools before returning/looping.
        for event in response.server_tool_events:
            await _emit_tool_event(stage, event.name, event.input, event.result)
        if not response.tool_calls:
            return AgentResult(final_text=response.text or "", turns=turn + 1)
        # Deterministic ids so the recorded/replayed conversation hashes match.
        assistant_calls = [
            {
                "id": f"call_{turn}_{i}",
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.input, sort_keys=True)},
            }
            for i, c in enumerate(response.tool_calls)
        ]
        messages.append(
            {"role": "assistant", "content": response.text, "tool_calls": assistant_calls}
        )
        for i, call in enumerate(response.tool_calls):
            result = await _execute_tool(stage, call, offered)
            messages.append({"role": "tool", "tool_call_id": f"call_{turn}_{i}", "content": result})
    raise AgentBudgetExceeded(
        f"stage {stage!r}: agent exceeded its {max_turns}-turn budget without answering"
    )


# ── fetch_page: the shared fetching tool (§10.2, §16 SSRF posture) ────────────


def _fetch_page_event_summary(result: Any) -> str:
    """What one `fetch_page` call gets to leave in `job_events.detail`: how much
    text came back and which text it was, never the text itself.

    A success is a ``str`` (the cleaned page) and a refusal is a ``dict``, and
    the discrimination is on that type rather than on parsing the value. Parsing
    would mean a cleaned page that happened to look like the refusal JSON gets
    echoed into the event — the exact "surely not" that this whole finding is
    made of.

    The hash is the same identity `property_sources.cleaned_text_hash` records,
    so a support question ("did the two fetches see the same page?") is still
    answerable from the event log without the page being in it.
    """
    if isinstance(result, str):
        return json.dumps(
            {
                "outcome": "fetched",
                "chars": len(result),
                "sha256": hashlib.sha256(result.encode("utf-8")).hexdigest(),
            }
        )
    return json.dumps(result, default=str)


@tool(summarize=_fetch_page_event_summary)
async def fetch_page(url: str) -> str | dict[str, str]:
    """Fetch a public web page and return its cleaned text.

    Routes through the tier ladder (§10.7), so it inherits the adapter registry,
    per-domain tiers, rate limits, and politeness. Two-layer §16 SSRF control: the
    VALIDATE_URL literal host checks run first (identical to submission — reject a
    private/loopback/non-http(s) URL before any network), and the tier fetchers
    then resolve every host (and every redirect hop) and refuse any that lands on a
    non-global address. So a tool loop can never be steered into fetching internal
    infrastructure, even via a public hostname that resolves private. The returned
    text is length-capped.

    A refusal comes back as a ``dict`` rather than a JSON *string*: the loop
    serialises it to exactly the same bytes for the model, and the type is what
    lets `_fetch_page_event_summary` tell "this is a reason" from "this is a
    page" without parsing a page body.
    """
    # Local import breaks the import cycle (validate_url → stages.base → client →
    # tools). By call time every module is loaded.
    from manzil_shared.config import FETCH_PAGE_MAX_CHARS
    from manzil_shared.errors import FetchProviderError, PrivateAddressRefused
    from manzil_shared.errors import StageFatal as _StageFatal

    from manzil_worker.fetching.ladder import fetch_with_ladder
    from manzil_worker.stages.validate_url import normalize_url

    ctx = current_tool_context()
    if ctx.registry is None or not ctx.fetchers:
        raise StageFatal("fetch_page: no fetchers/registry in the ToolContext")

    try:
        safe_url = normalize_url(url)  # scheme + public-host + not-a-binary checks
    except _StageFatal as exc:
        # A refused URL is a tool result, not a loop crash — hand the reason back.
        # The check is on URL shape only (deterministic, pre-network), so this
        # leaks no timing/reachability oracle about internal hosts.
        log.warning("fetch_page_refused", url=url, reason=str(exc))
        return {"error": f"refused: {exc}"}

    try:
        ladder = await fetch_with_ladder(safe_url, ctx.registry, ctx.fetchers)
    except PrivateAddressRefused as exc:
        # The DNS-resolving guard fired inside a tier (host resolved private, or a
        # redirect hop pointed at an internal address). Loop-visible tool error,
        # not a crash — same shape as the literal refusal above.
        log.warning("fetch_page_refused", url=url, reason=str(exc))
        return {"error": f"refused: {exc}"}
    except FetchProviderError as exc:
        # The unblocker refused *us*, not this URL (§20 2026-08-11). Same posture:
        # a misconfigured zone must not crash a tool loop, and the model is told
        # the page is unavailable rather than that it said something it did not.
        log.warning("fetch_page_provider_error", url=url, reason=str(exc))
        return {"error": f"unavailable: {exc}"}

    return ladder.cleaned.text[:FETCH_PAGE_MAX_CHARS]
