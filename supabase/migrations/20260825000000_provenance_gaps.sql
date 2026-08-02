-- Provenance gaps (AD-G, DESIGN §20 v3.38).
--
-- Manzil already keeps most of its history where it belongs: `overrides` is
-- append-only with an author, `visit_entries` never overwrite, extraction facts
-- carry candidate/resolved lineage, and `job_events` narrates the pipeline. Four
-- places did not, and this migration closes them **in the domain** rather than
-- in a generic audit table — one source of truth per fact, so nothing can
-- disagree with anything.
--
-- 1. `fee_checklist` was upserted in place, so a fee's previous amount and the
--    person who set it were destroyed on every edit. Fees feed all-in cost and
--    therefore the score, which makes this a correctness gap, not a nice-to-have.
-- 2. `hunt_members.role` was overwrite-only: no record of who promoted or
--    demoted whom.
-- 3. `hunt_listings.status` / `source_policy` / `pins` were overwrite-only.
-- 4. Deleting anything left no trace that it had ever existed.
--
-- Captured by TRIGGER, not by the writers. The API, the worker and a direct
-- PostgREST call all mutate these tables; a trigger is the only place that sees
-- every one of them, and it cannot be forgotten by a future writer.
--
-- `auth.uid()` is null on the worker's direct pool connection (no JWT). A null
-- actor therefore reads as "the system did this", which is true and is better
-- than attributing a pipeline write to a person.

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Fee value history
-- ─────────────────────────────────────────────────────────────────────────────
-- Append-only stream of what the fee BECAME, mirroring `overrides` rather than
-- storing superseded rows: current value is the latest row, which is the shape
-- the codebase already reads elsewhere.
create table fee_checklist_history (
    id              uuid primary key default gen_random_uuid(),
    hunt_listing_id uuid not null references hunt_listings (id) on delete cascade,
    fee_slot        text not null,
    amount          numeric(10, 2),
    value_state     value_state not null,
    counted         boolean,
    required        boolean,
    refundable      boolean,
    credited_amount numeric(10, 2),
    evidence_ref    text,
    -- The fee row's own `entered_by` when the API set one, else the JWT subject.
    entered_by      uuid,
    recorded_at     timestamptz not null default now()
);
comment on table fee_checklist_history is
    'Append-only history of fee_checklist values (AD-G). Latest row per '
    '(hunt_listing_id, fee_slot) equals the live row; earlier rows are what it was.';

create index fee_checklist_history_slot_idx
    on fee_checklist_history (hunt_listing_id, fee_slot, recorded_at desc);

create or replace function private.record_fee_checklist_history()
returns trigger language plpgsql security definer set search_path = public
as $$
begin
    -- Skip no-op upserts: the fee writer touches `updated_at` on every save, and
    -- a history of "unchanged" entries would bury the edits that matter.
    if tg_op = 'UPDATE'
       and old.amount is not distinct from new.amount
       and old.value_state is not distinct from new.value_state
       and old.counted is not distinct from new.counted
       and old.required is not distinct from new.required
       and old.refundable is not distinct from new.refundable
       and old.credited_amount is not distinct from new.credited_amount
       and old.evidence_ref is not distinct from new.evidence_ref
    then
        return null;
    end if;

    insert into fee_checklist_history (
        hunt_listing_id, fee_slot, amount, value_state,
        counted, required, refundable, credited_amount, evidence_ref, entered_by
    )
    values (
        new.hunt_listing_id, new.fee_slot, new.amount, new.value_state,
        new.counted, new.required, new.refundable, new.credited_amount,
        new.evidence_ref, coalesce(new.entered_by, auth.uid())
    );
    return null;
end;
$$;

