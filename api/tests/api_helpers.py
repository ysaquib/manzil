"""Shared API test helpers: the fake authenticated user context. Lives outside
conftest.py because test modules import these by name, and bare `conftest`
imports collide across suites in a root-level pytest run."""

from __future__ import annotations

from manzil_api.dependencies import UserContext

FAKE_USER = UserContext(
    id="00000000-0000-0000-0000-000000000001",
    email="dev@example.com",
    access_token="fake-token",
)
