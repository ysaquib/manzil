"""Public product release and immutable deploy identity."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


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
