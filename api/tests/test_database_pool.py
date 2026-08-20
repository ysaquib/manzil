"""API direct-Postgres pool sizing regressions."""

from __future__ import annotations

from types import SimpleNamespace


async def test_api_pool_caps_connections_for_overlapping_render_deploys(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import manzil_api.database as database

    seen: dict[str, object] = {}

    async def create_pool(dsn: str, *, min_size: int, max_size: int) -> object:
        seen.update(dsn=dsn, min_size=min_size, max_size=max_size)
        return object()

    monkeypatch.setattr(database.asyncpg, "create_pool", create_pool)

    await database.create_db_pool(SimpleNamespace(database_url="postgresql://api"))

    assert seen == {"dsn": "postgresql://api", "min_size": 1, "max_size": 4}
