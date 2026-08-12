from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import AsyncClient
from manzil_api.config import get_settings
from manzil_api.email.dispatcher import apply_resend_webhook, process_next_delivery
from manzil_api.email.render import render_email
from postgrest.exceptions import APIError
from svix.webhooks import Webhook

EVENTS = {
    "checkpoint_waiting": True,
    "run_failed": True,
    "listing_score_changed": False,
    "comment_added": False,
    "rating_changed": False,
}


@pytest.fixture(autouse=True)
def _attach_pool(app, db_pool):  # type: ignore[no-untyped-def]
    app.state.db_pool = db_pool


def test_invite_template_is_product_mail_and_escapes_hunt_content() -> None:
    rendered = render_email(
        "hunt_invited",
        {
            "inviter_name": "Nadia\r\nBcc: attacker@example.com",
            "hunt_name": "<script>Jersey City</script>",
            "role": "member",
            "expires_at_display": "August 17, 2026",
            "cta_url": "https://manzil.example/invite/bare-token",
        },
    )

    assert "\r" not in rendered.subject and "\n" not in rendered.subject
    assert rendered.subject.startswith("Nadia Bcc: attacker@example.com invited you")
    assert "You\u2019re invited to &lt;script&gt;Jersey City&lt;/script&gt;" in rendered.html
    assert "https://manzil.example/invite/bare-token" in rendered.html
    assert "ConfirmationURL" not in rendered.html
    assert "sign in link" not in rendered.text.lower()


@pytest.mark.parametrize(
    ("event_type", "context"),
    [
        (
            "checkpoint_waiting",
            {
                "property_name": "The Ellsworth",
                "cta_url": "https://app/tasks",
                "alerts_url": "https://app/alerts",
            },
        ),
        (
            "run_failed",
            {
                "property_name": "The Ellsworth",
                "cta_url": "https://app/tasks",
                "alerts_url": "https://app/alerts",
            },
        ),
        (
            "listing_score_changed",
            {
                "property_name": "The Ellsworth",
                "changes": [{"old_total": 4, "new_total": 5}],
                "cta_url": "https://app/listing",
                "alerts_url": "https://app/alerts",
            },
        ),
        (
            "comment_added",
            {
                "actor_name": "Nadia",
                "hunt_name": "Detroit",
                "property_name": "The Ellsworth",
                "cta_url": "https://app/listing",
                "alerts_url": "https://app/alerts",
            },
        ),
        (
            "rating_changed",
            {
                "actor_name": "Nadia",
                "hunt_name": "Detroit",
                "property_name": "The Ellsworth",
                "rating": 4.5,
                "cta_url": "https://app/listing",
                "alerts_url": "https://app/alerts",
            },
        ),
    ],
)
def test_product_templates_render_html_and_text(
    event_type: str, context: dict[str, object]
) -> None:
    rendered = render_email(event_type, context)
    assert rendered.subject
    assert context["cta_url"] in rendered.html
    assert context["cta_url"] in rendered.text


@pytest.mark.asyncio
async def test_account_defaults_and_hunt_override_inheritance(
    collab_hunt, as_member: AsyncClient
) -> None:
    account = await as_member.get("/v1/notification-preferences")
    assert account.status_code == 200
    assert account.json() == {"email": EVENTS}

    changed = dict(EVENTS)
    changed["comment_added"] = True
    saved = await as_member.put("/v1/notification-preferences", json={"email": changed})
    assert saved.status_code == 200
    assert saved.json()["email"] == changed

    inherited = await as_member.get(f"/v1/hunts/{collab_hunt['hunt_id']}/notification-preferences")
    assert inherited.status_code == 200
    assert inherited.json()["effective_email"] == changed
    assert all(value is None for value in inherited.json()["email_overrides"].values())

    overrides = dict.fromkeys(EVENTS)
    overrides["comment_added"] = False
    overridden = await as_member.put(
        f"/v1/hunts/{collab_hunt['hunt_id']}/notification-preferences",
        json={"email_overrides": overrides},
    )
    assert overridden.status_code == 200
    assert overridden.json()["effective_email"]["comment_added"] is False
    assert overridden.json()["account_email"]["comment_added"] is True


