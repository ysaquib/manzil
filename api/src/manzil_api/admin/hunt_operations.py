"""Audited Site Admin mutations performed from a Hunt's Ghost View.

These routes deliberately mirror the ordinary Hunt URLs behind an
``/admin/ghost`` prefix.  They use the service client only after proving that
the caller is both a Site Admin and *not* a member of the target Hunt.  An
admin who joins a Hunt therefore keeps their real Hunt role and cannot use
Ghost View to elevate it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, status
from manzil_shared.models import CheckpointPrompt, JobState

from manzil_api import privileged
from manzil_api.admin.dependencies import AdminUser, Audit
from manzil_api.collaboration.exceptions import TransferTargetNotMember
from manzil_api.collaboration.schemas import (
    MemberPatch,
    MemberResponse,
    TransferOwnershipRequest,
    TransferOwnershipResponse,
)
from manzil_api.database import create_service_client
from manzil_api.dependencies import DbPool, SettingsDep
from manzil_api.exceptions import ManzilAPIError
from manzil_api.fees import service as fee_service
from manzil_api.fees.schemas import FeeEntryResponse, FeeEntryUpsert
from manzil_api.hunts import service as hunt_service
from manzil_api.hunts.schemas import (
    HuntResponse,
    HuntSettingsPatch,
    HuntUpdate,
    SharedFiltersPut,
    SharedFiltersResponse,
)
from manzil_api.invitation_links import service as invitation_link_service
from manzil_api.invitation_links.schemas import (
    InvitationLinkCreate,
    InvitationLinkPatch,
    InvitationLinkResponse,
)
from manzil_api.invites import service as invite_service
from manzil_api.invites.schemas import InviteCreate, InviteResponse
from manzil_api.jobs import service as job_service
from manzil_api.jobs.dependencies import parse_job_states
from manzil_api.jobs.exceptions import InvalidCheckpointAnswer
from manzil_api.jobs.schemas import CheckpointAnswer, JobResponse
from manzil_api.listings import service as listing_service
from manzil_api.listings.schemas import (
    ListingCreate,
    ListingDeletionImpact,
    ListingPermanentDelete,
    ListingResponse,
    ListingStatusPatch,
    PinsPatch,
    RefreshRequest,
    SourcePolicyPatch,
    UnitGroupStatePatch,
    UnitGroupStateResponse,
)
from manzil_api.overrides import service as override_service
from manzil_api.overrides.schemas import OverrideCreate, OverrideResponse
from manzil_api.rubric import service as rubric_service
from manzil_api.rubric.schemas import (
    CustomRoutingRequest,
    CustomRoutingResponse,
    RubricCriterionOut,
    RubricPut,
)
from manzil_api.utilities import service as utility_service
from manzil_api.utilities.schemas import (
    UtilityName,
    UtilityOverrideResponse,
    UtilityOverrideUpsert,
)
from supabase import Client

router = APIRouter(prefix="/admin/ghost", tags=["admin", "ghost-view"])


class GhostViewUnavailable(ManzilAPIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "ghost_view_unavailable"


class GhostTargetNotFound(ManzilAPIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "ghost_target_not_found"


def get_service_client(settings: SettingsDep) -> Client:
    return create_service_client(settings)


ServiceClient = Annotated[Client, Depends(get_service_client)]


async def _require_ghost_hunt(pool: DbPool, hunt_id: UUID, admin: AdminUser) -> dict:
    row = await pool.fetchrow("select * from hunts where id = $1", hunt_id)
    if row is None:
        raise GhostTargetNotFound("Hunt not found")
    member = await pool.fetchval(
        "select exists(select 1 from hunt_members where hunt_id = $1 and user_id = $2)",
        hunt_id,
        UUID(admin.id),
    )
    if member:
        raise GhostViewUnavailable(
            "Site Admins who belong to this Hunt must use their assigned Hunt role"
        )
    hunt = dict(row)
    if isinstance(hunt.get("settings"), str):
        hunt["settings"] = json.loads(hunt["settings"])
    return hunt


async def _require_ghost_listing(pool: DbPool, listing_id: UUID, admin: AdminUser) -> dict:
    row = await pool.fetchrow("select * from hunt_listings where id = $1", listing_id)
    if row is None:
        raise GhostTargetNotFound("Listing not found")
    await _require_ghost_hunt(pool, row["hunt_id"], admin)
    listing = dict(row)
    for key in ("id", "hunt_id", "property_id", "added_by", "submitted_source_id"):
        if listing.get(key) is not None:
            listing[key] = str(listing[key])
    return listing


async def _audit_hunt(
    audit: Audit,
    action: str,
    hunt_id: UUID,
    *,
    target_type: str = "hunt",
    target_id: UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    await audit.record(
        action,
        target_type=target_type,
        target_id=target_id or hunt_id,
        hunt_id=hunt_id,
        before=before,
        after=after,
        via_ghost_view=True,
    )


@router.patch("/hunts/{hunt_id}", response_model=HuntResponse)
async def patch_hunt(
    hunt_id: UUID,
    body: HuntUpdate,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> HuntResponse:
    before = await _require_ghost_hunt(pool, hunt_id, admin)
    result = await hunt_service.patch_hunt(client, hunt_id, body)
    await _audit_hunt(
        audit,
        "hunt.update",
        hunt_id,
        before={
            "name": before["name"],
            "archived_at": before["archived_at"].isoformat() if before["archived_at"] else None,
        },
        after=result.model_dump(mode="json"),
    )
    return result


@router.patch("/hunts/{hunt_id}/settings", response_model=HuntResponse)
async def patch_hunt_settings(
    hunt_id: UUID,
    body: HuntSettingsPatch,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> HuntResponse:
    before = await _require_ghost_hunt(pool, hunt_id, admin)
    result = await hunt_service.patch_settings(client, hunt_id, body)
    await _audit_hunt(
        audit,
        "hunt.settings.update",
        hunt_id,
        before={"settings": before.get("settings")},
        after={"settings": result.settings},
    )
    return result


@router.put("/hunts/{hunt_id}/shared-filters", response_model=SharedFiltersResponse)
async def put_shared_filters(
    hunt_id: UUID,
    body: SharedFiltersPut,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> SharedFiltersResponse:
    await _require_ghost_hunt(pool, hunt_id, admin)
    result = await hunt_service.put_shared_filters(client, hunt_id, admin.id, body)
    await _audit_hunt(audit, "hunt.shared_filters.update", hunt_id, after={"filters": body.filters})
    return result


@router.put("/hunts/{hunt_id}/rubric", response_model=list[RubricCriterionOut])
async def put_rubric(
    hunt_id: UUID,
    body: RubricPut,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> list[RubricCriterionOut]:
    await _require_ghost_hunt(pool, hunt_id, admin)
    before = await rubric_service.get_rubric(client, hunt_id)
    result = await rubric_service.put_rubric(client, hunt_id, body)
    await _audit_hunt(
        audit,
        "hunt.rubric.update",
        hunt_id,
        target_type="rubric",
        before={"criteria": [row.model_dump(mode="json") for row in before]},
        after={"criteria": [row.model_dump(mode="json") for row in result]},
    )
    return result


@router.post("/hunts/{hunt_id}/rubric/custom-routing", response_model=CustomRoutingResponse)
async def classify_custom_routing(
    hunt_id: UUID,
    body: CustomRoutingRequest,
    admin: AdminUser,
    pool: DbPool,
) -> CustomRoutingResponse:
    await _require_ghost_hunt(pool, hunt_id, admin)
    return await rubric_service.classify_custom_routing(hunt_id, admin.id, body)


@router.post(
    "/hunts/{hunt_id}/listings",
    response_model=ListingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_listing(
    hunt_id: UUID,
    body: ListingCreate,
    admin: AdminUser,
    pool: DbPool,
    audit: Audit,
) -> ListingResponse:
    hunt = await _require_ghost_hunt(pool, hunt_id, admin)
    source_policy = body.source_policy or (hunt.get("settings") or {}).get(
        "default_source_policy", "tiers_1_2_3"
    )
    async with pool.acquire() as connection, connection.transaction():
        property_id = await connection.fetchval(
            "insert into properties(name, canonical_address) values($1, $1) returning id",
            listing_service._placeholder_name(body.url),
        )
        row = await connection.fetchrow(
            """
            insert into hunt_listings(hunt_id, property_id, added_by, source_policy)
            values($1, $2, $3, $4) returning *
            """,
            hunt_id,
            property_id,
            UUID(admin.id),
            source_policy,
        )
        await connection.execute(
            """
            insert into jobs(hunt_id, hunt_listing_id, type, state, payload)
            values($1, $2, 'ingest', 'queued', $3::jsonb)
            """,
            hunt_id,
            row["id"],
            json.dumps({"url": body.url, "source_policy": source_policy}),
        )
    listing_row = dict(row)
    if isinstance(listing_row.get("pins"), str):
        listing_row["pins"] = json.loads(listing_row["pins"])
    result = ListingResponse.model_validate(listing_row)
    await _audit_hunt(
        audit,
        "listing.create",
        hunt_id,
        target_type="listing",
        target_id=result.id,
        after={"url": body.url, "source_policy": source_policy},
    )
    return result


@router.patch("/listings/{listing_id}/status", response_model=ListingResponse)
async def patch_listing_status(
    listing_id: UUID,
    body: ListingStatusPatch,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> ListingResponse:
    listing = await _require_ghost_listing(pool, listing_id, admin)
    result = await listing_service.patch_status(
        client, listing, admin.id, body, authorized_admin=True
    )
    await _audit_hunt(
        audit,
        "listing.status.update",
        UUID(str(listing["hunt_id"])),
        target_type="listing",
        target_id=listing_id,
        before={"status": listing["status"]},
        after={"status": body.status},
    )
    return result


@router.get("/listings/{listing_id}/deletion-impact", response_model=ListingDeletionImpact)
async def listing_deletion_impact(
    listing_id: UUID,
    admin: AdminUser,
    pool: DbPool,
) -> ListingDeletionImpact:
    await _require_ghost_listing(pool, listing_id, admin)
    async with pool.acquire() as connection:
        return await listing_service.get_deletion_impact_admin(connection, listing_id)


@router.delete("/listings/{listing_id}", response_model=ListingDeletionImpact)
async def delete_listing_permanently(
    listing_id: UUID,
    body: ListingPermanentDelete,
    admin: AdminUser,
    pool: DbPool,
    audit: Audit,
) -> ListingDeletionImpact:
    listing = await _require_ghost_listing(pool, listing_id, admin)
    async with pool.acquire() as connection, connection.transaction():
        result = await listing_service.delete_listing_permanently_admin(
            connection, listing_id, UUID(admin.id), body.confirmation_name
        )
        await audit.record(
            "listing.permanent_delete",
            target_type="listing",
            target_id=listing_id,
            target_label=result.property_name,
            hunt_id=UUID(str(listing["hunt_id"])),
            before={"status": result.status, "counts": result.counts.model_dump()},
            after={"deleted": True},
            via_ghost_view=True,
            conn=connection,
        )
    return result


@router.patch("/listings/{listing_id}/pins", response_model=ListingResponse)
async def patch_listing_pins(
    listing_id: UUID,
    body: PinsPatch,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> ListingResponse:
    listing = await _require_ghost_listing(pool, listing_id, admin)
    result = await listing_service.patch_pins(
        client, listing, admin.id, body, authorized_admin=True
    )
    await _audit_hunt(
        audit,
        "listing.pins.update",
        UUID(str(listing["hunt_id"])),
        target_type="listing",
        target_id=listing_id,
        before={"pins": listing.get("pins") or {}},
        after={"pins": body.pins},
    )
    return result


@router.patch("/listings/{listing_id}/source-policy", response_model=ListingResponse)
async def patch_listing_source_policy(
    listing_id: UUID,
    body: SourcePolicyPatch,
    admin: AdminUser,
    pool: DbPool,
    audit: Audit,
) -> ListingResponse:
    listing = await _require_ghost_listing(pool, listing_id, admin)
    caps = {
        "trust_link": 0,
        "tier_1": 1,
        "tier_1_plus_official": 1,
        "tiers_1_2": 2,
        "tiers_1_2_3": 3,
    }
    relaxed = caps[body.source_policy] > caps[listing["source_policy"]]
    async with pool.acquire() as connection, connection.transaction():
        row = await connection.fetchrow(
            """
            update hunt_listings set source_policy=$2,
              single_source_reason=case when $2='trust_link' then 'trust_link'
                when $3 then null else single_source_reason end
            where id=$1 returning *
            """,
            listing_id,
            body.source_policy,
            relaxed,
        )
        if relaxed:
            url = await connection.fetchval(
                "select payload->>'url' from jobs where hunt_listing_id=$1 and type='ingest' "
                "and payload ? 'url' order by created_at limit 1",
                listing_id,
            )
            if not url:
                raise GhostTargetNotFound("Listing has no submitted Source URL")
            await connection.execute(
                """insert into jobs(hunt_id,hunt_listing_id,type,state,payload)
                values($1,$2,'refresh','queued',$3::jsonb)""",
                listing["hunt_id"],
                listing_id,
                json.dumps(
                    {
                        "hunt_id": str(listing["hunt_id"]),
                        "listing_id": str(listing_id),
                        "url": url,
                        "scope": "discover",
                        "source_policy": body.source_policy,
                    }
                ),
            )
    listing_row = dict(row)
    if isinstance(listing_row.get("pins"), str):
        listing_row["pins"] = json.loads(listing_row["pins"])
    result = ListingResponse.model_validate(listing_row)
    await _audit_hunt(
        audit,
        "listing.source_policy.update",
        UUID(str(listing["hunt_id"])),
        target_type="listing",
        target_id=listing_id,
        before={"source_policy": listing["source_policy"]},
        after={"source_policy": body.source_policy},
    )
    return result


@router.post("/listings/{listing_id}/refresh", response_model=JobResponse, status_code=202)
async def refresh_listing(
    listing_id: UUID,
    body: RefreshRequest,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> JobResponse:
    listing = await _require_ghost_listing(pool, listing_id, admin)
    result = await listing_service.enqueue_listing_refresh(
        client,
        listing=listing,
        user_id=admin.id,
        body=body,
        trigger="admin:ghost",
        authorized_hunt_refresh=True,
    )
    await _audit_hunt(
        audit,
        "listing.refresh",
        UUID(str(listing["hunt_id"])),
        target_type="listing",
        target_id=listing_id,
        after={"job_id": str(result.id), "fields": body.fields},
    )
    return result


@router.post("/hunts/{hunt_id}/refresh", response_model=list[JobResponse], status_code=202)
async def refresh_hunt(
    hunt_id: UUID,
    body: RefreshRequest,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> list[JobResponse]:
    await _require_ghost_hunt(pool, hunt_id, admin)
    result = await listing_service.enqueue_hunt_refresh(
        client, hunt_id=hunt_id, user_id=admin.id, body=body
    )
    await _audit_hunt(audit, "hunt.refresh", hunt_id, after={"jobs": [str(j.id) for j in result]})
    return result


@router.patch(
    "/listings/{listing_id}/unit-groups/{unit_group_key}/state",
    response_model=UnitGroupStateResponse,
)
async def patch_unit_group_state(
    listing_id: UUID,
    unit_group_key: str,
    body: UnitGroupStatePatch,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> UnitGroupStateResponse:
    listing = await _require_ghost_listing(pool, listing_id, admin)
    result = await listing_service.patch_unit_group_state(
        client, listing, unit_group_key, admin.id, body, authorized_admin=True
    )
    await _audit_hunt(
        audit,
        "listing.unit_group_state.update",
        UUID(str(listing["hunt_id"])),
        target_type="listing",
        target_id=listing_id,
        after={"unit_group_key": unit_group_key, **body.model_dump(mode="json")},
    )
    return result


@router.post("/listings/{listing_id}/overrides", response_model=OverrideResponse, status_code=201)
async def create_override(
    listing_id: UUID,
    body: OverrideCreate,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> OverrideResponse:
    listing = await _require_ghost_listing(pool, listing_id, admin)
    hunt_id = UUID(str(listing["hunt_id"]))
    result = await override_service.create_override(
        client,
        hunt_listing_id=listing_id,
        hunt_id=hunt_id,
        user_id=admin.id,
        body=body,
        authorized_admin=True,
    )
    await _audit_hunt(
        audit,
        "listing.override.create",
        hunt_id,
        target_type="listing",
        target_id=listing_id,
        after=body.model_dump(mode="json"),
    )
    return result


@router.put("/listings/{listing_id}/fees/{fee_slot}", response_model=FeeEntryResponse)
async def upsert_fee(
    listing_id: UUID,
    fee_slot: str,
    body: FeeEntryUpsert,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> FeeEntryResponse:
    listing = await _require_ghost_listing(pool, listing_id, admin)
    hunt_id = UUID(str(listing["hunt_id"]))
    result = await fee_service.upsert_fee(
        client,
        hunt_listing_id=listing_id,
        hunt_id=hunt_id,
        user_id=admin.id,
        fee_slot=fee_slot,
        body=body,
        authorized_admin=True,
    )
    await _audit_hunt(
        audit,
        "listing.fee.update",
        hunt_id,
        target_type="listing",
        target_id=listing_id,
        after={"fee_slot": fee_slot, **body.model_dump(mode="json")},
    )
    return result


@router.put("/listings/{listing_id}/utilities/{utility}", response_model=UtilityOverrideResponse)
async def upsert_utility(
    listing_id: UUID,
    utility: UtilityName,
    body: UtilityOverrideUpsert,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> UtilityOverrideResponse:
    listing = await _require_ghost_listing(pool, listing_id, admin)
    hunt_id = UUID(str(listing["hunt_id"]))
    result = await utility_service.upsert_utility_override(
        client,
        hunt_listing_id=listing_id,
        hunt_id=hunt_id,
        user_id=admin.id,
        utility=utility,
        body=body,
        authorized_admin=True,
    )
    await _audit_hunt(
        audit,
        "listing.utility.update",
        hunt_id,
        target_type="listing",
        target_id=listing_id,
        after={"utility": utility, **body.model_dump(mode="json")},
    )
    return result


@router.patch("/hunts/{hunt_id}/members/{target_user_id}", response_model=MemberResponse)
async def patch_member(
    hunt_id: UUID,
    target_user_id: UUID,
    body: MemberPatch,
    admin: AdminUser,
    pool: DbPool,
    audit: Audit,
) -> MemberResponse:
    await _require_ghost_hunt(pool, hunt_id, admin)
    if body.role is None or body.color is not None or "display_name" in body.model_fields_set:
        raise GhostViewUnavailable("Ghost View may change another member's role only")
    row = await pool.fetchrow(
        "update hunt_members set role=$3 where hunt_id=$1 and user_id=$2 and role <> 'owner' "
        "returning user_id, role, color, display_name",
        hunt_id,
        target_user_id,
        body.role,
    )
    if row is None:
        raise GhostTargetNotFound("Member not found or is the Hunt Owner")
    result = MemberResponse.model_validate(dict(row))
    await _audit_hunt(
        audit,
        "hunt.member.role.update",
        hunt_id,
        target_type="user",
        target_id=target_user_id,
        after={"role": body.role},
    )
    return result


@router.delete("/hunts/{hunt_id}/members/{target_user_id}", status_code=204)
async def remove_member(
    hunt_id: UUID, target_user_id: UUID, admin: AdminUser, pool: DbPool, audit: Audit
) -> None:
    await _require_ghost_hunt(pool, hunt_id, admin)
    result = await pool.execute(
        "delete from hunt_members where hunt_id=$1 and user_id=$2 and role <> 'owner'",
        hunt_id,
        target_user_id,
    )
    if result == "DELETE 0":
        raise GhostTargetNotFound("Member not found or is the Hunt Owner")
    await _audit_hunt(
        audit, "hunt.member.remove", hunt_id, target_type="user", target_id=target_user_id
    )


@router.post("/hunts/{hunt_id}/transfer-ownership", response_model=TransferOwnershipResponse)
async def transfer_ownership(
    hunt_id: UUID,
    body: TransferOwnershipRequest,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> TransferOwnershipResponse:
    await _require_ghost_hunt(pool, hunt_id, admin)
    result = privileged.transfer_ownership(client, hunt_id, body.new_owner_id)
    if result.get("status") == "not_member":
        raise TransferTargetNotMember("The new owner must already be a member of the Hunt")
    await _audit_hunt(
        audit, "hunt.ownership.transfer", hunt_id, target_type="user", target_id=body.new_owner_id
    )
    return TransferOwnershipResponse(status="ok")


@router.get("/hunts/{hunt_id}/invites", response_model=list[InviteResponse])
async def list_invites(
    hunt_id: UUID,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    settings: SettingsDep,
) -> list[InviteResponse]:
    await _require_ghost_hunt(pool, hunt_id, admin)
    return await invite_service.list_invites(client, settings.frontend_url, hunt_id)


@router.post("/hunts/{hunt_id}/invites", response_model=InviteResponse, status_code=201)
async def create_invite(
    hunt_id: UUID,
    body: InviteCreate,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    settings: SettingsDep,
    audit: Audit,
) -> InviteResponse:
    await _require_ghost_hunt(pool, hunt_id, admin)
    result = await invite_service.create_invite(client, settings, hunt_id, admin.id, body)
    await _audit_hunt(
        audit,
        "hunt.invite.create",
        hunt_id,
        target_type="invite",
        target_id=result.id,
        after={"email": body.email, "role": body.role},
    )
    return result


@router.delete("/invites/{invite_id}", status_code=204)
async def revoke_invite(
    invite_id: UUID, admin: AdminUser, pool: DbPool, client: ServiceClient, audit: Audit
) -> None:
    row = await pool.fetchrow("select hunt_id, email from invites where id=$1", invite_id)
    if row is None:
        raise GhostTargetNotFound("Invite not found")
    hunt_id = UUID(str(row["hunt_id"]))
    await _require_ghost_hunt(pool, hunt_id, admin)
    await invite_service.revoke_invite(client, invite_id)
    await _audit_hunt(
        audit,
        "hunt.invite.revoke",
        hunt_id,
        target_type="invite",
        target_id=invite_id,
        before={"email": row["email"]},
    )


@router.get("/hunts/{hunt_id}/invitation-links", response_model=list[InvitationLinkResponse])
async def list_invitation_links(
    hunt_id: UUID,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    settings: SettingsDep,
) -> list[InvitationLinkResponse]:
    await _require_ghost_hunt(pool, hunt_id, admin)
    return await invitation_link_service.list_invitation_links(
        client, settings.frontend_url, hunt_id
    )


@router.post(
    "/hunts/{hunt_id}/invitation-links",
    response_model=InvitationLinkResponse,
    status_code=201,
)
async def create_invitation_link(
    hunt_id: UUID,
    body: InvitationLinkCreate,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    settings: SettingsDep,
    audit: Audit,
) -> InvitationLinkResponse:
    await _require_ghost_hunt(pool, hunt_id, admin)
    result = await invitation_link_service.create_invitation_link(
        client, settings, hunt_id, admin.id, body
    )
    await _audit_hunt(
        audit,
        "hunt.invitation_link.create",
        hunt_id,
        target_type="invitation_link",
        target_id=result.id,
        after=body.model_dump(mode="json"),
    )
    return result


async def _invitation_link_hunt(pool: DbPool, invitation_link_id: UUID, admin: AdminUser) -> UUID:
    hunt_id = await pool.fetchval(
        "select hunt_id from invitation_links where id=$1", invitation_link_id
    )
    if hunt_id is None:
        raise GhostTargetNotFound("Invitation Link not found")
    await _require_ghost_hunt(pool, hunt_id, admin)
    return UUID(str(hunt_id))


@router.patch("/invitation-links/{invitation_link_id}", response_model=InvitationLinkResponse)
async def patch_invitation_link(
    invitation_link_id: UUID,
    body: InvitationLinkPatch,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    settings: SettingsDep,
    audit: Audit,
) -> InvitationLinkResponse:
    hunt_id = await _invitation_link_hunt(pool, invitation_link_id, admin)
    result = await invitation_link_service.patch_invitation_link(
        client, settings.frontend_url, invitation_link_id, body
    )
    await _audit_hunt(
        audit,
        "hunt.invitation_link.update",
        hunt_id,
        target_type="invitation_link",
        target_id=invitation_link_id,
        after=body.model_dump(mode="json"),
    )
    return result


@router.delete("/invitation-links/{invitation_link_id}", status_code=204)
async def delete_invitation_link(
    invitation_link_id: UUID,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> None:
    hunt_id = await _invitation_link_hunt(pool, invitation_link_id, admin)
    await invitation_link_service.delete_invitation_link(client, invitation_link_id, admin.id)
    await _audit_hunt(
        audit,
        "hunt.invitation_link.delete",
        hunt_id,
        target_type="invitation_link",
        target_id=invitation_link_id,
    )


@router.get("/hunts/{hunt_id}/jobs", response_model=list[JobResponse])
async def list_jobs(
    hunt_id: UUID,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    states: Annotated[list[JobState] | None, Depends(parse_job_states)],
) -> list[JobResponse]:
    await _require_ghost_hunt(pool, hunt_id, admin)
    return await job_service.list_jobs(client, hunt_id, states)


async def _require_ghost_job(pool: DbPool, job_id: UUID, admin: AdminUser) -> dict:
    row = await pool.fetchrow("select * from jobs where id=$1", job_id)
    if row is None:
        raise GhostTargetNotFound("Job not found")
    await _require_ghost_hunt(pool, row["hunt_id"], admin)
    return dict(row)


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: UUID, admin: AdminUser, pool: DbPool, client: ServiceClient, audit: Audit
) -> JobResponse:
    row = await _require_ghost_job(pool, job_id, admin)
    result = await job_service.cancel_job(client, job_id, admin.id, authorized_admin=True)
    await _audit_hunt(
        audit,
        "job.cancel",
        UUID(str(row["hunt_id"])),
        target_type="job",
        target_id=job_id,
        before={"state": row["state"]},
        after={"state": result.state.value},
    )
    return result


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
async def retry_job(
    job_id: UUID, admin: AdminUser, pool: DbPool, client: ServiceClient, audit: Audit
) -> JobResponse:
    row = await _require_ghost_job(pool, job_id, admin)
    result = await job_service.retry_job(client, job_id, admin.id, authorized_admin=True)
    await _audit_hunt(
        audit,
        "job.retry",
        UUID(str(row["hunt_id"])),
        target_type="job",
        target_id=job_id,
        before={"state": row["state"]},
        after={"state": result.state.value},
    )
    return result


@router.post("/jobs/{job_id}/checkpoint", response_model=JobResponse)
async def answer_checkpoint(
    job_id: UUID,
    body: CheckpointAnswer,
    admin: AdminUser,
    pool: DbPool,
    client: ServiceClient,
    audit: Audit,
) -> JobResponse:
    row = await _require_ghost_job(pool, job_id, admin)
    payload = job_service._parse_payload(row.get("payload"))
    auto = payload.get("auto_resolved_checkpoint")

    if row["state"] == JobState.WAITING_USER.value:
        run_state = payload.get("run_state") or {}
        prompt_raw = run_state.get("checkpoint")
        if not isinstance(prompt_raw, dict):
            raise InvalidCheckpointAnswer("Job has no checkpoint prompt")
        prompt = CheckpointPrompt.model_validate(prompt_raw)
        _validate_checkpoint_choice(prompt, body)
        payload["checkpoint_answer"] = {
            **body.answer,
            "context_ref": prompt.context_ref,
        }
        run_state["status"] = JobState.RUNNING.value
        run_state["checkpoint"] = None
        payload["run_state"] = run_state
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "update jobs set state='queued', payload=$2::jsonb where id=$1",
                job_id,
                json.dumps(payload),
            )
            await connection.execute(
                "insert into job_events(job_id,stage,event,detail) "
                "values($1,$2,'checkpoint_answered',$3::jsonb)",
                job_id,
                row.get("current_stage") or "checkpoint",
                json.dumps(
                    {"answer": body.answer, "kind": prompt.kind.value, "question": prompt.question}
                ),
            )
        result_id = job_id
    else:
        if not isinstance(auto, dict):
            raise InvalidCheckpointAnswer("Job is not waiting for a checkpoint answer")
        if row["state"] not in {JobState.DONE.value, JobState.FAILED.value}:
            raise InvalidCheckpointAnswer("Auto-resolved checkpoint is still being applied")
        prompt_raw = auto.get("prompt")
        snapshot = auto.get("snapshot")
        if not isinstance(prompt_raw, dict) or not isinstance(snapshot, dict):
            raise InvalidCheckpointAnswer("Job has no auto-resolved checkpoint prompt")
        prompt = CheckpointPrompt.model_validate(prompt_raw)
        _validate_checkpoint_choice(prompt, body)
        if auto.get("correction_job_id"):
            raise InvalidCheckpointAnswer("Auto-resolved checkpoint was already corrected")
        provenance = await pool.fetchval(
            "select exists(select 1 from job_events where job_id=$1 "
            "and event='checkpoint_auto_resolved')",
            job_id,
        )
        if snapshot.get("job_id") != str(job_id) or not provenance:
            raise InvalidCheckpointAnswer("Checkpoint correction provenance is invalid")
        result_id = uuid4()
        corrected_at = datetime.now(UTC).isoformat()
        corrected_snapshot = {
            **snapshot,
            "job_id": str(result_id),
            "status": JobState.RUNNING.value,
            "checkpoint": None,
        }
        corrected_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"checkpoint_answer", "auto_resolved_checkpoint"}
        }
        corrected_payload.update(
            {
                "run_state": corrected_snapshot,
                "checkpoint_answer": {**body.answer, "context_ref": prompt.context_ref},
                "trigger": "admin:ghost:checkpoint_correction",
                "corrects_job_id": str(job_id),
            }
        )
        auto.update(
            {
                "correction_job_id": str(result_id),
                "correction_answer": body.answer,
                "corrected_at": corrected_at,
            }
        )
        payload["auto_resolved_checkpoint"] = auto
        plan = job_service._parse_payload(row.get("plan")) if row.get("plan") else None
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute(
                """insert into jobs(id,hunt_id,hunt_listing_id,type,state,plan,payload)
                values($1,$2,$3,$4,'queued',$5::jsonb,$6::jsonb)""",
                result_id,
                UUID(str(row["hunt_id"])),
                row.get("hunt_listing_id"),
                row["type"],
                json.dumps(plan) if plan is not None else None,
                json.dumps(corrected_payload),
            )
            await connection.execute(
                "update jobs set payload=$2::jsonb where id=$1", job_id, json.dumps(payload)
            )
            await connection.execute(
                "insert into job_events(job_id,stage,event,detail) "
                "values($1,$2,'checkpoint_answered',$3::jsonb)",
                job_id,
                row.get("current_stage") or prompt.kind.value,
                json.dumps(
                    {"answer": body.answer, "late": True, "correction_job_id": str(result_id)}
                ),
            )

    updated = await job_service.get_job_row(client, result_id)
    if updated is None:
        raise RuntimeError("checkpoint answer returned no Job")
    result = job_service.row_to_response(updated)
    await _audit_hunt(
        audit,
        "job.checkpoint.answer",
        UUID(str(row["hunt_id"])),
        target_type="job",
        target_id=job_id,
        after={"answer": body.answer, "result_job_id": str(result_id)},
    )
    return result


def _validate_checkpoint_choice(prompt: CheckpointPrompt, body: CheckpointAnswer) -> None:
    choice = body.answer.get("choice")
    if not isinstance(choice, str) or choice not in prompt.options:
        raise InvalidCheckpointAnswer(f"Answer must be one of {prompt.options}, got {choice!r}")
