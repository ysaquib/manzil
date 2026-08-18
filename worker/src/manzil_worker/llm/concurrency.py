"""Cross-worker OpenRouter concurrency gate.

The API currently hosts the durable worker loop in every process.  An in-memory
semaphore would therefore multiply its limit as the API scales horizontally.
Postgres advisory locks are cluster-wide, require no mutable application table,
and are released if a worker process dies.  A lock is held only around the
upstream request, never while a Job is doing fetch, projection, or backoff work.
"""

from __future__ import annotations

import asyncio
import zlib
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from manzil_shared.config import (
    OPENROUTER_CONCURRENCY_POLL_SECONDS,
    OPENROUTER_MAX_CONCURRENT_CALLS,
)

from manzil_worker.llm.config import provider_for_model

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg


class PostgresOpenRouterGate:
    """One bounded set of cluster-wide slots per upstream provider family."""

    def __init__(self, pool: asyncpg.Pool, *, slots: int = OPENROUTER_MAX_CONCURRENT_CALLS) -> None:
        if slots < 1:
            raise ValueError("OpenRouter concurrency slots must be at least one")
        self._pool = pool
        self._slots = slots

    @staticmethod
    def _provider_lock_key(provider: str) -> int:
        """Stable signed int32 namespace for a Manzil upstream provider."""
        value = zlib.crc32(f"manzil:openrouter:{provider}".encode())
        return value if value < 2**31 else value - 2**32

    @asynccontextmanager
    async def slot(self, model: str) -> AsyncIterator[None]:
        provider = provider_for_model(model)
        provider_key = self._provider_lock_key(provider)
        conn: asyncpg.Connection | None = None
        slot: int | None = None

        while conn is None:
            candidate = await self._pool.acquire()
            for candidate_slot in range(self._slots):
                if await candidate.fetchval(
                    "select pg_try_advisory_lock($1::integer, $2::integer)",
                    provider_key,
                    candidate_slot,
                ):
                    conn = candidate
                    slot = candidate_slot
                    break
            if conn is None:
                await self._pool.release(candidate)
                await asyncio.sleep(OPENROUTER_CONCURRENCY_POLL_SECONDS)

        try:
            yield
        finally:
            # Session-level advisory locks belong to this exact pooled
            # connection.  Always unlock before returning it to the pool.
            await conn.fetchval(
                "select pg_advisory_unlock($1::integer, $2::integer)", provider_key, slot
            )
            await self._pool.release(conn)


_gate: ContextVar[PostgresOpenRouterGate | None] = ContextVar("openrouter_gate", default=None)


@asynccontextmanager
async def use_postgres_openrouter_gate(pool: asyncpg.Pool) -> AsyncIterator[None]:
    """Install the queue worker's cluster-wide gate for descendant LLM calls."""
    token = _gate.set(PostgresOpenRouterGate(pool))
    try:
        yield
    finally:
        _gate.reset(token)


@asynccontextmanager
async def openrouter_slot(model: str) -> AsyncIterator[None]:
    """Acquire a provider slot when running under the durable worker loop.

    CLI and isolated seam tests intentionally have no Postgres gate; they make
    one call at a time and do not represent production worker concurrency.
    """
    gate = _gate.get()
    if gate is None:
        yield
        return
    async with gate.slot(model):
        yield