@pytest.mark.asyncio
async def test_notification_preferences_are_self_scoped_and_outbox_is_private(
    collab_hunt, seeded_users, db_pool
) -> None:
    owner = seeded_users["owner"]
    member = seeded_users["member"]
    outsider = seeded_users["outsider"]
    try:
        created = (
            owner.supabase.table("user_notification_prefs")
            .insert(
                {
                    "user_id": owner.user_id,
                    "event_type": "rating_changed",
                    "channel": "email",
                    "enabled": True,
                }
            )
            .execute()
        )
        assert len(created.data) == 1
        assert (
            member.supabase.table("user_notification_prefs")
            .select("*")
            .eq("user_id", owner.user_id)
            .execute()
            .data
            == []
        )
        with pytest.raises(APIError):
            member.supabase.table("user_notification_prefs").insert(
                {
                    "user_id": owner.user_id,
                    "event_type": "comment_added",
                    "channel": "email",
                    "enabled": True,
                }
            ).execute()

        hunt_created = (
            member.supabase.table("hunt_notification_prefs")
            .insert(
                {
                    "hunt_id": collab_hunt["hunt_id"],
                    "user_id": member.user_id,
                    "event_type": "rating_changed",
                    "channel": "email",
                    "enabled": True,
                }
            )
            .execute()
        )
        assert len(hunt_created.data) == 1
        assert (
            outsider.supabase.table("hunt_notification_prefs")
            .select("*")
            .eq("hunt_id", collab_hunt["hunt_id"])
            .execute()
            .data
            == []
        )
        with pytest.raises(APIError):
            outsider.supabase.rpc(
                "set_hunt_notification_preferences",
                {
                    "p_hunt_id": collab_hunt["hunt_id"],
                    "p_overrides": dict.fromkeys(EVENTS),
                },
            ).execute()
        assert not await db_pool.fetchval(
            "select has_table_privilege('authenticated','private.notification_events','select')"
        )
        assert not await db_pool.fetchval(
            "select has_table_privilege('authenticated','private.notification_deliveries','select')"
        )
        exposed_helpers = await db_pool.fetch(
            """select p.proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace
                 where n.nspname='private' and (
                       p.proname like 'notification_%'
                    or p.proname like 'enqueue_%notification'
                    or p.proname = 'cancel_hunt_invitation_delivery'
                 ) and has_function_privilege('authenticated',p.oid,'execute')"""
        )
        assert exposed_helpers == []
    finally:
        owner.supabase.table("user_notification_prefs").delete().eq(
            "event_type", "rating_changed"
        ).execute()


