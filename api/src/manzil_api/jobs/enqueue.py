"""Enqueue hunt-level rescore jobs (rescore-on-mutation, plan §1.7)."""

from __future__ import annotations

from uuid import UUID

from supabase import Client


async def enqueue_rescore(client: Client, hunt_id: UUID) -> None:
    client.table("jobs").insert(
        {
            "type": "rescore",
            "state": "queued",
            "payload": {"hunt_id": str(hunt_id)},
        }
    ).execute()
