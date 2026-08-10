"""Site Admin Demo Hunt selection, publication, and kill switch."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Query, status
from manzil_worker.ops.demo_publication import build_demo_snapshot
from pydantic import BaseModel

from manzil_api.admin.dependencies import AdminUser, Audit
from manzil_api.demo.router import reset_config_cache
from manzil_api.dependencies import DbPool
from manzil_api.exceptions import ManzilAPIError

router = APIRouter(prefix="/admin/demo", tags=["admin"])
logger = logging.getLogger("manzil_api")


class DemoConflict(ManzilAPIError):
    status_code = status.HTTP_409_CONFLICT
    code = "demo_conflict"


class DemoNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "demo_hunt_not_found"


class DemoToggle(BaseModel):
    enabled: bool


class DemoPreflightRequest(BaseModel):
    hunt_id: UUID


class DemoPublicationRequest(BaseModel):
    confirmation_id: UUID
    confirmation_text: str
    enable_on_success: bool = False


async def _ensure_virtual_principal(conn: asyncpg.Connection, actor: UUID) -> None:
    rows = await conn.fetch("select user_id from demo_accounts")
    if len(rows) > 1:
        raise DemoConflict("Demo configuration has more than one virtual principal")
    if not rows:
        await conn.execute(
            """
            insert into demo_accounts (user_id, created_by, note)
            values ($1, $2, 'Created by the admin-managed Demo publication flow')
            on conflict do nothing
            """,
            uuid4(),
            actor,
        )
        # Two Site Admins may preflight concurrently. The singleton index is the
        # arbiter; `on conflict do nothing` makes the loser reuse the winner
        # rather than surfacing a raw 500 from a harmless race.
        count = await conn.fetchval("select count(*) from demo_accounts")
        if count != 1:
            raise DemoConflict("Demo configuration could not establish one virtual principal")


async def _owned_hunt(conn: asyncpg.Connection, hunt_id: UUID, actor: UUID) -> asyncpg.Record:
    row = await conn.fetchrow(
        "select id, name, owner_id from hunts where id = $1 and owner_id = $2",
        hunt_id,
        actor,
    )
    if row is None:
        raise DemoNotFound("Choose a Hunt you own")
    return row


async def _human_inventory(conn: asyncpg.Connection, hunt_id: UUID) -> dict[str, int]:
    row = await conn.fetchrow(
        """
        with listing_ids as (
            select id from hunt_listings where hunt_id = $1
        ), visit_ids as (
            select id from visits where hunt_id = $1
        )
        select
          (select count(*) from hunt_members where hunt_id = $1) as members,
          (select count(*) from comments where hunt_listing_id in (select id from listing_ids)
                                      and deleted_at is null) as comments,
          (select count(*) from ratings
            where hunt_listing_id in (select id from listing_ids)) as ratings,
          (select count(*) from jobs where hunt_id = $1) as jobs,
          (select count(*) from visits where hunt_id = $1) as visits,
          (select count(*) from visit_defects where visit_id in (select id from visit_ids)
                                          and deleted_at is null) as defects,
          (select count(*) from visit_fee_proposals
            where hunt_listing_id in (select id from listing_ids)) as fee_proposals
        """,
        hunt_id,
    )
    return {key: int(value) for key, value in dict(row).items()}


@router.get("/hunts", summary="Demo Hunt candidates owned by this Site Admin")
async def demo_hunt_options(
    admin: AdminUser,
    pool: DbPool,
    q: str = Query("", max_length=200),
    limit: int = Query(50, ge=1, le=50),
) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        select h.id as hunt_id, h.name,
               count(hl.id) filter (where hl.status = 'active') as active_listings,
               count(hl.id) filter (where hl.status = 'archived') as archived_listings
          from hunts h
          left join hunt_listings hl on hl.hunt_id = h.id
         where h.owner_id = $1 and ($2 = '' or h.name ilike '%' || $2 || '%')
         group by h.id, h.name
         order by h.name
         limit $3
        """,
        UUID(admin.id),
        q.strip(),
        limit,
    )
    return [dict(row) for row in rows]


