"""Scaffold smoke test: the worker package and CLI entry point import cleanly."""

from manzil_worker.cli import app


def test_cli_app_exists() -> None:
    assert app.registered_commands
