"""Cluster-wide OpenRouter slot behavior without a real database."""

from __future__ import annotations

import asyncio

from manzil_worker.llm.concurrency import PostgresOpenRouterGate


class _FakeConnection:
    def __init__(self, pool: _FakePool) -> None:
        self._pool = pool

    async def fetchval(self, sql: str, provider_key: int, slot: int) -> bool:
        key = (provider_key, slot)
        if "pg_try_advisory_lock" in sql:
            if key in self._pool.locks:
                return False
            self._pool.locks.add(key)
            return True
        assert "pg_advisory_unlock" in sql
        self._pool.locks.remove(key)
        return True


class _FakePool:
    def __init__(self) -> None:
        self.locks: set[tuple[int, int]] = set()
        self.released = 0

    async def acquire(self) -> _FakeConnection:
        return _FakeConnection(self)

    async def release(self, conn: _FakeConnection) -> None:
        self.released += 1


def test_google_calls_share_one_postgres_slot_across_workers(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import manzil_worker.llm.concurrency as concurrency

    monkeypatch.setattr(concurrency, "OPENROUTER_CONCURRENCY_POLL_SECONDS", 0)

    async def exercise() -> int:
        pool = _FakePool()
        gate = PostgresOpenRouterGate(pool)
        first_acquired = asyncio.Event()
        release_first = asyncio.Event()
        active = 0
        max_active = 0

        async def use_slot(*, wait: bool) -> None:
            nonlocal active, max_active
            async with gate.slot("google/gemini-3-flash-preview"):
                active += 1
                max_active = max(max_active, active)
                if wait:
                    first_acquired.set()
                    await release_first.wait()
                active -= 1

        first = asyncio.create_task(use_slot(wait=True))
        await first_acquired.wait()
        second = asyncio.create_task(use_slot(wait=False))
        await asyncio.sleep(0)
        assert max_active == 1
        release_first.set()
        await asyncio.gather(first, second)
        assert not pool.locks
        return max_active

    assert asyncio.run(exercise()) == 1
