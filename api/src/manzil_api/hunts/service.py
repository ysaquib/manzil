"""Hunts service layer — wraps supabase-py/PostgREST (IMPLEMENTATION §2; no ORM)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from manzil_api.hunts.exceptions import InvalidHuntSettings
from manzil_api.hunts.schemas import (
    HuntCreate,
    HuntDeletionImpact,
    HuntResponse,
    HuntSettingsPatch,
    HuntUpdate,
    SharedFiltersPut,
    SharedFiltersResponse,
)
from manzil_api.jobs.enqueue import enqueue_enrich_refresh, enqueue_rescore
from supabase import Client

DEFAULT_SETTINGS: dict[str, Any] = {
    "default_source_policy": "tiers_1_2_3",
    "cost_estimate_mode": "conservative",
    "min_confidence": "medium",
    "min_vision_confidence": "low",
    "generalized_vision_policy": "full_rubric",
    "proximity_mode": "driving",
    "occupants": 1,
    "cats": 0,
    "dogs": 0,
}

_SOURCE_POLICIES = frozenset(
    {"trust_link", "tier_1", "tiers_1_2", "tiers_1_2_3", "tier_1_plus_official"}
)
_COST_MODES = frozenset({"conservative", "median"})
_CONFIDENCE_LEVELS = frozenset({"low", "medium", "high"})
_GENERALIZED_VISION_POLICIES = frozenset({"full_rubric", "points_only", "unknown"})
_PROXIMITY_MODES = frozenset({"walking", "driving"})
# Household integer keys with inclusive [lo, hi] bounds (§9.5 v1).
_HOUSEHOLD_BOUNDS: dict[str, tuple[int, int]] = {
    "occupants": (1, 20),
    "cats": (0, 10),
    "dogs": (0, 10),
}
# Keys whose change bumps rubric_version + enqueues a rescore. `occupants`
# joined at P3-9: it scales the per-person utility estimates in the §9.5
# composition, so a change re-scores like the other household keys.
_SCORING_KEYS = frozenset(
    {
        "cost_estimate_mode",
        "min_confidence",
        "min_vision_confidence",
        "generalized_vision_policy",
        "cats",
        "dogs",
        "occupants",
    }
)


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
    if merged["min_vision_confidence"] not in _CONFIDENCE_LEVELS:
        raise InvalidHuntSettings("Invalid min_vision_confidence")
    if merged["generalized_vision_policy"] not in _GENERALIZED_VISION_POLICIES:
        raise InvalidHuntSettings("Invalid generalized_vision_policy")
    if merged["proximity_mode"] not in _PROXIMITY_MODES:
        raise InvalidHuntSettings("Invalid proximity_mode")
    for key, (lo, hi) in _HOUSEHOLD_BOUNDS.items():
        value = merged[key]
        # bool is an int subclass in Python — reject it explicitly.
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidHuntSettings(f"{key} must be an integer")
        if not lo <= value <= hi:
            raise InvalidHuntSettings(f"{key} must be between {lo} and {hi}")
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
    return _to_response(row)


async def list_hunts(client: Client, user_id: str) -> list[HuntResponse]:
    response = client.table("hunts").select("*").order("created_at", desc=True).execute()
    return [_to_response(row) for row in response.data or []]


async def patch_hunt(client: Client, hunt_id: UUID, body: HuntUpdate) -> HuntResponse:
    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if updates:
        client.table("hunts").update(updates).eq("id", str(hunt_id)).execute()
    if body.archived is not None:
        client.rpc(
            "set_hunt_archived",
            {"p_hunt_id": str(hunt_id), "p_archived": body.archived},
        ).execute()
    row = await get_hunt_row(client, hunt_id)
    if row is None:
        raise RuntimeError("hunt missing after patch")
    return _to_response(row)


async def get_deletion_impact(client: Client, hunt_id: UUID) -> HuntDeletionImpact:
    response = client.rpc("get_hunt_deletion_impact", {"p_hunt_id": str(hunt_id)}).execute()
    if not response.data:
        raise RuntimeError("hunt deletion impact returned no row")
    return HuntDeletionImpact.model_validate(response.data)


async def delete_hunt_permanently(
    client: Client, hunt_id: UUID, confirmation_name: str
) -> HuntDeletionImpact:
    response = client.rpc(
        "delete_hunt_permanently",
        {
            "p_hunt_id": str(hunt_id),
            "p_confirmation_name": confirmation_name,
        },
    ).execute()
    if not response.data:
        raise RuntimeError("hunt permanent deletion returned no impact")
    return HuntDeletionImpact.model_validate(response.data)


async def put_shared_filters(
    client: Client, hunt_id: UUID, user_id: str, body: SharedFiltersPut
) -> SharedFiltersResponse:
    """Upsert the hunt-wide filter set. Role is double-enforced: the router's
    CuratedHunt dependency and the hunt_shared_filters RLS write policies."""
    response = (
        client.table("hunt_shared_filters")
        .upsert(
            {
                "hunt_id": str(hunt_id),
                "filters": body.filters,
                "updated_by": user_id,
                "updated_at": datetime.now(UTC).isoformat(),
            },
            on_conflict="hunt_id",
        )
        .execute()
    )
    row = (response.data or [None])[0]
    if row is None:
        raise RuntimeError("shared-filters upsert returned no row")
    return SharedFiltersResponse.model_validate(row)


async def patch_settings(client: Client, hunt_id: UUID, body: HuntSettingsPatch) -> HuntResponse:
    row = await get_hunt_row(client, hunt_id)
    if row is None:
        raise RuntimeError("hunt missing")
    current = row.get("settings") or {}
    merged = _merge_settings(current, body.settings)
    scoring_changed = any(
        key in body.settings and body.settings[key] != current.get(key) for key in _SCORING_KEYS
    )
    # P3-8: a proximity_mode flip re-derives the Maps-only location criteria and
    # rescores via a `refresh` job (scope: enrich) — no rubric bump, no LLM spend.
    # Field-scoping arrives with P3-12; until then this re-runs the full slice.
    proximity_changed = "proximity_mode" in body.settings and body.settings[
        "proximity_mode"
    ] != current.get("proximity_mode", DEFAULT_SETTINGS["proximity_mode"])
    updates: dict[str, Any] = {"settings": merged}
    if scoring_changed:
        updates["rubric_version"] = row.get("rubric_version", 0) + 1
    client.table("hunts").update(updates).eq("id", str(hunt_id)).execute()
    if scoring_changed:
        await enqueue_rescore(client, hunt_id)
    if proximity_changed:
        await enqueue_enrich_refresh(client, hunt_id)
    updated = await get_hunt_row(client, hunt_id)
    assert updated is not None
    return _to_response(updated)
