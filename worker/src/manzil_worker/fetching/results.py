"""Fetch and cleaning result shapes shared across the fetching subsystem."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class FetchResult(BaseModel):
    """One fetch attempt at one tier. `status_code` 0 means the request itself
    failed (`error` holds why); header keys are lowercased.

    `status_code` and `headers` always describe **the target page**, never the
    transport that carried it. At tier 3 the managed unblocker is asked for an
    envelope so its own API status stays out of these fields — a provider that
    rejects us raises `FetchProviderError` instead of impersonating a target
    response. `provider` names that unblocker when one was used.
    """

    url: str
    final_url: str
    status_code: int
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = ""
    tier: int
    provider: str | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None
    screenshot: bytes | None = None


class CleanedPage(BaseModel):
    """Cleaner output: normalized text (fee tables + embedded data preserved)
    + its content hash."""

    text: str
    text_hash: str
    fee_tables_found: int = 0
    used_fallback: bool = False
    embedded_blobs: int = 0