create trigger fee_checklist_history_capture
after insert or update on fee_checklist
for each row execute function private.record_fee_checklist_history();

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Membership history
-- ─────────────────────────────────────────────────────────────────────────────
create table hunt_member_history (
    id          uuid primary key default gen_random_uuid(),
    hunt_id     uuid not null references hunts (id) on delete cascade,
    user_id     uuid not null,
    -- Null role means the membership ended.
    role        hunt_role,
    action      text not null check (action in ('joined', 'role_changed', 'left')),
    -- Who performed it. Null for a system/worker write; equal to `user_id` when
    -- somebody joined via their own invite acceptance.
    actor_id    uuid,
    recorded_at timestamptz not null default now()
);
comment on table hunt_member_history is
    'Append-only membership timeline (AD-G): joins, role changes and removals, '
    'with the actor who caused them.';

create index hunt_member_history_hunt_idx on hunt_member_history (hunt_id, recorded_at desc);

create or replace function private.record_hunt_member_history()
returns trigger language plpgsql security definer set search_path = public
as $$
declare
    v_hunt_id uuid := coalesce(new.hunt_id, old.hunt_id);
begin
    -- A membership row also disappears when its Hunt is deleted. In that
    -- cascade the parent is already gone, so writing history here would both
    -- violate the FK and record N meaningless "left" rows for one deletion —
    -- the Hunt's tombstone is the honest record of that event.
    if not exists (select 1 from hunts where id = v_hunt_id) then
        return null;
    end if;

    if tg_op = 'INSERT' then
        insert into hunt_member_history (hunt_id, user_id, role, action, actor_id)
        values (new.hunt_id, new.user_id, new.role, 'joined', auth.uid());
    elsif tg_op = 'UPDATE' then
        if old.role is not distinct from new.role then
            return null;  -- a display-name or colour edit is not a role change
        end if;
        insert into hunt_member_history (hunt_id, user_id, role, action, actor_id)
        values (new.hunt_id, new.user_id, new.role, 'role_changed', auth.uid());
    else
        insert into hunt_member_history (hunt_id, user_id, role, action, actor_id)
        values (old.hunt_id, old.user_id, null, 'left', auth.uid());
    end if;
    return null;
end;
$$;

create trigger hunt_member_history_capture
after insert or update or delete on hunt_members
for each row execute function private.record_hunt_member_history();

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Listing curation history
-- ─────────────────────────────────────────────────────────────────────────────
-- `hunt_listings` already records who ADDED a Listing (`added_by`, `created_at`);
-- what it lost was every change afterwards.
create table hunt_listing_history (
    id              uuid primary key default gen_random_uuid(),
    hunt_listing_id uuid not null references hunt_listings (id) on delete cascade,
    status          text not null,
    source_policy   text not null,
    pins            jsonb not null default '{}',
    actor_id        uuid,
    recorded_at     timestamptz not null default now()
);
comment on table hunt_listing_history is
    'Append-only history of a Listing''s curation state (AD-G): archive/restore, '
    'Source Policy changes and pin edits. Insertion is already covered by '
    'hunt_listings.added_by/created_at, so only changes are recorded.';

create index hunt_listing_history_listing_idx
    on hunt_listing_history (hunt_listing_id, recorded_at desc);

create or replace function private.record_hunt_listing_history()
returns trigger language plpgsql security definer set search_path = public
as $$
begin
    if old.status is not distinct from new.status
       and old.source_policy is not distinct from new.source_policy
       and old.pins is not distinct from new.pins
    then
        return null;
    end if;

    insert into hunt_listing_history (
        hunt_listing_id, status, source_policy, pins, actor_id
    )
    values (new.id, new.status, new.source_policy, new.pins, auth.uid());
    return null;
end;
$$;

create trigger hunt_listing_history_capture
after update on hunt_listings
for each row execute function private.record_hunt_listing_history();

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Tombstones
-- ─────────────────────────────────────────────────────────────────────────────
-- Deliberately carries NO foreign keys. A tombstone whose FK cascades away with
-- the thing it commemorates is not a tombstone; `hunt_id` and `entity_id` are
-- plain uuids so the record outlives everything it refers to.
create table deletion_tombstones (
    id          uuid primary key default gen_random_uuid(),
    entity_type text not null check (entity_type in ('hunt', 'hunt_listing', 'hunt_member')),
    entity_id   uuid not null,
    hunt_id     uuid,
    -- What it was called while it existed — an id alone tells a reader nothing.
    label       text,
    -- True when this row died because its parent did. Lets a reader collapse one
    -- Hunt deletion and its 200 Listings into a single line.
    via_cascade boolean not null default false,
    detail      jsonb not null default '{}',
    deleted_by  uuid,
    deleted_at  timestamptz not null default now()
);
comment on table deletion_tombstones is
    'What used to exist (AD-G). No foreign keys by design: a tombstone that '
    'cascades away with its subject records nothing.';

