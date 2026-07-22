"""Record/replay store (IMPLEMENTATION §5 — settled).

`MANZIL_LLM_MODE=record` runs live and writes each call's request-hash ->
response to `worker/tests/fixtures/recorded/`. The hash covers
`(stage, model_id, prompt_version, sha256(content))` — deliberately NOT the
raw request object, so SDK upgrades and parameter reordering don't invalidate
the cache, while any change that could alter model output does. `replay`
(the CI default) serves from disk and fails on any miss — CI can never
silently call a live model.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

_DEFAULT_RECORDED_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "recorded"


class ReplayMissError(LookupError):
    """Replay mode found no recording for this request — in CI this is a
    build failure by design (a miss means the test would spend tokens)."""


@dataclass(frozen=True)
class Recording:
    stage: str
    model: str
    prompt_version: int
    content_sha256: str
    output: dict[str, object]  # the structured payload the model emitted
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    recorded_at: str
    # Agent-turn recordings (P3-3 `call_agent`): a turn either emits tool calls or
    # a final message. All three stay None on structured (`call_structured`)
    # recordings, so every existing fixture on disk loads unchanged. The
    # conversation-so-far is the hashed `content`, keeping the `{stage}--{hash16}`
    # naming convention — one fixture per turn.
    tool_calls: list[dict] | None = None  # [{"name": ..., "input": {...}}, …]
    text: str | None = None  # the assistant's final (non-tool) message
    stop_reason: str | None = None  # "tool_use" | "stop"
    # Provider-hosted tool uses (P3-5 native web search) are already executed in
    # the response; replay retains their observability and exact provider cost.
    server_tool_events: list[dict] | None = None
    reported_cost_usd: float | None = None
    # P4 recordings retain the exact input identity without committing image bytes.
    image_hashes: list[str] | None = None


def recorded_dir() -> Path:
    """Fixture location; `MANZIL_RECORDED_DIR` overrides (tests use tmp dirs)."""
    override = os.environ.get("MANZIL_RECORDED_DIR")
    return Path(override) if override else _DEFAULT_RECORDED_DIR


def content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def request_hash(stage: str, model: str, prompt_version: int, content: str) -> str:
    key = f"{stage}\x00{model}\x00{prompt_version}\x00{content_sha256(content)}"
    return hashlib.sha256(key.encode()).hexdigest()


def _path_for(stage: str, digest: str) -> Path:
    # Stage prefix is for humans browsing the fixture dir; the digest is the key.
    return recorded_dir() / f"{stage}--{digest[:16]}.json"


def save_recording(digest: str, recording: Recording) -> Path:
    path = _path_for(recording.stage, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(recording), indent=2, sort_keys=True) + "\n")
    return path


def load_recording(stage: str, digest: str) -> Recording:
    path = _path_for(stage, digest)
    if not path.exists():
        raise ReplayMissError(
            f"replay miss for stage {stage!r} ({path.name}): no recording on disk. "
            "Re-record with MANZIL_LLM_MODE=record (spends tokens) — "
            "a prompt/model/content change invalidates old recordings by design."
        )
    data = json.loads(path.read_text())
    return Recording(**data)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