@pytest.mark.asyncio
async def test_comment_and_job_triggers_apply_recipient_rules(
    collab_hunt, seeded_users, db_pool
) -> None:
    owner = seeded_users["owner"]
    member = seeded_users["member"]
    hunt_id = UUID(collab_hunt["hunt_id"])
    listing_id = UUID(collab_hunt["member_listing_id"])

    # Collaboration mail is opt-in. Only the Owner opts in, and the actor is
    # excluded, so this comment yields exactly one delivery.
    await db_pool.execute(
        """insert into user_notification_prefs(user_id,event_type,channel,enabled)
           values ($1,'comment_added','email',true)""",
        UUID(owner.user_id),
    )
    comment_id = await db_pool.fetchval(
        "insert into comments(hunt_listing_id,user_id,body) values($1,$2,'hello') returning id",
        listing_id,
        UUID(member.user_id),
    )
    comment_recipients = await db_pool.fetch(
        """select d.recipient_user_id from private.notification_events e
             join private.notification_deliveries d on d.event_id=e.id
            where e.source_kind='comment' and e.source_id=$1""",
        comment_id,
    )
    assert [row["recipient_user_id"] for row in comment_recipients] == [UUID(owner.user_id)]

    job_id = await db_pool.fetchval(
        """insert into jobs(hunt_id,hunt_listing_id,type,state)
           values($1,$2,'ingest','queued') returning id""",
        hunt_id,
        listing_id,
    )
    checkpoint_id = await db_pool.fetchval(
        """insert into job_events(job_id,stage,event,detail)
           values($1,'VERIFY','checkpoint_asked','{}') returning id""",
        job_id,
    )
    checkpoint_recipients = await db_pool.fetch(
        """select d.recipient_user_id from private.notification_events e
             join private.notification_deliveries d on d.event_id=e.id
            where e.source_kind='job_event' and e.source_id=$1""",
        checkpoint_id,
    )
    assert [row["recipient_user_id"] for row in checkpoint_recipients] == [UUID(member.user_id)]

    await db_pool.execute(
        "update jobs set state='failed', error='test failure' where id=$1", job_id
    )
    failed_recipients = await db_pool.fetch(
        """select d.recipient_user_id from private.notification_events e
             join private.notification_deliveries d on d.event_id=e.id
            where e.source_kind='job' and e.source_id=$1 order by d.recipient_email""",
        job_id,
    )
    assert {row["recipient_user_id"] for row in failed_recipients} == {
        UUID(member.user_id),
        UUID(owner.user_id),
    }


@pytest.mark.asyncio
async def test_attention_reports_hunt_wide_job_severity(
    collab_hunt, as_owner: AsyncClient, as_member: AsyncClient, db_pool
) -> None:
    """Attention is hunt-wide (DESIGN/IMPLEMENTATION 2.0.161), not role-scoped.

    Members and Owners both see failed/waiting/running counts plus a strict
    severity `task_status`; waiting_checkpoint_count stays as the waiting_user
    alias for the Tasks badge.
    """
    await db_pool.execute(
        """insert into jobs(hunt_id,hunt_listing_id,type,state)
           values($1,$2,'ingest','waiting_user')""",
        UUID(collab_hunt["hunt_id"]),
        UUID(collab_hunt["owner_listing_id"]),
    )
    expected = {
        "waiting_checkpoint_count": 1,
        "failed": 0,
        "waiting_user": 1,
        "running": 0,
        "task_status": "waiting_user",
    }
    owner = await as_owner.get(f"/v1/hunts/{collab_hunt['hunt_id']}/attention")
    member = await as_member.get(f"/v1/hunts/{collab_hunt['hunt_id']}/attention")

    assert owner.json() == expected
    assert member.json() == expected


