"""Dev seed (P1-1): a runnable local fixture for the whole stack.

Assumes `supabase db reset` already ran (schema + catalog seeded). This script
adds one dev user, one hunt with a rubric, and three listings — and crucially it
creates those listings the *real* way: it enqueues three `ingest` jobs against
three committed synthetic fixture pages and drains them through the actual
`run_worker_loop` in `MANZIL_LLM_MODE=replay`. So it both seeds usable data and
smoke-tests that the ingest path writes to Postgres correctly (the P1-2 swap it
precedes).

Dev user: a fixed UUID owner, not a provisioned Supabase auth user. Migration
0002 deliberately gives every user-id column no FK to `auth.users` (auth/RLS is
P2-1), and its own comment says the dev-seed "must insert without provisioning
auth users" — so an auth-admin call would be disproportionate. RLS is off until
P2-1, so a plain UUID owner exercises everything Phase 1 needs.

Idempotent: it deletes its own hunt (cascades listings/jobs/rubric/scores) and
its fixed properties (cascades sources/floor_plans/extractions) before rebuilding.

Runs in `replay` by default; export `MANZIL_LLM_MODE=record` to (re)record the
fixture-page LLM responses against the live provider.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID, uuid5

import asyncpg
from dotenv import load_dotenv

load_dotenv()  # override=False: an explicitly exported MANZIL_LLM_MODE wins
if os.environ.get("MANZIL_LLM_MODE") != "record":
    os.environ["MANZIL_LLM_MODE"] = "replay"

from manzil_worker.fetching.results import FetchResult  # noqa: E402
from manzil_worker.phase0_rubric import phase0_rubric  # noqa: E402
from manzil_worker.queue import build_dispatch, run_worker_loop  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGES_DIR = REPO_ROOT / "worker" / "tests" / "fixtures" / "pages"

# Deterministic identities so re-running is a clean replace, not a pile-up.
_NS = UUID("00000000-0000-0000-0000-00000d5eed00")
DEV_USER_ID = uuid5(_NS, "dev-user")
DEV_HUNT_ID = uuid5(_NS, "dev-hunt")

DEFAULT_SETTINGS = {
    "default_source_policy": "tiers_1_2_3",
    "cost_estimate_mode": "conservative",
    "min_confidence": "medium",
    "proximity_mode": "driving",
}

# Three listing-bearing committed synthetic pages, with fake-but-public URLs that
# pass VALIDATE_URL (no loopback/private host). Served by FixtureFetcher.
# NOTE: the P1-1 brief named success_jsonld.html, but that is a 230-char
# classifier smoke fixture (used only by test_classifier) that fails VALIDATE's
# 800-char listing floor — it is not ingestable. injection_listing.html is a
# genuine listing page (and doubles as a prompt-injection resistance smoke), so
# it takes the third slot. e2e_listing / success_text / injection_listing are the
# only committed synthetic pages that pass the real ingest path.
SEED_LISTINGS = [
    ("e2e_listing.html", "https://maple-court.seed.example/floorplans", "Maple Court Apartments"),
    ("success_text.html", "https://oakwood.seed.example/apartments", "Oakwood Flats"),
    ("injection_listing.html", "https://willow-bend.seed.example/apartments", "Willow Bend Flats"),
]


class FixtureFetcher:
    """Tier-1 fetcher that serves committed fixture-page bodies by URL — the
    same "inject the world through StageCtx" seam the pipeline tests use, so the
    seed drives the real stages without touching the network."""

    tier = 1

    def __init__(self, bodies: dict[str, str]) -> None:
        self._bodies = bodies

    async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
        return FetchResult(
            url=url, final_url=url, status_code=200, body=self._bodies[url], tier=1
        )


def _fixture_bodies() -> dict[str, str]:
    return {url: (PAGES_DIR / slug).read_text() for slug, url, _ in SEED_LISTINGS}


async def _reset_dev_data(conn: asyncpg.Connection) -> None:
    await conn.execute("delete from hunts where id = $1", DEV_HUNT_ID)
    property_ids = [uuid5(_NS, f"property:{slug}") for slug, _, _ in SEED_LISTINGS]
    await conn.execute("delete from properties where id = any($1::uuid[])", property_ids)


async def _seed_hunt_and_rubric(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        insert into hunts (id, name, owner_id, domain, rubric_version, settings)
        values ($1, $2, $3, 'rent', 0, $4::jsonb)
        """,
        DEV_HUNT_ID,
        "Dev Hunt",
        DEV_USER_ID,
        json.dumps(DEFAULT_SETTINGS),
    )
    await conn.execute(
        "insert into hunt_members (hunt_id, user_id, role) values ($1, $2, 'owner')",
        DEV_HUNT_ID,
        DEV_USER_ID,
    )
    for crit in phase0_rubric():
        await conn.execute(
            """
            insert into rubric_criteria
                (hunt_id, catalog_key, options, unknown_delta, non_negotiable,
                 is_bonus, position)
            values ($1, $2, $3::jsonb, $4, $5::jsonb, $6, $7)
            """,
            DEV_HUNT_ID,
            crit.catalog_key,
            json.dumps([o.model_dump(mode="json") for o in crit.options]),
            crit.unknown_delta,
            json.dumps(crit.non_negotiable.model_dump(mode="json"))
            if crit.non_negotiable
            else None,
            crit.is_bonus,
            crit.position,
        )


