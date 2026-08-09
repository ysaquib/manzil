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

The Demo Hunt id is derived, so re-running reconciles the same rows. Set
`MANZIL_DEMO_HUNT_ID` to adopt a Hunt that already exists instead -- one the
Owner created through the UI and has already ingested into. An adopted Hunt is
treated as somebody else's work: its name, owner and Rubric are left alone
(`--force-rubric` overrides the last of those, destructively).

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
from pathlib import Path
from uuid import UUID, uuid5

import asyncpg
from dotenv import load_dotenv

load_dotenv()

from manzil_worker.phase0_rubric import phase0_rubric  # noqa: E402

# Deterministic identities: re-running reconciles the same rows.
_NS = UUID("00000000-0000-0000-0000-00000d3e0000")
_DEFAULT_DEMO_HUNT_ID = uuid5(_NS, "demo-hunt")


def _demo_hunt_id() -> tuple[UUID, bool]:
    """The Demo Hunt to manage, and whether it was named rather than derived.

    The id is normally derived so re-running reconciles the same rows without
    anyone having to record it. But the Demo Hunt is an ordinary Hunt the Owner
    ingests into and is billed for (DESIGN §3), and that Hunt may already exist
    -- created through the UI, with real listings and a Rubric somebody tuned.
    Deriving a *different* id in that case does not adopt it; it silently builds
    a second, empty Demo Hunt beside it.

    `MANZIL_DEMO_HUNT_ID` names the Hunt to adopt instead. Adoption is
    deliberately gentler than creation: an adopted Hunt keeps its own name,
    owner and Rubric (see `_seed`), because everything in it predates this
    script and none of it is ours to overwrite.
    """
    raw = os.environ.get("MANZIL_DEMO_HUNT_ID", "").strip()
    if not raw:
        return _DEFAULT_DEMO_HUNT_ID, False
    try:
        return UUID(raw), True
    except ValueError:
        sys.exit(f"MANZIL_DEMO_HUNT_ID is not a UUID: {raw!r}")


DEMO_HUNT_ID, DEMO_HUNT_ADOPTED = _demo_hunt_id()
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


def _service_key() -> str:
    """The server key, under either name.

    Production moved to `SUPABASE_SECRET_KEY`; the local Supabase CLI still
    emits only the legacy service-role JWT, so accept both rather than make the
    seed runnable in exactly one of the two places it is used.
    """
    for name in ("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    sys.exit("SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY) is required.")


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
    owner = await conn.fetchval("select user_id from site_admins where is_primordial limit 1")
    if owner is None:
        sys.exit(
            "No primordial Site Admin exists. Bootstrap the local admin first "
            "(see AGENTS.md), then re-run."
        )
    return owner


class DemoPrincipalConflict(RuntimeError):
    """The configured principal is not virtual, so seeding must not proceed."""


async def reconcile_demo_principal(conn: asyncpg.Connection, owner: UUID) -> list[str]:
    """Make `demo_accounts` hold exactly the virtual principal. Returns warnings.

    Order matters here, and it used to be wrong (R2 H1): the seed inserted first
    and deleted the stale singleton afterwards, so the unique index rejected the
    insert and the delete never ran. An installation carrying an *earlier* Demo
    Account -- which is every installation seeded before v3.55, when the
    principal was still a real Auth user -- could therefore not be upgraded at
    all, and `demo_preflight()` would then refuse to enable the demo because
    that surviving principal still has an `auth.users` row.

    Reconcile first, then insert. Callers run this inside a transaction, so
    there is no window in which no principal exists.
    """
    warnings: list[str] = []

    stale = await conn.fetch(
        "select user_id from demo_accounts where user_id <> $1", DEMO_PRINCIPAL_ID
    )
    await conn.execute("delete from demo_accounts where user_id <> $1", DEMO_PRINCIPAL_ID)
    await conn.execute(
        """
        insert into demo_accounts (user_id, created_by, note)
        values ($1, $2, 'Public demo principal - deliberately has no auth.users row')
        on conflict (user_id) do update set note = excluded.note
        """,
        DEMO_PRINCIPAL_ID,
        owner,
    )

    # A stale principal that was a real account leaves an Auth user behind. It is
    # no longer the demo identity, but silently stranding it would leave a
    # password-bearing account nobody is watching -- so say so rather than
    # deleting an account this script was not asked to manage.
    for row in stale:
        if await conn.fetchval(
            "select exists (select 1 from auth.users where id = $1)", row["user_id"]
        ):
            warnings.append(
                f"former Demo Account {row['user_id']} still has an auth.users row. "
                "It is no longer the demo principal; remove it through the audited "
                "Site Admin path, or confirm it is a real account that should keep "
                "existing."
            )

    # The principal must have no account behind it: that is the entire C3
    # defence (DESIGN §20 v3.55). Asserted rather than assumed, because a
    # collision here would be silent and would reintroduce the whole GoTrue
    # takeover surface.
    if await conn.fetchval(
        "select exists (select 1 from auth.users where id = $1)", DEMO_PRINCIPAL_ID
    ):
        raise DemoPrincipalConflict(
            f"The demo principal {DEMO_PRINCIPAL_ID} has an auth.users row. It must "
            "be virtual -- an account behind it can have its password changed and "
            "every visitor signed out."
        )

    # It must hold no stored membership either: its Curator role is synthesised
    # by private.member_role(), and the membership guard refuses stored rows.
    await conn.execute("delete from hunt_members where user_id = $1", DEMO_PRINCIPAL_ID)
    return warnings


