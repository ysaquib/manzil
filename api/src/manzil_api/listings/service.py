"""Listings service — wraps supabase-py (IMPLEMENTATION §2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from manzil_worker.fetching.slug_hint import search_hint

from manzil_api.hunts.exceptions import InsufficientRole
from manzil_api.jobs.schemas import JobResponse
from manzil_api.jobs.service import row_to_response
from manzil_api.listings.schemas import (
    ListingCreate,
    ListingResponse,
    ListingStatusPatch,
    PinsPatch,
    RefreshClass,
    RefreshRequest,
    SourcePolicyPatch,
    UnitGroupStatePatch,
    UnitGroupStateResponse,
)
from supabase import Client


def _placeholder_name(url: str) -> str:
    hint = search_hint(url)
    if hint:
        return hint.title()
    host = urlsplit(url).hostname
    return host or "Unknown listing"


def _to_response(row: dict[str, Any]) -> ListingResponse:
    return ListingResponse.model_validate(row)


async def get_listing_row(client: Client, listing_id: UUID) -> dict[str, Any] | None:
    response = (
        client.table("hunt_listings").select("*").eq("id", str(listing_id)).limit(1).execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


async def create_listing(
    client: Client,
    *,
    hunt_id: UUID,
    user_id: str,
    hunt_settings: dict[str, Any],
    body: ListingCreate,
) -> ListingResponse:
    source_policy = body.source_policy or hunt_settings.get("default_source_policy", "tiers_1_2_3")
    listing = client.rpc(
        "submit_listing",
        {
            "p_hunt_id": str(hunt_id),
            "p_url": body.url,
            "p_placeholder_name": _placeholder_name(body.url),
            "p_source_policy": source_policy,
        },
    ).execute()
    listing_row = (listing.data or [None])[0]
    if listing_row is None:
        raise RuntimeError("listing insert returned no row")

    return _to_response(listing_row)


async def list_listings(client: Client, hunt_id: UUID) -> list[ListingResponse]:
    response = (
        client.table("hunt_listings")
        .select("*")
        .eq("hunt_id", str(hunt_id))
        .eq("status", "active")
        .execute()
    )
    return [_to_response(row) for row in response.data or []]


def _role(client: Client, hunt_id: str, user_id: str) -> str:
    response = (
        client.table("hunt_members")
        .select("role")
        .eq("hunt_id", hunt_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    return response.data["role"]


async def delete_listing(client: Client, listing_id: UUID, user_id: str) -> None:
    listing = await get_listing_row(client, listing_id)
    if listing is None or _role(client, listing["hunt_id"], user_id) != "owner":
        raise InsufficientRole("Only the Hunt Owner may delete Listings")
    client.table("hunt_listings").update({"status": "archived"}).eq("id", str(listing_id)).execute()


async def patch_status(
    client: Client, listing: dict[str, Any], user_id: str, body: ListingStatusPatch
) -> ListingResponse:
    """Archive or restore — the same owner gate as delete_listing (archive's alias)."""
    if _role(client, listing["hunt_id"], user_id) != "owner":
        raise InsufficientRole("Only the Hunt Owner may archive or restore Listings")
    listing_id = UUID(listing["id"])
    client.table("hunt_listings").update({"status": body.status}).eq(
        "id", str(listing_id)
    ).execute()
    row = await get_listing_row(client, listing_id)
    if row is None:
        raise RuntimeError("listing missing after status patch")
    return _to_response(row)


async def patch_pins(
    client: Client, listing: dict[str, Any], user_id: str, body: PinsPatch
) -> ListingResponse:
    if _role(client, listing["hunt_id"], user_id) == "member" and listing["added_by"] != user_id:
        raise InsufficientRole("Members may edit pins only on their own Listings")
    listing_id = UUID(listing["id"])
    client.table("hunt_listings").update({"pins": body.pins}).eq("id", str(listing_id)).execute()
    row = await get_listing_row(client, listing_id)
    if row is None:
        raise RuntimeError("listing missing after pins patch")
    return _to_response(row)


async def patch_source_policy(
    client: Client,
    listing: dict[str, Any],
    user_id: str,
    body: SourcePolicyPatch,
) -> ListingResponse:
    """Persist policy and atomically enqueue DISCOVER when assurance relaxes."""
    role = _role(client, listing["hunt_id"], user_id)
    if role != "owner" and listing["added_by"] != user_id:
        raise InsufficientRole("Members and Curators may edit only their own Listings")
    response = client.rpc(
        "set_listing_source_policy",
        {
            "p_listing_id": listing["id"],
            "p_source_policy": body.source_policy,
        },
    ).execute()
    row = (response.data or [None])[0]
    if row is None:
        raise RuntimeError("source policy update returned no Listing")
    return _to_response(row)


def _json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return json.loads(raw)
    return raw or {}


def _refresh_matches(row: dict[str, Any], fields: list[RefreshClass]) -> bool:
    payload = _json(row.get("payload"))
    return payload.get("scope") == "classes" and payload.get("fields") == fields


def _submitted_url(client: Client, listing: dict[str, Any]) -> str:
    source_id = listing.get("submitted_source_id")
    query = client.table("property_sources").select("url")
    if source_id:
        rows = query.eq("id", source_id).limit(1).execute().data or []
    else:
        rows = (
            query.eq("property_id", listing["property_id"])
            .not_.is_("last_success_at", "null")
            .order("last_success_at")
            .limit(1)
            .execute()
            .data
            or []
        )
    if not rows:
        raise RuntimeError("Listing has no successfully fetched submitted Source")
    return str(rows[0]["url"])


async def enqueue_listing_refresh(
    client: Client,
    *,
    listing: dict[str, Any],
    user_id: str,
    body: RefreshRequest,
    trigger: str = "user",
    authorized_hunt_refresh: bool = False,
) -> JobResponse:
    """Create or coalesce one Listing-scoped refresh Job."""
    if not authorized_hunt_refresh:
        role = _role(client, listing["hunt_id"], user_id)
        if role != "owner" and listing["added_by"] != user_id:
            raise InsufficientRole("Only the Listing submitter or Hunt Owner may refresh it")
    fields = RefreshRequest.normalized_fields(body.fields)
    active = (
        client.table("jobs")
        .select("*")
        .eq("hunt_listing_id", listing["id"])
        .eq("type", "refresh")
        .in_("state", ["queued", "running", "waiting_user"])
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    matching = next((row for row in active if _refresh_matches(row, fields)), None)
    if matching is not None:
        return row_to_response(matching)
    payload = {
        "url": _submitted_url(client, listing),
        "scope": "classes",
        "fields": fields,
        "trigger": trigger,
        "hunt_id": listing["hunt_id"],
        "listing_id": listing["id"],
    }
    rows = (
        client.table("jobs")
        .insert(
            {
                "hunt_id": listing["hunt_id"],
                "hunt_listing_id": listing["id"],
                "type": "refresh",
                "state": "queued",
                "payload": payload,
            }
        )
        .execute()
        .data
        or []
    )
    if not rows:
        raise RuntimeError("refresh Job insert returned no row")
    return row_to_response(rows[0])


async def enqueue_hunt_refresh(
    client: Client,
    *,
    hunt_id: UUID,
    user_id: str,
    body: RefreshRequest,
) -> list[JobResponse]:
    """Fan out one refresh Job per active Listing."""
    listings = (
        client.table("hunt_listings")
        .select("*")
        .eq("hunt_id", str(hunt_id))
        .eq("status", "active")
        .order("created_at")
        .execute()
        .data
        or []
    )
    return [
        await enqueue_listing_refresh(
            client,
            listing=listing,
            user_id=user_id,
            body=body,
            trigger="user:hunt",
            authorized_hunt_refresh=True,
        )
        for listing in listings
    ]


async def patch_unit_group_state(
    client: Client,
    listing: dict[str, Any],
    unit_group_key: str,
    user_id: str,
    body: UnitGroupStatePatch,
) -> UnitGroupStateResponse:
    if _role(client, listing["hunt_id"], user_id) == "member":
        raise InsufficientRole("Only Hunt Curators and the Owner may curate Unit Groups")
    response = (
        client.table("listing_unit_group_states")
        .upsert(
            {
                "hunt_listing_id": listing["id"],
                "unit_group_key": unit_group_key,
                "interest_status": body.interest_status,
                "visited": body.visited,
                "updated_by": user_id,
                "updated_at": datetime.now(UTC).isoformat(),
            },
            on_conflict="hunt_listing_id,unit_group_key",
        )
        .execute()
    )
    row = (response.data or [None])[0]
    if row is None:
        raise RuntimeError("Unit Group state upsert returned no row")
    return UnitGroupStateResponse.model_validate(row)