@router.post("/preflight", summary="Review a Hunt before publishing it publicly")
async def demo_preflight(
    body: DemoPreflightRequest,
    admin: AdminUser,
    pool: DbPool,
) -> dict[str, Any]:
    actor = UUID(admin.id)
    async with pool.acquire() as conn, conn.transaction():
        hunt = await _owned_hunt(conn, body.hunt_id, actor)
        await _ensure_virtual_principal(conn, actor)
        snapshot = await build_demo_snapshot(conn, body.hunt_id)
        security = list(await conn.fetchval("select private.demo_security_preflight()") or [])
        blockers = [*security, *snapshot.blockers]
        human = await _human_inventory(conn, body.hunt_id)
        warnings = list(snapshot.warnings)
        human_total = sum(value for key, value in human.items() if key != "members")
        if human_total:
            warnings.append(
                "This Hunt contains human-authored or collaboration history that Demo visitors "
                "can read. Review the counts before confirming."
            )
        inventory = {
            "hunt_id": str(body.hunt_id),
            "hunt_name": hunt["name"],
            "active_listings": snapshot.active_count,
            "archived_listings": snapshot.archived_count,
            "replay_ready": len(snapshot.captures),
            "mapped_properties": len(snapshot.places),
            "human_content": human,
            "blockers": blockers,
            "warnings": warnings,
        }
        confirmation_id = await conn.fetchval(
            """
            insert into private.demo_publish_confirmations
                (actor_id, hunt_id, source_fingerprint, inventory)
            values ($1, $2, $3, $4::jsonb)
            returning id
            """,
            actor,
            body.hunt_id,
            snapshot.fingerprint,
            json.dumps(inventory),
        )
    return {
        **inventory,
        "confirmation_id": str(confirmation_id),
        "source_fingerprint": snapshot.fingerprint,
        "expires_in": 600,
    }


@router.post(
    "/publications",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue an atomic Demo release publication",
)
async def create_demo_publication(
    body: DemoPublicationRequest,
    admin: AdminUser,
    pool: DbPool,
    audit: Audit,
) -> dict[str, Any]:
    actor = UUID(admin.id)
    async with pool.acquire() as conn, conn.transaction():
        confirmation = await conn.fetchrow(
            """
            select * from private.demo_publish_confirmations
             where id = $1 for update
            """,
            body.confirmation_id,
        )
        if (
            confirmation is None
            or confirmation["actor_id"] != actor
            or confirmation["consumed_at"] is not None
            or confirmation["expires_at"] <= datetime.now().astimezone()
        ):
            raise DemoConflict("That publication review expired; review the Hunt again")
        hunt = await _owned_hunt(conn, confirmation["hunt_id"], actor)
        if body.confirmation_text != hunt["name"]:
            raise DemoConflict("Type the Hunt name exactly to confirm public exposure")
        snapshot = await build_demo_snapshot(conn, confirmation["hunt_id"])
        if snapshot.fingerprint != confirmation["source_fingerprint"]:
            raise DemoConflict("The Hunt changed after review; review it again before publishing")
        security = list(await conn.fetchval("select private.demo_security_preflight()") or [])
        blockers = [*security, *snapshot.blockers]
        if blockers:
            raise DemoConflict("; ".join(blockers))
        config = await conn.fetchrow(
            "select demo_generation, demo_hunt_id from site_settings for update"
        )
        if body.enable_on_success and config["demo_hunt_id"] is not None:
            raise DemoConflict(
                "Publish updates without enabling; a retained Demo Hunt must be enabled explicitly"
            )
        try:
            publication_id = await conn.fetchval(
                """
                insert into private.demo_publications
                    (hunt_id, requested_by, enable_on_success, expected_generation,
                     source_fingerprint, replay_count, mapped_count, warnings)
                values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                returning id
                """,
                confirmation["hunt_id"],
                actor,
                body.enable_on_success,
                config["demo_generation"],
                snapshot.fingerprint,
                len(snapshot.captures),
                len(snapshot.places),
                json.dumps(snapshot.warnings),
            )
        except asyncpg.UniqueViolationError as error:
            raise DemoConflict("Another Demo publication is already in progress") from error
        await conn.execute(
            "update private.demo_publish_confirmations set consumed_at = now() where id = $1",
            body.confirmation_id,
        )
        await audit.record(
            "demo.publish.requested",
            target_type="demo_publication",
            target_id=publication_id,
            target_label=hunt["name"],
            hunt_id=confirmation["hunt_id"],
            after={"enable_on_success": body.enable_on_success},
            conn=conn,
        )
    return {"publication_id": str(publication_id), "state": "queued"}


