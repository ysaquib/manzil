from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import asyncpg
import httpx
from jinja2 import TemplateError

from manzil_api.config import Settings
from manzil_api.email.render import render_email

logger = logging.getLogger("manzil_api.email")
RESEND_URL = "https://api.resend.com/emails"
RETRY_SECONDS = (60, 300, 900, 3600, 10800, 21600, 43200)
PROVIDER_STATUS_BY_EVENT = {
    "email.sent": "sent",
    "email.delivered": "delivered",
    "email.delivery_delayed": "delayed",
    "email.failed": "failed",
    "email.bounced": "bounced",
    "email.suppressed": "suppressed",
    "email.complained": "complained",
}


async def _claim(pool: asyncpg.Pool, worker_id: str) -> asyncpg.Record | None:
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            select d.*, e.event_type, e.hunt_id, e.actor_user_id,
                   e.source_kind, e.source_id, e.context
              from private.notification_deliveries d
              join private.notification_events e on e.id = d.event_id
             where (
                    d.status = 'queued' and d.next_attempt_at <= now()
                   ) or (
                    d.status = 'sending' and d.locked_at < now() - interval '5 minutes'
                   )
             order by d.next_attempt_at, d.created_at
             for update of d skip locked limit 1
            """
        )
        if row is None:
            return None
        await conn.execute(
            """update private.notification_deliveries
                  set status = 'sending', attempts = attempts + 1,
                      locked_by = $2, locked_at = now(), updated_at = now()
                where id = $1""",
            row["id"],
            worker_id,
        )
        return row


async def _cancel(pool: asyncpg.Pool, delivery_id: UUID, reason: str) -> None:
    await pool.execute(
        """update private.notification_deliveries
              set status = 'cancelled', last_error = $2, locked_by = null,
                  locked_at = null, updated_at = now()
            where id = $1""",
        delivery_id,
        reason[:500],
    )


async def _context(
    pool: asyncpg.Pool, settings: Settings, row: asyncpg.Record
) -> dict[str, Any] | None:
    raw_context = row["context"] or {}
    context = json.loads(raw_context) if isinstance(raw_context, str) else dict(raw_context)
    base = settings.frontend_url.rstrip("/")
    if row["event_type"] == "hunt_invited":
        invite = await pool.fetchrow(
            """select token, expires_at, accepted_by from invites
                where id = $1 and expires_at > now()""",
            row["source_id"],
        )
        if invite is None or invite["accepted_by"] is not None:
            return None
        context["cta_url"] = f"{base}/invite/{invite['token']}"
        expires_at = invite["expires_at"]
        context["expires_at_display"] = expires_at.astimezone(UTC).strftime("%B %-d, %Y")
        return context

    recipient_user_id = row["recipient_user_id"]
    if recipient_user_id is None or row["hunt_id"] is None:
        return None
    still_member = await pool.fetchval(
        "select exists(select 1 from hunt_members where hunt_id = $1 and user_id = $2)",
        row["hunt_id"],
        recipient_user_id,
    )
    if not still_member:
        return None

    hunt_id = row["hunt_id"]
    event_type = row["event_type"]
    # Consent and source state are evaluated again immediately before send.
    # Enqueue-time fan-out is durable, but a member may opt out, leave, answer a
    # Checkpoint, or delete the source while a delivery is waiting to retry.
    enabled = await pool.fetchval(
        "select private.notification_enabled($1,$2,$3)",
        recipient_user_id,
        hunt_id,
        event_type,
    )
    if not enabled:
        return None

    if event_type == "checkpoint_waiting":
        source_exists = await pool.fetchval(
            "select exists(select 1 from jobs where id = $1 and state = 'waiting_user')",
            UUID(str(context["job_id"])),
        )
    elif event_type == "run_failed":
        source_exists = await pool.fetchval(
            "select exists(select 1 from jobs where id = $1 and state = 'failed')",
            row["source_id"],
        )
    elif event_type == "listing_score_changed":
        source_exists = await pool.fetchval(
            "select exists(select 1 from hunt_listings where id = $1 and status = 'active')",
            UUID(str(context["listing_id"])),
        )
    elif event_type == "comment_added":
        source_exists = await pool.fetchval(
            "select exists(select 1 from comments where id = $1 and deleted_at is null)",
            row["source_id"],
        )
    elif event_type == "rating_changed":
        source_exists = await pool.fetchval(
            """select exists(select 1 from ratings
                   where hunt_listing_id = $1 and unit_group_key = $2
                     and user_id = $3 and rating::text = $4)""",
            UUID(str(context["listing_id"])),
            str(context["unit_group_key"]),
            row["actor_user_id"],
            str(context["rating"]),
        )
    else:
        source_exists = False
    if not source_exists:
        return None

    if event_type == "checkpoint_waiting":
        path = f"/h/{hunt_id}/tasks"
    elif event_type == "run_failed":
        path = f"/h/{hunt_id}/tasks?tab=history"
    else:
        params = {"listing": str(context["listing_id"])}
        if context.get("unit_group_key"):
            params["group"] = str(context["unit_group_key"])
        path = f"/h/{hunt_id}?{urlencode(params)}"
    context["cta_url"] = base + path
    context["alerts_url"] = base + "/account/alerts"
    return context


async def _mark_retry_or_failed(
    pool: asyncpg.Pool, row: asyncpg.Record, error: str, *, retryable: bool
) -> None:
    attempt = int(row["attempts"]) + 1
    if retryable and attempt <= len(RETRY_SECONDS):
        delay = RETRY_SECONDS[attempt - 1]
        await pool.execute(
            """update private.notification_deliveries
                  set status = 'queued', next_attempt_at = now() + ($2 * interval '1 second'),
                      last_error = $3, locked_by = null, locked_at = null, updated_at = now()
                where id = $1 and status = 'sending'""",
            row["id"],
            delay,
            error[:500],
        )
        logger.warning(
            "notification_delivery_retry_scheduled",
            extra={"delivery_id": str(row["id"]), "event_type": row["event_type"]},
        )
    else:
        await pool.execute(
            """update private.notification_deliveries
                  set status = 'failed', last_error = $2, locked_by = null,
                      locked_at = null, updated_at = now()
                where id = $1 and status = 'sending'""",
            row["id"],
            error[:500],
        )
        logger.error(
            "notification_delivery_failed",
            extra={"delivery_id": str(row["id"]), "event_type": row["event_type"]},
        )


def _resend_error(response: httpx.Response) -> tuple[str | None, str]:
    try:
        body = response.json()
    except ValueError:
        return None, f"Resend returned HTTP {response.status_code}"
    if not isinstance(body, dict):
        return None, f"Resend returned HTTP {response.status_code}"
    name = body.get("name")
    message = body.get("message")
    suffix = f" {name}" if isinstance(name, str) else ""
    if isinstance(message, str) and message:
        suffix += f": {message}"
    return name if isinstance(name, str) else None, f"Resend HTTP {response.status_code}{suffix}"


async def _apply_provider_event(
    conn: asyncpg.Connection,
    provider_message_id: str,
    event_type: str,
    provider_at: datetime,
) -> None:
    status = PROVIDER_STATUS_BY_EVENT.get(event_type)
    if status is None:
        return
    await conn.execute(
        """update private.notification_deliveries
              set status = $2,
                  provider_status_at = $3,
                  delivered_at = case when $2 = 'delivered' then $3 else delivered_at end,
                  updated_at = now()
            where provider_message_id = $1
              and (provider_status_at is null or $3 >= provider_status_at)
              and case
                    when status in (
                      'bounced','suppressed','complained','failed','disabled','cancelled'
                    ) then false
                    when status = 'delivered' then $2 = 'complained'
                    when status = 'delayed' then $2 <> 'sent'
                    else true
                  end""",
        provider_message_id,
        status,
        provider_at,
    )


async def _replay_early_provider_events(conn: asyncpg.Connection, provider_message_id: str) -> None:
    rows = await conn.fetch(
        """select event_type, provider_at
             from private.notification_webhook_events
            where provider_message_id = $1
            order by provider_at, received_at""",
        provider_message_id,
    )
    for event in rows:
        await _apply_provider_event(
            conn,
            provider_message_id,
            event["event_type"],
            event["provider_at"],
        )


async def process_next_delivery(
    pool: asyncpg.Pool,
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    worker_id: str | None = None,
) -> bool:
    worker_id = worker_id or f"{socket.gethostname()}:{id(pool)}"
    row = await _claim(pool, worker_id)
    if row is None:
        return False

    if settings.email_mode == "disabled":
        await pool.execute(
            """update private.notification_deliveries set status = 'disabled',
                      locked_by = null, locked_at = null, updated_at = now()
                where id = $1 and status = 'sending'""",
            row["id"],
        )
        return True

    try:
        context = await _context(pool, settings, row)
        if context is None:
            await _cancel(pool, row["id"], "Recipient, preference, or source is no longer eligible")
            return True
        rendered = render_email(row["event_type"], context)
    except (AttributeError, KeyError, TemplateError, TypeError, ValueError) as exc:
        await _mark_retry_or_failed(
            pool,
            row,
            f"Email preparation failed: {type(exc).__name__}",
            retryable=False,
        )
        return True
    payload = {
        "from": f"{settings.mail_from_name} <{settings.mail_from}>",
        "to": [row["recipient_email"]],
        "subject": rendered.subject,
        "html": rendered.html,
        "text": rendered.text,
    }
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        response = await client.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Idempotency-Key": f"manzil/{row['id']}",
                "User-Agent": "Manzil/1.0",
            },
            json=payload,
        )
        if response.is_success:
            message_id = response.json()["id"]
            async with pool.acquire() as conn, conn.transaction():
                # A revoke can cancel a delivery while the HTTP request is in
                # flight. Preserve that terminal state while still recording
                # the provider id for audit/webhook correlation.
                await conn.execute(
                    """update private.notification_deliveries
                          set status = case when status = 'sending' then 'sent' else status end,
                              provider_message_id = $2, sent_at = now(), last_error = null,
                              locked_by = null, locked_at = null, updated_at = now()
                        where id = $1""",
                    row["id"],
                    message_id,
                )
                # Resend explicitly permits webhooks to beat the POST response.
                # Those events were durably stored without a matching delivery;
                # replay them now that the provider id is known.
                await _replay_early_provider_events(conn, message_id)
            logger.info(
                "notification_delivery_accepted",
                extra={"delivery_id": str(row["id"]), "event_type": row["event_type"]},
            )
        else:
            error_name, error = _resend_error(response)
            await _mark_retry_or_failed(
                pool,
                row,
                error,
                retryable=(
                    response.status_code >= 500
                    or error_name == "concurrent_idempotent_requests"
                    or (response.status_code == 429 and error_name in (None, "rate_limit_exceeded"))
                ),
            )
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        await _mark_retry_or_failed(
            pool,
            row,
            f"Resend request failed: {type(exc).__name__}",
            retryable=True,
        )
    finally:
        if owns_client:
            await client.aclose()
    return True


async def run_email_dispatcher(pool: asyncpg.Pool, settings: Settings, stop: asyncio.Event) -> None:
    worker_id = f"{socket.gethostname()}:{id(stop)}"
    async with httpx.AsyncClient(timeout=15) as client:
        while not stop.is_set():
            try:
                worked = await process_next_delivery(
                    pool, settings, client=client, worker_id=worker_id
                )
            except Exception:
                logger.exception("notification_dispatch_failed")
                worked = False
            if not worked:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=1)


async def apply_resend_webhook(
    pool: asyncpg.Pool,
    *,
    svix_id: str,
    event_type: str,
    provider_at: datetime,
    provider_message_id: str | None,
) -> None:
    async with pool.acquire() as conn, conn.transaction():
        inserted = await conn.fetchval(
            """insert into private.notification_webhook_events
                   (svix_id, provider_message_id, event_type, provider_at)
                 values ($1, $2, $3, $4) on conflict do nothing returning svix_id""",
            svix_id,
            provider_message_id,
            event_type,
            provider_at,
        )
        if inserted is None or provider_message_id is None:
            return
        await _apply_provider_event(conn, provider_message_id, event_type, provider_at)