async def _seed(
    conn: asyncpg.Connection, persona: UUID | None, *, force_rubric: bool = False
) -> None:
    owner = await _owner_id(conn)

    # ── Hunt ─────────────────────────────────────────────────────────────────
    # An adopted Hunt (MANZIL_DEMO_HUNT_ID) is left as its Owner made it: name,
    # owner and settings all predate this script. Only a Hunt this script
    # creates gets this script's opinions about those three things.
    existing_name = await conn.fetchval("select name from hunts where id = $1", DEMO_HUNT_ID)
    if existing_name is not None and DEMO_HUNT_ADOPTED:
        print(f"  adopted existing Hunt {DEMO_HUNT_ID} ({existing_name!r}) -- left as-is")
    else:
        await conn.execute(
            """
            insert into hunts (id, name, owner_id, settings)
            values ($1, $2, $3, $4::jsonb)
            on conflict (id) do update
                set name = excluded.name, owner_id = excluded.owner_id
            """,
            DEMO_HUNT_ID,
            "Ann Arbor 2026 (demo)",
            owner,
            json.dumps(HUNT_SETTINGS),
        )

    # An adopted Hunt already has an owner, and it is not necessarily the Site
    # Admin running this script.
    hunt_owner = (
        await conn.fetchval("select owner_id from hunts where id = $1", DEMO_HUNT_ID) or owner
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
        hunt_owner,
        OWNER_DEMO_NAME,
    )
    # The upsert above cannot actually set the name, and neither could any
    # upsert: `hunt_members_inherit_default_name` is a BEFORE INSERT trigger
    # that nulls `display_name`/`color` for any user who has a profile, and in
    # `INSERT ... ON CONFLICT DO UPDATE` it fires on the *proposed* row before
    # the conflict is detected -- so `excluded.display_name` is already NULL by
    # the time the update reads it. The override has to be a separate UPDATE,
    # which is what the trigger's own comment prescribes ("only a later explicit
    # UPDATE creates an override"). Without this the public demo publishes the
    # Owner's real account name, which is the exact thing DM-6's privacy pass
    # exists to prevent.
    await conn.execute(
        """
        update hunt_members set display_name = $3, color = 'dusk'
         where hunt_id = $1 and user_id = $2
        """,
        DEMO_HUNT_ID,
        hunt_owner,
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
        # Same BEFORE INSERT trigger, same separate UPDATE (see above).
        await conn.execute(
            """
            update hunt_members set display_name = 'Sam', color = 'moss'
             where hunt_id = $1 and user_id = $2
            """,
            DEMO_HUNT_ID,
            persona,
        )

    # ── The virtual principal ────────────────────────────────────────────────
    for warning in await reconcile_demo_principal(conn, owner):
        print(f"  ! {warning}")

    await conn.execute(
        "update site_settings set demo_hunt_id = $1, updated_by = $2, updated_at = now()",
        DEMO_HUNT_ID,
        owner,
    )

    # ── Rubric ───────────────────────────────────────────────────────────────
    # Rebuilt wholesale: a rubric is a set, and reconciling it row by row would
    # leave criteria somebody removed.
    #
    # But "wholesale" is a `delete`, and an adopted Hunt's Rubric was tuned by a
    # person and is what every existing `scores` row was computed against --
    # replacing it silently invalidates them and makes the scores baked into
    # each Replay Capture disagree with the live Listing a visitor opens after
    # the replay. So an adopted Hunt that already has criteria keeps them, and
    # `--force-rubric` is the explicit way to say otherwise.
    existing_criteria = await conn.fetchval(
        "select count(*) from rubric_criteria where hunt_id = $1", DEMO_HUNT_ID
    )
    if existing_criteria and DEMO_HUNT_ADOPTED and not force_rubric:
        print(
            f"  kept the adopted Hunt's Rubric ({existing_criteria} criteria) -- "
            "pass --force-rubric to replace it with phase0_rubric and rescore."
        )
        await _seed_opinions(conn, owner, persona)
        await _stage_replay_listing(conn)
        return

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
    await _stage_replay_listing(conn)


# The exported capture's `listing.id` is the one Listing the DM-9 replay
# publishes back onto the Overview on "submission" (DESIGN §20 v3.57). It must
# not also be visible on ordinary page load, or the demo would show the same
# Property twice -- once for real, once again when a visitor "adds" it. Hiding
# it costs no new machinery: `useListings` already filters `status = 'active'`
# (`frontend/src/features/listings/api.ts:43`), so `archived` is invisible with
# no demo-specific branch anywhere in the read path, and the replay's own
# `publish()` sets the cached row's status to `active` when it lands
# (`frontend/src/features/demo/replay/replayEngine.ts`).
#
# The demo ships a *slate* of recordings -- `capture.json`, `capture-2.json`,
# and so on -- played one per submission until the visitor exhausts them. This
# glob and its sort must match `useDemoCapture.ts`, which decides play order the
# same way; a mismatch would stage the wrong rows.
_REPLAY_DIR = Path(__file__).resolve().parents[1] / "frontend/src/features/demo/replay"


def _capture_paths() -> list[Path]:
    return sorted(_REPLAY_DIR.glob("capture*.json"))


async def _stage_replay_listing(conn: asyncpg.Connection) -> None:
    paths = _capture_paths()
    if not paths:
        print(
            "  ! no capture*.json yet -- run `manzil export-demo-capture <job_id>` "
            "for each listing that will play back, then re-run this script so "
            "they get hidden until 'submitted'."
        )
        return

    for path in paths:
        capture = json.loads(path.read_text())
        listing_id = UUID(capture["listing"]["id"])

        row = await conn.fetchrow(
            "select hunt_id, status from hunt_listings where id = $1", listing_id
        )
        if row is None:
            print(f"  ! {path.name} names Listing {listing_id}, which no longer exists.")
            continue
        if row["hunt_id"] != DEMO_HUNT_ID:
            print(
                f"  ! {path.name} names Listing {listing_id} in a different Hunt "
                f"({row['hunt_id']}), not the Demo Hunt. Leaving it alone."
            )
            continue

        # Idempotent: re-running with the row already archived is a no-op update,
        # not an error, and re-exporting a different capture re-stages cleanly.
        await conn.execute("update hunt_listings set status = 'archived' where id = $1", listing_id)
        if row["status"] != "archived":
            print(
                f"  staged Listing {listing_id} ({path.name}) as archived -- it "
                "appears only when the demo visitor 'submits' its URL."
            )


async def _seed_opinions(conn: asyncpg.Connection, owner: UUID, persona: UUID | None) -> None:
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
    row = await conn.fetchrow("select demo_enabled, demo_hunt_id from site_settings")
    principal = await conn.fetchval("select user_id from demo_accounts limit 1")
    listings = await conn.fetchval(
        "select count(*) from hunt_listings where hunt_id = $1", DEMO_HUNT_ID
    )
    members = await conn.fetchval(
        "select count(*) from hunt_members where hunt_id = $1", DEMO_HUNT_ID
    )
    blockers = await conn.fetchval("select private.demo_preflight()")
    # One line per recording on the slate: a demo whose fourth capture is still
    # `active` shows that Property twice, and a single aggregate count would
    # hide which one.
    staged: list[tuple[str, str | None]] = []
    for path in _capture_paths():
        capture = json.loads(path.read_text())
        staged.append(
            (
                path.name,
                await conn.fetchval(
                    "select status from hunt_listings where id = $1",
                    UUID(capture["listing"]["id"]),
                ),
            )
        )

    print(f"demo enabled : {row['demo_enabled']}")
    print(f"demo hunt    : {row['demo_hunt_id']}")
    print(f"principal    : {principal}")
    print(f"members      : {members}")
    print(f"listings     : {listings}")
    ready = sum(1 for _, status in staged if status == "archived")
    print(
        f"replay slate : {len(staged)} capture(s), {ready} staged"
        if staged
        else "replay slate : no capture*.json"
    )
    for name, status in staged:
        note = (
            "(ready)"
            if status == "archived"
            else "(!! Listing missing)"
            if status is None
            else "(!! re-run without --status)"
        )
        print(f"  · {name}: status={status} {note}")
    if blockers:
        print("blockers     :")
        for problem in blockers:
            print(f"  - {problem}")
    else:
        print('blockers     : none - `PATCH /v1/admin/demo {"enabled":true}` will succeed')


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--status", action="store_true", help="report configuration, change nothing"
    )
    parser.add_argument(
        "--force-rubric",
        action="store_true",
        help=(
            "replace an adopted Hunt's Rubric with phase0_rubric. Destructive: "
            "every existing score was computed against the Rubric being deleted, "
            "so the Hunt needs a rescore and any Replay Capture needs re-exporting."
        ),
    )
    args = parser.parse_args()

    conn = await asyncpg.connect(_env("DATABASE_URL"))
    try:
        if args.status:
            await _status(conn)
            return

        persona = _ensure_persona(_env("SUPABASE_URL"), _service_key())
        try:
            async with conn.transaction():
                await _seed(conn, persona, force_rubric=args.force_rubric)
        except DemoPrincipalConflict as exc:
            sys.exit(f"{exc}\nRefusing to seed.")
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
