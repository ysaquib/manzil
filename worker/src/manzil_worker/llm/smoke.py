"""Seam smoke check (P0-7 exit gate: one traced call visible in Langfuse,
replay test green). `manzil llm-smoke` runs it live; the committed recording
of the same call is what CI replays."""

from __future__ import annotations

from pydantic import BaseModel

from manzil_worker.llm.client import call_structured

# The default token is deliberately constant: same stage + model + prompt
# version + content -> same request hash, so the CLI's record run refreshes
# exactly the fixture the replay test reads.
SMOKE_TOKEN = "manzil-smoke-p0-7"


class SmokeResult(BaseModel):
    echo: str
    model_family: str


async def run_smoke(token: str = SMOKE_TOKEN) -> SmokeResult:
    return await call_structured("smoke", SmokeResult, f"Token: {token}")
