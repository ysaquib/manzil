"""Scaffold smoke test: the api package imports cleanly."""

import base64
import json

import manzil_api
import pytest
from local_supabase import LOCAL_ANON_KEY, LOCAL_SERVICE_ROLE_KEY


def test_api_imports() -> None:
    assert manzil_api.__doc__


@pytest.mark.parametrize(
    ("token", "role"),
    ((LOCAL_ANON_KEY, "anon"), (LOCAL_SERVICE_ROLE_KEY, "service_role")),
)
def test_local_supabase_keys_have_valid_jwt_claims(token: str, role: str) -> None:
    parts = token.split(".")
    assert len(parts) == 3
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload))
    assert claims["role"] == role
