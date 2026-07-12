from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from manzil_api import privileged


@pytest.mark.asyncio
async def test_accept_is_idempotent_for_existing_member(
    collab_hunt, as_owner: AsyncClient, as_member: AsyncClient
) -> None:
    created = await as_owner.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/invites",
        json={"email": "member@test.manzil", "role": "curator"},
    )
    token = created.json()["link"].rsplit("/", 1)[-1]
    accepted = await as_member.post(f"/v1/invites/{token}/accept")
    assert accepted.status_code == 200
    assert accepted.json()["hunt_id"] == collab_hunt["hunt_id"]


@pytest.mark.asyncio
async def test_expired_and_revoked_invites_are_gone(
    collab_hunt, as_owner: AsyncClient, as_outsider: AsyncClient, db_pool
) -> None:
    expired_token = "expired-test-token"
    await db_pool.execute(
        """insert into invites (hunt_id, email, token, created_by, expires_at)
           values ($1, 'expired@example.com', $2, $3, $4)""",
        UUID(collab_hunt["hunt_id"]),
        expired_token,
        "00000000-0000-0000-0000-000000000001",
        datetime.now(UTC) - timedelta(days=1),
    )
    expired = await as_outsider.post(f"/v1/invites/{expired_token}/accept")
    assert expired.status_code == 410

    created = await as_owner.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/invites",
        json={"email": "revoked@example.com"},
    )
    invite_id = created.json()["id"]
    token = created.json()["link"].rsplit("/", 1)[-1]
    revoked = await as_owner.delete(f"/v1/invites/{invite_id}")
    assert revoked.status_code == 204
    gone = await as_outsider.post(f"/v1/invites/{token}/accept")
    assert gone.status_code == 410


@pytest.mark.asyncio
async def test_only_owner_can_create_invite(
    collab_hunt, as_member: AsyncClient, as_curator: AsyncClient
) -> None:
    for client in (as_member, as_curator):
        response = await client.post(f"/v1/hunts/{collab_hunt['hunt_id']}/invites", json={})
        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_role"


@pytest.mark.asyncio
async def test_email_invite_dispatches_supabase_auth(
    collab_hunt, as_owner: AsyncClient, monkeypatch
) -> None:
    sent: dict[str, str] = {}

    def fake_send(service_client, email: str, token: str, frontend_url: str) -> None:  # type: ignore[no-untyped-def]
        sent.update(email=email, token=token, frontend_url=frontend_url)

    monkeypatch.setattr(privileged, "send_invite_email", fake_send)
    response = await as_owner.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/invites",
        json={"email": "partner@example.com", "role": "member"},
    )
    assert response.status_code == 201
    assert sent["email"] == "partner@example.com"
    assert response.json()["link"].endswith(sent["token"])
