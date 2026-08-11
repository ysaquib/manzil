"""Public product release and immutable deploy identity."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

FEEDBACK_VERSION_MAX_CHARS = 100


class BuildInfo(BaseModel):
    service: str = "api"
    release_version: str
    build_sha: str
    build_id: str
    environment: str


def release_version() -> str:
    return (Path(__file__).resolve().parents[3] / "VERSION").read_text().strip()


def build_sha() -> str:
    return os.getenv("RENDER_GIT_COMMIT") or os.getenv("GITHUB_SHA") or "dev"


def api_build_info(environment: str) -> BuildInfo:
    release = release_version()
    sha = build_sha()
    short = sha[:7] if sha != "dev" else sha
    return BuildInfo(
        release_version=release,
        build_sha=sha,
        build_id=f"{release}+{short}",
        environment=environment,
    )


def feedback_build_context(frontend_context: str | None, environment: str) -> str:
    """Attach the serving API build without trusting a client-supplied API suffix."""
    api_fragment = f"api {api_build_info(environment).build_id}"
    if not frontend_context:
        return api_fragment
    frontend_fragment = frontend_context.split(" · api ", 1)[0].strip()
    if not frontend_fragment.startswith("frontend "):
        frontend_fragment = f"frontend {frontend_fragment}"
    available = FEEDBACK_VERSION_MAX_CHARS - len(" · ") - len(api_fragment)
    return f"{frontend_fragment[:available]} · {api_fragment}"
