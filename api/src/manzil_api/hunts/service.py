"""Hunts service layer — wraps supabase-py/PostgREST (IMPLEMENTATION §2; no ORM)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from manzil_api.hunts.exceptions import InvalidHuntSettings
from manzil_api.hunts.schemas import (
    HuntCreate,
    HuntResponse,
    HuntSettingsPatch,
    HuntUpdate,
)
from manzil_api.jobs.enqueue import enqueue_rescore
from supabase import Client

DEFAULT_SETTINGS: dict[str, str] = {
    "default_source_policy": "tiers_1_2_3",
    "cost_estimate_mode": "conservative",
    "min_confidence": "medium",
    "proximity_mode": "driving",
}

_SOURCE_POLICIES = frozenset(
    {"trust_link", "tier_1", "tiers_1_2", "tiers_1_2_3", "tier_1_plus_official"}
)
_COST_MODES = frozenset({"conservative", "median"})
_CONFIDENCE_LEVELS = frozenset({"low", "medium", "high"})
_PROXIMITY_MODES = frozenset({"walking", "driving"})
_SCORING_KEYS = frozenset({"cost_estimate_mode", "min_confidence"})


def _to_response(row: dict[str, Any]) -> HuntResponse:
    return HuntResponse.model_validate(row)


def _merge_settings(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = {**DEFAULT_SETTINGS, **current, **patch}
    unknown = set(patch) - set(DEFAULT_SETTINGS)
    if unknown:
        raise InvalidHuntSettings(f"Unknown settings keys: {sorted(unknown)}")
    if merged["default_source_policy"] not in _SOURCE_POLICIES:
        raise InvalidHuntSettings("Invalid default_source_policy")
    if merged["cost_estimate_mode"] not in _COST_MODES:
        raise InvalidHuntSettings("Invalid cost_estimate_mode")
    if merged["min_confidence"] not in _CONFIDENCE_LEVELS:
        raise InvalidHuntSettings("Invalid min_confidence")
    if merged["proximity_mode"] not in _PROXIMITY_MODES:
        raise InvalidHuntSettings("Invalid proximity_mode")
    return merged


async def get_hunt_row(client: Client, hunt_id: UUID) -> dict[str, Any] | None:
    """Fetch one hunt by id via the caller-authenticated client, or None."""
    response = client.table("hunts").select("*").eq("id", str(hunt_id)).limit(1).execute()
    rows = response.data or []
    return rows[0] if rows else None


async def create_hunt(client: Client, user_id: str, body: HuntCreate) -> HuntResponse:
    response = (
        client.table("hunts")
        .insert(
            {
                "name": body.name,
                "owner_id": user_id,
                "domain": body.domain,
                "settings": DEFAULT_SETTINGS,
            }
        )
        .execute()
    )
    row = (response.data or [None])[0]
    if row is None:
        raise RuntimeError("hunt insert returned no row")
    client.table("hunt_members").insert(
        {"hunt_id": row["id"], "user_id": user_id, "role": "owner"}
    ).execute()
    return _to_response(row)


async def list_hunts(client: Client, user_id: str) -> list[HuntResponse]:
    response = (
        client.table("hunts")
        .select("*")
        .eq("owner_id", user_id)
        .is_("archived_at", "null")
        .order("created_at", desc=True)
        .execute()
    )
    return [_to_response(row) for row in response.data or []]


async def patch_hunt(client: Client, hunt_id: UUID, body: HuntUpdate) -> HuntResponse:
    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.archived is not None:
        updates["archived_at"] = datetime.now(UTC).isoformat() if body.archived else None
    if updates:
        client.table("hunts").update(updates).eq("id", str(hunt_id)).execute()
    row = await get_hunt_row(client, hunt_id)
    if row is None:
        raise RuntimeError("hunt missing after patch")
    return _to_response(row)


async def patch_settings(
    client: Client, hunt_id: UUID, body: HuntSettingsPatch
) -> HuntResponse:
    row = await get_hunt_row(client, hunt_id)
    if row is None:
        raise RuntimeError("hunt missing")
    current = row.get("settings") or {}
    merged = _merge_settings(current, body.settings)
    scoring_changed = any(
        key in body.settings and body.settings[key] != current.get(key)
        for key in _SCORING_KEYS
    )
    updates: dict[str, Any] = {"settings": merged}
    if scoring_changed:
        updates["rubric_version"] = row.get("rubric_version", 0) + 1
    client.table("hunts").update(updates).eq("id", str(hunt_id)).execute()
    if scoring_changed:
        await enqueue_rescore(client, hunt_id)
    updated = await get_hunt_row(client, hunt_id)
    assert updated is not None
    return _to_response(updated)