@router.get("", summary="Demo Mode status and publication freshness")
async def demo_status(admin: AdminUser, pool: DbPool) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        select s.demo_enabled, s.demo_hunt_id, s.demo_release_id, s.demo_generation,
               s.updated_at, h.name as hunt_name, h.owner_id,
               p.state as release_state, p.source_fingerprint, p.published_at,
               p.replay_count, p.mapped_count, p.warnings, p.error,
               (select count(*) from hunt_listings hl
                 where hl.hunt_id = s.demo_hunt_id and hl.status = 'active') as active_count
          from site_settings s
          left join hunts h on h.id = s.demo_hunt_id
          left join private.demo_publications p on p.id = s.demo_release_id
        """
    )
    inflight = await pool.fetchrow(
        """
        select id, hunt_id, state, attempts, error, created_at, started_at
          from private.demo_publications
         where state in ('queued', 'building')
         order by created_at desc limit 1
        """
    )
    latest_failed = None
    if inflight is None:
        latest_failed = await pool.fetchrow(
            """
            select id, hunt_id, state, attempts, error, created_at, started_at
              from private.demo_publications
             where state in ('failed', 'superseded')
             order by created_at desc limit 1
            """
        )
    stale = False
    freshness_error = None
    # The UI polls every two seconds while a publication is in flight. Rebuilding
    # and hashing up to 50 full Replay Captures on every poll would compete with
    # the worker doing that exact work. The completed poll computes freshness
    # once; while building, the operator already has the stronger state signal.
    if inflight is None and row["demo_hunt_id"] and row["source_fingerprint"]:
        try:
            async with pool.acquire() as conn:
                snapshot = await build_demo_snapshot(conn, row["demo_hunt_id"])
            stale = snapshot.fingerprint != row["source_fingerprint"]
        except Exception as error:  # status remains useful when one replay is malformed
            stale = True
            freshness_error = str(error)
    blockers = list(await pool.fetchval("select private.demo_preflight()") or [])
    available = bool(await pool.fetchval("select demo_available()"))
    publication = inflight or latest_failed
    return {
        "enabled": bool(row["demo_enabled"]),
        "available": available,
        "hunt_id": str(row["demo_hunt_id"]) if row["demo_hunt_id"] else None,
        "hunt_name": row["hunt_name"],
        "owned_by_caller": row["owner_id"] == UUID(admin.id) if row["owner_id"] else False,
        "release_id": str(row["demo_release_id"]) if row["demo_release_id"] else None,
        "release_state": row["release_state"],
        "published_at": row["published_at"],
        "replay_count": row["replay_count"] or 0,
        "active_count": row["active_count"] or 0,
        "mapped_count": row["mapped_count"] or 0,
        "warnings": json.loads(row["warnings"])
        if isinstance(row["warnings"], str)
        else list(row["warnings"] or []),
        "blockers": blockers,
        "stale": stale,
        "freshness_error": freshness_error,
        "updated_at": row["updated_at"],
        "publication": dict(publication) if publication else None,
    }


@router.patch("", summary="Enable or immediately disable public Demo Mode")
async def set_demo(
    body: DemoToggle,
    admin: AdminUser,
    pool: DbPool,
    audit: Audit,
) -> dict[str, Any]:
    actor = UUID(admin.id)
    previous = await pool.fetchval("select demo_enabled from site_settings")
    if body.enabled:
        async with pool.acquire() as conn, conn.transaction():
            owner = await conn.fetchval(
                """
                select h.owner_id from site_settings s join hunts h on h.id = s.demo_hunt_id
                """
            )
            if owner != actor:
                raise DemoConflict("Only the selected Demo Hunt's owner may enable it")
            config = await conn.fetchrow(
                """
                select s.demo_hunt_id, p.source_fingerprint
                  from site_settings s
                 join private.demo_publications p
                    on p.id = s.demo_release_id and p.hunt_id = s.demo_hunt_id
                 where p.state = 'ready' and p.requested_by = $1
                """,
                actor,
            )
            if config is None:
                raise DemoConflict("Publish a Demo Hunt before enabling Demo Mode")
            snapshot = await build_demo_snapshot(conn, config["demo_hunt_id"])
            if snapshot.fingerprint != config["source_fingerprint"]:
                raise DemoConflict("Publish the Hunt's pending replay/map updates before enabling")
            try:
                await conn.fetchval("select set_demo_enabled($1, $2)", True, actor)
            except asyncpg.InsufficientPrivilegeError as error:
                raise DemoConflict(error.detail or str(error)) from error
            await audit.record(
                "demo.toggle",
                target_type="site_settings",
                before={"demo_enabled": previous},
                after={"demo_enabled": True},
                conn=conn,
            )
    else:
        await pool.fetchval("select set_demo_enabled($1, $2)", False, actor)
        try:
            await audit.record(
                "demo.toggle",
                target_type="site_settings",
                before={"demo_enabled": previous},
                after={"demo_enabled": False},
            )
        except Exception:
            logger.error(
                "Demo mode was disabled but the audit entry failed; the shutoff stands",
                exc_info=True,
            )
    reset_config_cache()
    return {"enabled": body.enabled}


__all__ = ["router"]
