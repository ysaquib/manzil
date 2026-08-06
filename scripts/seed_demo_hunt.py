"""DM-6: set up the Demo Hunt and the virtual demo principal.

Idempotent. Re-running reconciles rather than piling up, so it is safe to run
after every `supabase db reset` and safe to run again when you have added
listings.

What this does **not** do is seed listings. The demo shows real extractions with
real provenance, so the Owner ingests a handful of real URLs through the ordinary
pipeline and pays for them once. This script does the human-authored parts the
pipeline cannot produce -- the Hunt, the Rubric, opinions, a tour -- and wires up
the principal.

The demo principal is a bare UUID with no `auth.users` row (DESIGN §20 v3.55).
That is why it is created here with a plain INSERT and not through the auth
admin API: there is deliberately no account. Its Curator role is synthesised by
`private.member_role()`, so it holds no `hunt_members` row either -- and the
membership guard will refuse one if you try.

Usage:
    uv run python scripts/seed_demo_hunt.py            # set up / reconcile
    uv run python scripts/seed_demo_hunt.py --status   # report, change nothing

Enabling the demo is deliberately NOT done here. Use the audited admin route
(`PATCH /v1/admin/demo`), which runs `private.demo_preflight()` in the same
transaction and writes the Admin Audit Log entry.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from uuid import UUID, uuid5

import asyncpg
from dotenv import load_dotenv

load_dotenv()

from manzil_worker.phase0_rubric import phase0_rubric  # noqa: E402

# Deterministic identities: re-running reconciles the same rows.
_NS = UUID("00000000-0000-0000-0000-00000d3e0000")
DEMO_HUNT_ID = uuid5(_NS, "demo-hunt")
DEMO_PRINCIPAL_ID = uuid5(_NS, "demo-principal")

PERSONA_EMAIL = os.environ.get("MANZIL_DEMO_PERSONA_EMAIL", "sam@manzil.local")

HUNT_SETTINGS = {
    "default_source_policy": "tiers_1_2_3",
    "cost_estimate_mode": "conservative",
    "min_confidence": "medium",
    "proximity_mode": "driving",
}

# The Owner's per-Hunt display name. §16 privacy pass: `default_display_name` is
# readable by anyone sharing a Hunt, and the Owner must be a member because they
# own it -- so the public demo would otherwise publish their real name.
OWNER_DEMO_NAME = os.environ.get("MANZIL_DEMO_OWNER_NAME", "Hunt Owner")


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"{name} is required. Export it or put it in .env")
    return value


# ── The persona ──────────────────────────────────────────────────────────────
# One additional member so the collaboration surfaces -- member colours,
# per-member Visit impressions, comment attribution -- have more than one voice.
# A real account, created confirmed with a random password and never signed into;
# no email is sent. The demo principal cannot fill this role because it is not a
# person and holds no membership.
def _ensure_persona(api_url: str, service_key: str) -> UUID | None:
    def _call(method: str, path: str, body: dict | None) -> tuple[int, str]:
        req = urllib.request.Request(
            f"{api_url}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    code, body = _call(
        "POST",
        "/auth/v1/admin/users",
        {
            "email": PERSONA_EMAIL,
            "password": secrets.token_urlsafe(24),
            "email_confirm": True,
        },
    )
    if code == 200:
        return UUID(json.loads(body)["id"])

    code, body = _call("GET", f"/auth/v1/admin/users?filter={PERSONA_EMAIL}", None)
    if code == 200:
        users = json.loads(body).get("users") or []
        if users:
            return UUID(users[0]["id"])
    print(f"  ! could not provision the persona ({code}); continuing without it")
    return None


async def _owner_id(conn: asyncpg.Connection) -> UUID:
    owner = await conn.fetchval(
        "select user_id from site_admins where is_primordial limit 1"
    )
    if owner is None:
        sys.exit(
            "No primordial Site Admin exists. Bootstrap the local admin first "
            "(see AGENTS.md), then re-run."
        )
    return owner


async def _seed(conn: asyncpg.Connection, persona: UUID | None) -> None:
    owner = await _owner_id(conn)

    # ── Hunt ─────────────────────────────────────────────────────────────────
    await conn.execute(
        """
        insert into hunts (id, name, owner_id, settings)
        values ($1, $2, $3, $4::jsonb)
        on conflict (id) do update
            set name = excluded.name, owner_id = excluded.owner_id
        """,
        DEMO_HUNT_ID,
        "Detroit 2026 (demo)",
        owner,
        json.dumps(HUNT_SETTINGS),
    )

    # The Owner membership is created by a trigger on `hunts`; set the per-Hunt
    # display name so the public demo does not publish their real one.
    await conn.execute(
        """
        insert into hunt_members (hunt_id, user_id, role, display_name, color)
        values ($1, $2, 'owner', $3, 'dusk')
        on conflict (hunt_id, user_id) do update
            set display_name = excluded.display_name, color = excluded.color
        """,
        DEMO_HUNT_ID,
        owner,
        OWNER_DEMO_NAME,
    )

    if persona is not None:
        await conn.execute(
            """
            insert into user_profiles (user_id, default_display_name)
            values ($1, 'Sam')
            on conflict (user_id) do nothing
            """,
            persona,
        )
        await conn.execute(
            """
            insert into hunt_members (hunt_id, user_id, role, display_name, color)
            values ($1, $2, 'curator', 'Sam', 'moss')
            on conflict (hunt_id, user_id) do update
                set role = excluded.role, display_name = excluded.display_name
            """,
            DEMO_HUNT_ID,
            persona,
        )

    # ── The virtual principal ────────────────────────────────────────────────
    await conn.execute(
        """
        insert into demo_accounts (user_id, created_by, note)
        values ($1, $2, 'Public demo principal - deliberately has no auth.users row')
        on conflict (user_id) do nothing
        """,
        DEMO_PRINCIPAL_ID,
        owner,
    )
    # The singleton index means a stale principal from an earlier run would block
    # this one; reconcile rather than fail.
    await conn.execute("delete from demo_accounts where user_id <> $1", DEMO_PRINCIPAL_ID)

    await conn.execute(
        "update site_settings set demo_hunt_id = $1, updated_by = $2, updated_at = now()",
        DEMO_HUNT_ID,
        owner,
    )

    # ── Rubric ───────────────────────────────────────────────────────────────
    # Rebuilt wholesale: a rubric is a set, and reconciling it row by row would
    # leave criteria somebody removed.
    await conn.execute("delete from rubric_criteria where hunt_id = $1", DEMO_HUNT_ID)
    for crit in phase0_rubric():
        await conn.execute(
            """
            insert into rubric_criteria
                (hunt_id, catalog_key, options, unknown_delta, non_negotiable,
                 is_bonus, position)
            values ($1, $2, $3::jsonb, $4, $5::jsonb, $6, $7)
            """,
            DEMO_HUNT_ID,
            crit.catalog_key,
            json.dumps([o.model_dump(mode="json") for o in crit.options]),
            crit.unknown_delta,
            json.dumps(crit.non_negotiable.model_dump(mode="json"))
            if crit.non_negotiable
            else None,
            crit.is_bonus,
            crit.position,
        )

    await _seed_opinions(conn, owner, persona)


async def _seed_opinions(
    conn: asyncpg.Connection, owner: UUID, persona: UUID | None
) -> None:
    """Comments, ratings and Interest Status over whatever listings exist.

    Skipped silently when the Hunt is still empty: listings arrive by real
    ingestion, so a fresh setup legitimately has none and this script is meant to
    be re-run afterwards.
    """
    listings = await conn.fetch(
        """
        select hl.id, hl.property_id,
               (select min(fp.beds) || '-' || min(fp.baths)
                  from floor_plans fp where fp.property_id = hl.property_id) as ug
          from hunt_listings hl
         where hl.hunt_id = $1
         order by hl.created_at
        """,
        DEMO_HUNT_ID,
    )
    if not listings:
        print("  · no listings yet - ingest a few, then re-run to add opinions")
        return

    voices = [v for v in (owner, persona) if v is not None]
    notes = [
        "Walkable to the farmers market, which matters more to me than the parking.",
        "Laundry is in the basement, not in-unit - worth confirming on the tour.",
        "Rent looks fair for the square footage, but ask about the winter heating bill.",
    ]
    statuses = ["interested", "applied", None]

    for index, row in enumerate(listings):
        await conn.execute(
            """
            insert into comments (hunt_listing_id, user_id, body)
            select $1, $2, $3
             where not exists (
                 select 1 from comments where hunt_listing_id = $1 and user_id = $2)
            """,
            row["id"],
            voices[index % len(voices)],
            notes[index % len(notes)],
        )
        if row["ug"]:
            for offset, voice in enumerate(voices):
                await conn.execute(
                    """
                    insert into ratings (hunt_listing_id, user_id, unit_group_key, rating)
                    values ($1, $2, $3, $4)
                    on conflict (hunt_listing_id, user_id, unit_group_key)
                        do update set rating = excluded.rating
                    """,
                    row["id"],
                    voice,
                    row["ug"],
                    4.0 - offset * 0.5,
                )
            status = statuses[index % len(statuses)]
            if status:
                await conn.execute(
                    """
                    insert into listing_unit_group_states
                        (hunt_listing_id, unit_group_key, interest_status, updated_by)
                    values ($1, $2, $3, $4)
                    on conflict (hunt_listing_id, unit_group_key) do update
                        set interest_status = excluded.interest_status
                    """,
                    row["id"],
                    row["ug"],
                    status,
                    owner,
                )
    print(f"  · opinions seeded over {len(listings)} listing(s)")


async def _status(conn: asyncpg.Connection) -> None:
    row = await conn.fetchrow(
        "select demo_enabled, demo_hunt_id from site_settings"
    )
    principal = await conn.fetchval("select user_id from demo_accounts limit 1")
    listings = await conn.fetchval(
        "select count(*) from hunt_listings where hunt_id = $1", DEMO_HUNT_ID
    )
    members = await conn.fetchval(
        "select count(*) from hunt_members where hunt_id = $1", DEMO_HUNT_ID
    )
    blockers = await conn.fetchval("select private.demo_preflight()")

    print(f"demo enabled : {row['demo_enabled']}")
    print(f"demo hunt    : {row['demo_hunt_id']}")
    print(f"principal    : {principal}")
    print(f"members      : {members}")
    print(f"listings     : {listings}")
    if blockers:
        print("blockers     :")
        for problem in blockers:
            print(f"  - {problem}")
    else:
        print("blockers     : none - `PATCH /v1/admin/demo {\"enabled\":true}` will succeed")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--status", action="store_true", help="report configuration, change nothing"
    )
    args = parser.parse_args()

    conn = await asyncpg.connect(_env("DATABASE_URL"))
    try:
        if args.status:
            await _status(conn)
            return

        persona = _ensure_persona(
            _env("SUPABASE_URL"), _env("SUPABASE_SERVICE_ROLE_KEY")
        )
        async with conn.transaction():
            await _seed(conn, persona)
        print("Demo Hunt reconciled.\n")
        await _status(conn)
        print(
            "\nNext: ingest a few real listings as the Owner, re-run this script to "
            "add opinions, then enable via PATCH /v1/admin/demo."
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
