from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture(autouse=True)
async def _notification_pool(app, db_pool):  # type: ignore[no-untyped-def]
    app.state.db_pool = db_pool


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
    assert (
        await db_pool.fetchval(
            """select d.status from private.notification_events e
             join private.notification_deliveries d on d.event_id=e.id
            where e.source_kind='invite' and e.source_id=$1""",
            UUID(invite_id),
        )
        == "cancelled"
    )
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
async def test_email_invite_queues_product_mail_without_creating_auth_account(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    email = "new-partner@example.com"
    before = await db_pool.fetchval("select count(*) from auth.users where email=$1", email)
    response = await as_owner.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/invites",
        json={"email": email, "role": "member"},
    )
    assert response.status_code == 201
    assert response.json()["delivery_status"] == "queued"
    assert "/invite/" in response.json()["link"]
    queued = await db_pool.fetchrow(
        """select e.event_type,e.context,d.recipient_email,d.status
             from private.notification_events e
             join private.notification_deliveries d on d.event_id=e.id
            where e.source_id=$1""",
        UUID(response.json()["id"]),
    )
    assert queued["event_type"] == "hunt_invited"
    assert queued["recipient_email"] == email
    context = json.loads(queued["context"])
    assert context["hunt_name"] == "Collab Hunt"
    assert await db_pool.fetchval("select count(*) from auth.users where email=$1", email) == before


@pytest.mark.asyncio
async def test_resend_reuses_active_invite_and_creates_new_delivery(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    created = await as_owner.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/invites",
        json={"email": "partner@example.com", "role": "member"},
    )
    refused = await as_owner.post(f"/v1/invites/{created.json()['id']}/resend")
    assert refused.status_code == 409
    assert refused.json()["code"] == "invite_delivery_not_retryable"

    await db_pool.execute(
        """update private.notification_deliveries d set status='failed'
             from private.notification_events e
            where d.event_id=e.id and e.source_kind='invite' and e.source_id=$1""",
        UUID(created.json()["id"]),
    )
    resent = await as_owner.post(f"/v1/invites/{created.json()['id']}/resend")
    assert resent.status_code == 200
    assert resent.json()["link"] == created.json()["link"]
    assert resent.json()["delivery_status"] == "queued"
    assert (
        await db_pool.fetchval(
            """select count(*) from private.notification_events
            where source_kind='invite' and source_id=$1""",
            UUID(created.json()["id"]),
        )
        == 2
    )
    duplicate = await as_owner.post(f"/v1/invites/{created.json()['id']}/resend")
    assert duplicate.status_code == 409
