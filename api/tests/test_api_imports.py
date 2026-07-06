"""Scaffold smoke test: the api package imports cleanly."""

import manzil_api


def test_api_imports() -> None:
    assert manzil_api.__doc__