@pytest.mark.asyncio
async def test_dispatcher_uses_bare_invite_and_stable_idempotency_key(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    response = await as_owner.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/invites",
        json={"email": "delivery@example.com", "role": "member"},
    )
    assert response.status_code == 201
    invite_id = UUID(response.json()["id"])
    delivery = await db_pool.fetchrow(
        """select d.id from private.notification_events e
             join private.notification_deliveries d on d.event_id=e.id
            where e.source_kind='invite' and e.source_id=$1""",
        invite_id,
    )
    seen: dict[str, object] = {}

    def send(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["Authorization"]
        seen["idempotency"] = request.headers["Idempotency-Key"]
        seen["user_agent"] = request.headers["User-Agent"]
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "resend-message-1"})

    settings = get_settings().model_copy(
        update={
            "email_mode": "resend",
            "resend_api_key": "test-key",
            "mail_from": "alerts@manzil.example",
            "mail_from_name": "Manzil",
            "frontend_url": "https://app.manzil.example",
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(send)) as client:
        assert await process_next_delivery(db_pool, settings, client=client)

    payload = seen["payload"]
    assert seen["authorization"] == "Bearer test-key"
    assert seen["idempotency"] == f"manzil/{delivery['id']}"
    assert seen["user_agent"] == "Manzil/1.0"
    assert payload["to"] == ["delivery@example.com"]
    token = response.json()["link"].rsplit("/", 1)[-1]
    assert f"https://app.manzil.example/invite/{token}" in payload["html"]
    assert "auth/v1" not in payload["html"]
    assert (
        await db_pool.fetchval(
            "select status from private.notification_deliveries where id=$1", delivery["id"]
        )
        == "sent"
    )


@pytest.mark.asyncio
async def test_resend_webhook_is_idempotent_and_does_not_regress_delivery(
    collab_hunt, seeded_users, db_pool
) -> None:
    event_id = uuid4()
    delivery_id = uuid4()
    await db_pool.execute(
        """insert into private.notification_events
             (id,event_type,hunt_id,source_kind,source_id,dedupe_key,context)
           values($1,'run_failed',$2,'job',$3,$4,'{}')""",
        event_id,
        UUID(collab_hunt["hunt_id"]),
        uuid4(),
        f"webhook-test:{event_id}",
    )
    await db_pool.execute(
        """insert into private.notification_deliveries
             (id,event_id,recipient_user_id,recipient_email,status,provider_message_id)
           values($1,$2,$3,$4,'sent','resend-webhook-1')""",
        delivery_id,
        event_id,
        UUID(seeded_users["owner"].user_id),
        seeded_users["owner"].email,
    )
    now = datetime.now(UTC)
    delivered_webhook_id = f"msg-delivered-{event_id}"
    await apply_resend_webhook(
        db_pool,
        svix_id=delivered_webhook_id,
        event_type="email.delivered",
        provider_at=now,
        provider_message_id="resend-webhook-1",
    )
    await apply_resend_webhook(
        db_pool,
        svix_id=f"msg-delayed-late-{event_id}",
        event_type="email.delivery_delayed",
        provider_at=now - timedelta(seconds=2),
        provider_message_id="resend-webhook-1",
    )
    await apply_resend_webhook(
        db_pool,
        svix_id=f"msg-failed-late-{event_id}",
        event_type="email.failed",
        provider_at=now - timedelta(seconds=1),
        provider_message_id="resend-webhook-1",
    )
    await apply_resend_webhook(
        db_pool,
        svix_id=delivered_webhook_id,
        event_type="email.delivered",
        provider_at=now,
        provider_message_id="resend-webhook-1",
    )

    assert (
        await db_pool.fetchval(
            "select status from private.notification_deliveries where id=$1", delivery_id
        )
        == "delivered"
    )
    assert (
        await db_pool.fetchval(
            "select count(*) from private.notification_webhook_events where svix_id=$1",
            delivered_webhook_id,
        )
        == 1
    )

    await apply_resend_webhook(
        db_pool,
        svix_id=f"msg-complained-{event_id}",
        event_type="email.complained",
        provider_at=now + timedelta(seconds=1),
        provider_message_id="resend-webhook-1",
    )
    final = await db_pool.fetchrow(
        "select status,provider_status_at from private.notification_deliveries where id=$1",
        delivery_id,
    )
    assert final["status"] == "complained"
    assert final["provider_status_at"] == now + timedelta(seconds=1)


@pytest.mark.asyncio
async def test_dispatcher_cancels_checkpoint_after_answer_or_opt_out(
    collab_hunt, seeded_users, db_pool
) -> None:
    member_id = UUID(seeded_users["member"].user_id)
    hunt_id = UUID(collab_hunt["hunt_id"])
    listing_id = UUID(collab_hunt["member_listing_id"])

    async def queue_checkpoint() -> UUID:
        job_id = await db_pool.fetchval(
            """insert into jobs(hunt_id,hunt_listing_id,type,state)
               values($1,$2,'ingest','waiting_user') returning id""",
            hunt_id,
            listing_id,
        )
        event_id = await db_pool.fetchval(
            """insert into job_events(job_id,stage,event,detail)
               values($1,'VERIFY','checkpoint_asked','{}') returning id""",
            job_id,
        )
        return await db_pool.fetchval(
            """select d.id from private.notification_events e
                 join private.notification_deliveries d on d.event_id=e.id
                where e.source_id=$1""",
            event_id,
        )

    first = await queue_checkpoint()
    await db_pool.execute(
        """update jobs set state='running' where id=(
             select (e.context->>'job_id')::uuid from private.notification_events e
             join private.notification_deliveries d on d.event_id=e.id where d.id=$1
           )""",
        first,
    )
    settings = get_settings().model_copy(update={"email_mode": "resend"})
    transport = httpx.MockTransport(
        lambda _request: pytest.fail("an ineligible notification reached Resend")
    )
    async with httpx.AsyncClient(transport=transport) as client:
        assert await process_next_delivery(db_pool, settings, client=client)
    assert (
        await db_pool.fetchval(
            "select status from private.notification_deliveries where id=$1", first
        )
        == "cancelled"
    )

    second = await queue_checkpoint()
    await db_pool.execute(
        """insert into user_notification_prefs(user_id,event_type,channel,enabled)
           values($1,'checkpoint_waiting','email',false)
           on conflict(user_id,event_type,channel) do update set enabled=false""",
        member_id,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        assert await process_next_delivery(db_pool, settings, client=client)
    assert (
        await db_pool.fetchval(
            "select status from private.notification_deliveries where id=$1", second
        )
        == "cancelled"
    )


@pytest.mark.asyncio
async def test_dispatcher_retries_concurrent_idempotent_request(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    created = await as_owner.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/invites",
        json={"email": "retry@example.com", "role": "member"},
    )
    delivery_id = await db_pool.fetchval(
        """select d.id from private.notification_events e
             join private.notification_deliveries d on d.event_id=e.id
            where e.source_id=$1""",
        UUID(created.json()["id"]),
    )
    settings = get_settings().model_copy(
        update={
            "email_mode": "resend",
            "resend_api_key": "test-key",
            "mail_from": "alerts@manzil.example",
        }
    )
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            409,
            json={
                "name": "concurrent_idempotent_requests",
                "message": "Original request is in progress",
            },
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        assert await process_next_delivery(db_pool, settings, client=client)
    delivery = await db_pool.fetchrow(
        """select status,attempts,next_attempt_at,last_error
             from private.notification_deliveries where id=$1""",
        delivery_id,
    )
    assert delivery["status"] == "queued"
    assert delivery["attempts"] == 1
    assert delivery["next_attempt_at"] > datetime.now(UTC)
    assert "concurrent_idempotent_requests" in delivery["last_error"]


@pytest.mark.asyncio
async def test_two_dispatchers_claim_one_delivery_once(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    await as_owner.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/invites",
        json={"email": "single-claim@example.com", "role": "member"},
    )
    sends = 0

    async def send(_request: httpx.Request) -> httpx.Response:
        nonlocal sends
        sends += 1
        await asyncio.sleep(0)
        return httpx.Response(200, json={"id": f"single-claim-{uuid4()}"})

    settings = get_settings().model_copy(
        update={
            "email_mode": "resend",
            "resend_api_key": "test-key",
            "mail_from": "alerts@manzil.example",
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(send)) as client:
        results = await asyncio.gather(
            process_next_delivery(db_pool, settings, client=client, worker_id="dispatcher-a"),
            process_next_delivery(db_pool, settings, client=client, worker_id="dispatcher-b"),
        )
    assert sorted(results) == [False, True]
    assert sends == 1


@pytest.mark.asyncio
async def test_dispatcher_replays_webhook_that_preceded_send_response(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    created = await as_owner.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/invites",
        json={"email": "early-webhook@example.com", "role": "member"},
    )
    provider_at = datetime.now(UTC)
    provider_id = f"early-{uuid4()}"
    await apply_resend_webhook(
        db_pool,
        svix_id=f"early-webhook-{uuid4()}",
        event_type="email.delivered",
        provider_at=provider_at,
        provider_message_id=provider_id,
    )
    settings = get_settings().model_copy(
        update={
            "email_mode": "resend",
            "resend_api_key": "test-key",
            "mail_from": "alerts@manzil.example",
        }
    )
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"id": provider_id}))
    async with httpx.AsyncClient(transport=transport) as client:
        assert await process_next_delivery(db_pool, settings, client=client)
    status = await db_pool.fetchval(
        """select d.status from private.notification_events e
             join private.notification_deliveries d on d.event_id=e.id
            where e.source_id=$1""",
        UUID(created.json()["id"]),
    )
    assert status == "delivered"


