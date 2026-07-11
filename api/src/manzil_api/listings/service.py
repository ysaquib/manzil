"""Listings service — wraps supabase-py (IMPLEMENTATION §2)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from manzil_worker.fetching.slug_hint import search_hint

from manzil_api.hunts.exceptions import InsufficientRole
from manzil_api.listings.schemas import ListingCreate, ListingResponse, PinsPatch
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
