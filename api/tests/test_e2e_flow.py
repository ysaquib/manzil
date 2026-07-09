"""End-to-end API flow: hunt → rubric → listing → scores → override (P1-5..P1-8)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from manzil_worker.fetching.results import FetchResult
from manzil_worker.phase0_rubric import phase0_rubric
from manzil_worker.queue import build_dispatch, run_worker_loop

FIXTURE_URL = "https://maple-court.seed.example/floorplans"
PAGE = "e2e_listing.html"


class _FixtureFetcher:
    tier = 1

    def __init__(self, body: str) -> None:
        self._body = body

    async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
        return FetchResult(url=url, final_url=url, status_code=200, body=self._body, tier=1)


@pytest.mark.asyncio
async def test_e2e_hunt_rubric_listing_override_flow(app, db_pool, monkeypatch) -> None:
    monkeypatch.setenv("MANZIL_LLM_MODE", "replay")
    body = (
        Path(__file__).resolve().parents[2] / "worker" / "tests" / "fixtures" / "pages" / PAGE
    ).read_text()
    dispatch = build_dispatch(db_pool, fetchers_factory=lambda: {1: _FixtureFetcher(body)})

    hunt_id: str | None = None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        hunt = await client.post("/v1/hunts", json={"name": "E2E Hunt"})
        assert hunt.status_code == 201
        hunt_id = hunt.json()["id"]

        criteria = [
            {
                "catalog_key": crit.catalog_key,
                "options": [o.model_dump(mode="json") for o in crit.options],
                "unknown_delta": crit.unknown_delta,
                "non_negotiable": crit.non_negotiable.model_dump(mode="json")
                if crit.non_negotiable
                else None,
                "position": crit.position,
            }
            for crit in phase0_rubric()
        ]
        rubric = await client.put(f"/v1/hunts/{hunt_id}/rubric", json={"criteria": criteria})
        assert rubric.status_code == 200

        listing = await client.post(
            f"/v1/hunts/{hunt_id}/listings", json={"url": FIXTURE_URL}
        )
        assert listing.status_code == 201
        listing_id = listing.json()["id"]

        await run_worker_loop(db_pool, asyncio.Event(), dispatch=dispatch, until_empty=True)

        job_state = await db_pool.fetchval(
            "select state from jobs where hunt_listing_id = $1", listing_id
        )
        assert job_state == "done"

        scores_before = await db_pool.fetchval(
            "select count(*) from scores where hunt_listing_id = $1", listing_id
        )
        assert scores_before >= 1

        settings = await client.patch(
            f"/v1/hunts/{hunt_id}/settings",
            json={"settings": {"min_confidence": "low"}},
        )
        assert settings.status_code == 200

        await run_worker_loop(db_pool, asyncio.Event(), dispatch=dispatch, until_empty=True)

        override = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={"criterion_key": "beds", "value": 2},
        )
        assert override.status_code == 201

        await run_worker_loop(db_pool, asyncio.Event(), dispatch=dispatch, until_empty=True)

        breakdown = await db_pool.fetchval(
            "select breakdown from scores where hunt_listing_id = $1 limit 1",
            listing_id,
        )
        assert breakdown is not None
        parsed = json.loads(breakdown) if isinstance(breakdown, str) else breakdown
        beds = next(c for c in parsed["criteria"] if c["key"] == "beds")
        assert beds["value"] == 2

    if hunt_id is not None:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