create index deletion_tombstones_hunt_idx on deletion_tombstones (hunt_id, deleted_at desc);

create or replace function private.record_hunt_tombstone()
returns trigger language plpgsql security definer set search_path = public
as $$
begin
    insert into deletion_tombstones (entity_type, entity_id, hunt_id, label, deleted_by, detail)
    values ('hunt', old.id, old.id, old.name, auth.uid(),
            jsonb_build_object('owner_id', old.owner_id));
    return old;
end;
$$;

create trigger hunts_tombstone
before delete on hunts
for each row execute function private.record_hunt_tombstone();

create or replace function private.record_hunt_listing_tombstone()
returns trigger language plpgsql security definer set search_path = public
as $$
declare
    v_cascade boolean := not exists (select 1 from hunts where id = old.hunt_id);
begin
    insert into deletion_tombstones (
        entity_type, entity_id, hunt_id, label, via_cascade, deleted_by, detail
    )
    values (
        'hunt_listing', old.id, old.hunt_id,
        (select name from properties where id = old.property_id),
        v_cascade, auth.uid(),
        jsonb_build_object('property_id', old.property_id, 'status', old.status)
    );
    return old;
end;
$$;

create trigger hunt_listings_tombstone
before delete on hunt_listings
for each row execute function private.record_hunt_listing_tombstone();

create or replace function private.record_hunt_member_tombstone()
returns trigger language plpgsql security definer set search_path = public
as $$
declare
    v_cascade boolean := not exists (select 1 from hunts where id = old.hunt_id);
begin
    insert into deletion_tombstones (
        entity_type, entity_id, hunt_id, label, via_cascade, deleted_by, detail
    )
    values (
        'hunt_member', old.user_id, old.hunt_id,
        (select default_display_name from user_profiles where user_id = old.user_id),
        v_cascade, auth.uid(),
        jsonb_build_object('role', old.role)
    );
    return old;
end;
$$;

create trigger hunt_members_tombstone
before delete on hunt_members
for each row execute function private.record_hunt_member_tombstone();

-- ─────────────────────────────────────────────────────────────────────────────
-- RLS
-- ─────────────────────────────────────────────────────────────────────────────
-- The line drawn here: **data provenance is shared, governance history is the
-- Owner's**. Any member may ask who set a fee to zero — it is their shared
-- Listing and it moves their score. Who demoted whom, and what was deleted, are
-- decisions about the Hunt rather than facts about a Property, and they belong
-- to the Owner (and, from AD-1, a site admin).
--
-- No client write policy on any of these: every row is written by a trigger
-- running SECURITY DEFINER. A history row a member could forge is worthless.
alter table fee_checklist_history enable row level security;
alter table hunt_member_history enable row level security;
alter table hunt_listing_history enable row level security;
alter table deletion_tombstones enable row level security;

create policy fee_checklist_history_member_select
    on fee_checklist_history for select to authenticated
    using (
        exists (
            select 1 from hunt_listings hl
            where hl.id = fee_checklist_history.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );

create policy hunt_listing_history_member_select
    on hunt_listing_history for select to authenticated
    using (
        exists (
            select 1 from hunt_listings hl
            where hl.id = hunt_listing_history.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );

create policy hunt_member_history_owner_select
    on hunt_member_history for select to authenticated
    using (private.member_role(hunt_id) = 'owner');

create policy deletion_tombstones_owner_select
    on deletion_tombstones for select to authenticated
    using (hunt_id is not null and private.member_role(hunt_id) = 'owner');
