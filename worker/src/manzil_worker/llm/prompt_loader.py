"""Prompt files (IMPLEMENTATION §4 — settled).

Prompts live as markdown in `llm/prompts/{stage}.md` with a tiny front-matter
header (`id`, `version`, `cacheable_prefix_marker`). Everything above the
marker is the stable prefix sent with `cache_control` (schema text, rules,
few-shots); everything below is per-call. `version` is recorded on every
extraction row and every Langfuse trace — that is what makes the §8
prompt-change runbook enforceable. Prompt files are code: never edited in
place without a version bump.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

_REQUIRED_KEYS = ("id", "version")


class PromptError(ValueError):
    """A prompt file is malformed — fail loudly, never guess at a prompt."""


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    cacheable_prefix: str  # stable: sent with cache_control
    per_call: str  # instructions that accompany each call's content


def load_prompt(stage: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    path = prompts_dir / f"{stage}.md"
    if not path.exists():
        raise PromptError(f"no prompt file for stage {stage!r} at {path}")
    front, body = _split_front_matter(path.read_text(), path)
    for key in _REQUIRED_KEYS:
        if key not in front:
            raise PromptError(f"{path}: front-matter missing {key!r}")
    marker = front.get("cacheable_prefix_marker", "")
    if marker:
        if marker not in body:
            raise PromptError(f"{path}: cacheable_prefix_marker {marker!r} not found in body")
        prefix, _, per_call = body.partition(marker)
    else:
        # No marker: nothing is cacheable, the whole body rides per-call.
        prefix, per_call = "", body
    return Prompt(
        id=front["id"],
        version=int(front["version"]),
        cacheable_prefix=prefix.strip(),
        per_call=per_call.strip(),
    )


def _split_front_matter(text: str, path: Path) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise PromptError(f"{path}: prompt files must start with '---' front-matter")
    front: dict[str, str] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return front, "\n".join(lines[i + 1 :])
        key, sep, value = line.partition(":")
        if not sep:
            raise PromptError(f"{path}: bad front-matter line {line!r}")
        front[key.strip()] = value.strip()
    raise PromptError(f"{path}: unterminated front-matter")
