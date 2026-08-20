"""Standalone worker-process startup and clean-shutdown contract."""

from __future__ import annotations

import asyncio
import signal
import sys

import pytest


class _Pool:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _SignalLoop:
    def __init__(self) -> None:
        self.handlers: dict[signal.Signals, tuple[object, tuple[object, ...]]] = {}

    def add_signal_handler(
        self, shutdown_signal: signal.Signals, callback: object, *args: object
    ) -> None:
        self.handlers[shutdown_signal] = (callback, args)


async def test_standalone_service_uses_postgres_dispatch_and_production_duties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import manzil_worker.service as service

    pool = _Pool()
    seen: dict[str, object] = {}

    async def create_pool(dsn: str, *, min_size: int, max_size: int) -> _Pool:
        seen["pool_dsn"] = dsn
        seen["min_size"] = min_size
        seen["max_size"] = max_size
        return pool

    def dispatch_builder(actual_pool: _Pool, *, dsn: str) -> dict[str, str]:
        seen["dispatch_pool"] = actual_pool
        seen["dispatch_dsn"] = dsn
        return {"durable": "dispatch"}

    async def worker_loop(actual_pool: _Pool, stop: asyncio.Event, **kwargs: object) -> None:
        seen["loop_pool"] = actual_pool
        seen["stop"] = stop
        seen.update(kwargs)

    monkeypatch.setattr(service.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(service, "build_dispatch", dispatch_builder)
    monkeypatch.setattr(service, "run_worker_loop", worker_loop)
    monkeypatch.setenv("MANZIL_MODE", "workflow")

    stop = asyncio.Event()
    await service.run_worker_service("postgresql://worker", stop=stop)

    assert seen["pool_dsn"] == "postgresql://worker"
    assert seen["min_size"] == 1
    assert seen["max_size"] == 4
    assert seen["dispatch_pool"] is pool
    assert seen["dispatch_dsn"] == "postgresql://worker"
    assert seen["loop_pool"] is pool
    assert seen["stop"] is stop
    assert seen["dispatch"] == {"durable": "dispatch"}
    assert seen["scheduler_tick"] is service.scheduler_tick
    assert seen["priority_tick"] is service.process_next_demo_publication
    assert seen["mode"] == "workflow"
    assert pool.closed is True


async def test_sigterm_requests_a_clean_worker_drain(monkeypatch: pytest.MonkeyPatch) -> None:
    import manzil_worker.service as service

    loop = _SignalLoop()
    stop = asyncio.Event()
    service.install_shutdown_signal_handlers(stop, event_loop=loop)  # type: ignore[arg-type]

    callback, args = loop.handlers[signal.SIGTERM]
    assert callable(callback)
    callback(*args)  # type: ignore[operator]
    assert stop.is_set()


async def test_process_passes_signal_owned_stop_event_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import manzil_worker.service as service

    loop = _SignalLoop()
    seen: dict[str, object] = {}

    monkeypatch.setattr(service.asyncio, "get_running_loop", lambda: loop)

    async def worker_service(dsn: str, *, stop: asyncio.Event) -> None:
        seen["dsn"] = dsn
        callback, args = loop.handlers[signal.SIGTERM]
        callback(*args)  # type: ignore[operator]
        seen["stopped"] = stop.is_set()

    monkeypatch.setattr(service, "run_worker_service", worker_service)
    await service.run_worker_process("postgresql://worker")

    assert seen == {"dsn": "postgresql://worker", "stopped": True}


def test_console_command_refuses_to_start_without_database_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    import manzil_worker.service as service

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["manzil-worker"])
    with pytest.raises(SystemExit, match="DATABASE_URL is required"):
        service.main()


def test_console_command_has_help_without_connecting_to_postgres(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import manzil_worker.service as service

    monkeypatch.setattr(sys, "argv", ["manzil-worker", "--help"])
    with pytest.raises(SystemExit, match="0"):
        service.main()

    assert "durable Postgres-backed pipeline worker" in capsys.readouterr().out
