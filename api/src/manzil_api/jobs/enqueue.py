"""Enqueue hunt-level rescore jobs (rescore-on-mutation, plan §1.7)."""

from __future__ import annotations

from uuid import UUID

from supabase import Client


async def enqueue_rescore(client: Client, hunt_id: UUID) -> None:
    client.table("jobs").insert(
        {
            "hunt_id": str(hunt_id),
            "type": "rescore",
            "state": "queued",
            "payload": {"hunt_id": str(hunt_id)},
        }
    ).execute()


async def enqueue_enrich_refresh(client: Client, hunt_id: UUID) -> None:
    """Hunt-level ENRICH re-run + rescore (P3-8): the `proximity_mode` flip path.
    Zero LLM spend in the worker — Maps calls against cached geocodes only."""
    client.table("jobs").insert(
        {
            "hunt_id": str(hunt_id),
            "type": "refresh",
            "state": "queued",
            "payload": {"hunt_id": str(hunt_id), "scope": "enrich"},
        }
    ).execute()