async def _seed_listings_and_jobs(conn: asyncpg.Connection) -> None:
    for slug, url, name in SEED_LISTINGS:
        property_id = uuid5(_NS, f"property:{slug}")
        listing_id = uuid5(_NS, f"listing:{slug}")
        await conn.execute(
            "insert into properties (id, name, canonical_address) values ($1, $2, $3)",
            property_id,
            name,
            f"{name} (dev seed)",
        )
        await conn.execute(
            """
            insert into hunt_listings (id, hunt_id, property_id, added_by, source_policy)
            values ($1, $2, $3, $4, 'tiers_1_2_3')
            """,
            listing_id,
            DEV_HUNT_ID,
            property_id,
            DEV_USER_ID,
        )
        await conn.execute(
            """
            insert into jobs (hunt_listing_id, type, state, payload)
            values ($1, 'ingest', 'queued', $2::jsonb)
            """,
            listing_id,
            json.dumps({"url": url}),
        )


async def _report(conn: asyncpg.Connection) -> tuple[int, int, int]:
    hunts = await conn.fetchval("select count(*) from hunts where owner_id = $1", DEV_USER_ID)
    listings = await conn.fetchval(
        "select count(*) from hunt_listings where hunt_id = $1", DEV_HUNT_ID
    )
    scores = await conn.fetchval(
        """
        select count(*) from scores s
        join hunt_listings hl on hl.id = s.hunt_listing_id
        where hl.hunt_id = $1 and s.total <> 0
        """,
        DEV_HUNT_ID,
    )
    return hunts, listings, scores


async def seed(pool: asyncpg.Pool) -> tuple[int, int, int]:
    """Seed idempotently and drain the ingest jobs. Returns
    (hunts, listings, non-zero scores) so callers can assert the P1-1 done-when."""
    async with pool.acquire() as conn, conn.transaction():
        await _reset_dev_data(conn)
        await _seed_hunt_and_rubric(conn)
        await _seed_listings_and_jobs(conn)

    dispatch = build_dispatch(pool, fetchers_factory=lambda: {1: FixtureFetcher(_fixture_bodies())})
    await run_worker_loop(pool, asyncio.Event(), dispatch=dispatch, until_empty=True)

    async with pool.acquire() as conn:
        failed = await conn.fetch(
            """
            select j.id, j.error from jobs j
            join hunt_listings hl on hl.id = j.hunt_listing_id
            where hl.hunt_id = $1 and j.state = 'failed'
            """,
            DEV_HUNT_ID,
        )
        if failed:
            details = "; ".join(f"{r['id']}: {r['error']}" for r in failed)
            raise RuntimeError(f"seed ingest jobs failed: {details}")
        return await _report(conn)


async def _main() -> None:
    dsn = os.environ["DATABASE_URL"]
    pool = await asyncpg.create_pool(dsn)
    try:
        hunts, listings, scores = await seed(pool)
    finally:
        await pool.close()
    print(f"seed complete: {hunts} hunt(s), {listings} listing(s), {scores} non-zero score(s)")
    if not (hunts == 1 and listings == 3 and scores >= 1):
        raise SystemExit(
            f"seed did not meet the P1-1 done-when (1 hunt / 3 listings / non-zero scores): "
            f"got {hunts}/{listings}/{scores}"
        )


if __name__ == "__main__":
    asyncio.run(_main())
