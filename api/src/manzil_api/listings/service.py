"""Listings service — wraps supabase-py (IMPLEMENTATION §2)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from manzil_worker.fetching.slug_hint import search_hint

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
    source_policy = body.source_policy or hunt_settings.get(
        "default_source_policy", "tiers_1_2_3"
    )
    prop = (
        client.table("properties")
        .insert(
            {
                "name": _placeholder_name(body.url),
                "canonical_address": _placeholder_name(body.url),
            }
        )
        .execute()
    )
    property_row = (prop.data or [None])[0]
    if property_row is None:
        raise RuntimeError("property insert returned no row")

    listing = (
        client.table("hunt_listings")
        .insert(
            {
                "hunt_id": str(hunt_id),
                "property_id": property_row["id"],
                "added_by": user_id,
                "source_policy": source_policy,
            }
        )
        .execute()
    )
    listing_row = (listing.data or [None])[0]
    if listing_row is None:
        raise RuntimeError("listing insert returned no row")

    client.table("jobs").insert(
        {
            "hunt_listing_id": listing_row["id"],
            "type": "ingest",
            "state": "queued",
            "payload": {"url": body.url, "source_policy": source_policy},
        }
    ).execute()
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


async def delete_listing(client: Client, listing_id: UUID) -> None:
    client.table("hunt_listings").update({"status": "archived"}).eq(
        "id", str(listing_id)
    ).execute()


async def patch_pins(client: Client, listing_id: UUID, body: PinsPatch) -> ListingResponse:
    client.table("hunt_listings").update({"pins": body.pins}).eq("id", str(listing_id)).execute()
    row = await get_listing_row(client, listing_id)
    if row is None:
        raise RuntimeError("listing missing after pins patch")
    return _to_response(row)