@pytest.mark.asyncio
async def test_revoke_race_preserves_cancelled_delivery(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    created = await as_owner.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/invites",
        json={"email": "revoke-race@example.com", "role": "member"},
    )
    delivery_id = await db_pool.fetchval(
        """select d.id from private.notification_events e
             join private.notification_deliveries d on d.event_id=e.id
            where e.source_id=$1""",
        UUID(created.json()["id"]),
    )
    provider_id = f"cancelled-{uuid4()}"

    async def accept_after_cancel(_request: httpx.Request) -> httpx.Response:
        await db_pool.execute(
            "update private.notification_deliveries set status='cancelled' where id=$1",
            delivery_id,
        )
        return httpx.Response(200, json={"id": provider_id})

    settings = get_settings().model_copy(
        update={
            "email_mode": "resend",
            "resend_api_key": "test-key",
            "mail_from": "alerts@manzil.example",
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(accept_after_cancel)) as client:
        assert await process_next_delivery(db_pool, settings, client=client)
    await apply_resend_webhook(
        db_pool,
        svix_id=f"cancelled-webhook-{uuid4()}",
        event_type="email.delivered",
        provider_at=datetime.now(UTC),
        provider_message_id=provider_id,
    )
    delivery = await db_pool.fetchrow(
        """select status,provider_message_id from private.notification_deliveries
            where id=$1""",
        delivery_id,
    )
    assert delivery["status"] == "cancelled"
    assert delivery["provider_message_id"] == provider_id


@pytest.mark.asyncio
async def test_malformed_event_is_failed_instead_of_poisoning_dispatcher(
    collab_hunt, seeded_users, db_pool
) -> None:
    job_id = await db_pool.fetchval(
        """insert into jobs(hunt_id,hunt_listing_id,type,state)
           values($1,$2,'ingest','failed') returning id""",
        UUID(collab_hunt["hunt_id"]),
        UUID(collab_hunt["owner_listing_id"]),
    )
    event_id = uuid4()
    delivery_id = uuid4()
    await db_pool.execute(
        """insert into private.notification_events
             (id,event_type,hunt_id,source_kind,source_id,dedupe_key,context)
           values($1,'run_failed',$2,'job',$3,$4,'{}')""",
        event_id,
        UUID(collab_hunt["hunt_id"]),
        job_id,
        f"malformed:{event_id}",
    )
    await db_pool.execute(
        """insert into private.notification_deliveries
             (id,event_id,recipient_user_id,recipient_email)
           values($1,$2,$3,$4)""",
        delivery_id,
        event_id,
        UUID(seeded_users["owner"].user_id),
        seeded_users["owner"].email,
    )
    settings = get_settings().model_copy(update={"email_mode": "resend"})
    transport = httpx.MockTransport(
        lambda _request: pytest.fail("a malformed notification reached Resend")
    )
    async with httpx.AsyncClient(transport=transport) as client:
        assert await process_next_delivery(db_pool, settings, client=client)
    delivery = await db_pool.fetchrow(
        "select status,last_error from private.notification_deliveries where id=$1",
        delivery_id,
    )
    assert delivery["status"] == "failed"
    assert delivery["last_error"] == "Email preparation failed: KeyError"


@pytest.mark.asyncio
async def test_current_rating_remains_send_eligible(collab_hunt, seeded_users, db_pool) -> None:
    owner_id = UUID(seeded_users["owner"].user_id)
    member_id = UUID(seeded_users["member"].user_id)
    listing_id = UUID(collab_hunt["member_listing_id"])
    unit_group_key = await db_pool.fetchval(
        """select private.unit_group_key(fp.beds,fp.baths)
             from hunt_listings hl join floor_plans fp on fp.property_id=hl.property_id
            where hl.id=$1 limit 1""",
        listing_id,
    )
    await db_pool.execute(
        """insert into user_notification_prefs(user_id,event_type,channel,enabled)
           values($1,'rating_changed','email',true)""",
        owner_id,
    )
    await db_pool.execute(
        """insert into ratings(hunt_listing_id,unit_group_key,user_id,rating)
           values($1,$2,$3,4.5)""",
        listing_id,
        unit_group_key,
        member_id,
    )
    settings = get_settings().model_copy(
        update={
            "email_mode": "resend",
            "resend_api_key": "test-key",
            "mail_from": "alerts@manzil.example",
        }
    )
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"id": f"rating-{uuid4()}"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        assert await process_next_delivery(db_pool, settings, client=client)
    assert (
        await db_pool.fetchval(
            """select d.status from private.notification_events e
             join private.notification_deliveries d on d.event_id=e.id
            where e.event_type='rating_changed' and e.actor_user_id=$1""",
            member_id,
        )
        == "sent"
    )


@pytest.mark.asyncio
async def test_resend_webhook_rejects_bad_signature(app, as_owner: AsyncClient) -> None:
    # Svix secrets are the `whsec_` prefix plus base64 key material.
    secret = "whsec_dGVzdC1ub3RpZmljYXRpb24tc2VjcmV0"
    settings = get_settings().model_copy(update={"resend_webhook_secret": secret})
    app.dependency_overrides[get_settings] = lambda: settings
    payload = json.dumps(
        {
            "type": "email.sent",
            "created_at": datetime.now(UTC).isoformat(),
            "data": {"email_id": "provider-id"},
        }
    )
    timestamp = datetime.now(UTC)
    headers = {
        "svix-id": "message-id",
        "svix-timestamp": str(int(timestamp.timestamp())),
        "svix-signature": "v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    }

    response = await as_owner.post("/v1/webhooks/resend", content=payload, headers=headers)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_resend_webhook_accepts_valid_raw_signature(
    app, as_owner: AsyncClient, collab_hunt, seeded_users, db_pool
) -> None:
    secret = "whsec_dGVzdC1ub3RpZmljYXRpb24tc2VjcmV0"
    settings = get_settings().model_copy(update={"resend_webhook_secret": secret})
    app.dependency_overrides[get_settings] = lambda: settings
    event_id = uuid4()
    provider_id = f"valid-signature-{uuid4()}"
    await db_pool.execute(
        """insert into private.notification_events
             (id,event_type,hunt_id,source_kind,source_id,dedupe_key,context)
           values($1,'run_failed',$2,'job',$3,$4,'{}')""",
        event_id,
        UUID(collab_hunt["hunt_id"]),
        uuid4(),
        f"valid-signature:{event_id}",
    )
    await db_pool.execute(
        """insert into private.notification_deliveries
             (event_id,recipient_user_id,recipient_email,status,provider_message_id)
           values($1,$2,$3,'sent',$4)""",
        event_id,
        UUID(seeded_users["owner"].user_id),
        seeded_users["owner"].email,
        provider_id,
    )
    timestamp = datetime.now(UTC)
    message_id = f"signed-{uuid4()}"
    payload = json.dumps(
        {
            "type": "email.delivered",
            "created_at": timestamp.isoformat(),
            "data": {"email_id": provider_id},
        },
        separators=(",", ":"),
    )
    signature = Webhook(secret).sign(message_id, timestamp, payload)
    response = await as_owner.post(
        "/v1/webhooks/resend",
        content=payload,
        headers={
            "svix-id": message_id,
            "svix-timestamp": str(int(timestamp.timestamp())),
            "svix-signature": signature,
        },
    )
    assert response.status_code == 204
    assert (
        await db_pool.fetchval(
            "select status from private.notification_deliveries where provider_message_id=$1",
            provider_id,
        )
        == "delivered"
    )
