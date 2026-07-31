-- VC-4 — the Visit defect log (DESIGN v3.30 §8.2, §9.7).
--
-- The point of this table is that it fills itself. The source document has a
-- defect table you are meant to transcribe into after the tour; nobody does
-- that, so marking a Check as a problem promotes into a row here with its unit
-- and originating item already attached (`from_item_key`).

create table visit_defects (
    id                  uuid primary key default gen_random_uuid(),
    visit_id            uuid not null references visits (id) on delete cascade,
    -- Null means the building rather than a unit — an omission would look the
    -- same, so the column is documented rather than inferred.
    visit_unit_id       uuid references visit_units (id) on delete set null,
    -- The Check this was promoted from, when it was promoted rather than typed.
    from_item_key       text check (char_length(from_item_key) between 1 and 120),
    title               text not null check (
        char_length(btrim(title)) between 1 and 300 and title = btrim(title)
    ),
    note                text check (char_length(note) <= 4000),
    -- Nullable on purpose: a promoted defect starts **unrated**. Defaulting it
    -- to a number would invent a judgement nobody made, and "unrated" is a
    -- meaningful state on a tour you are still walking.
    severity            smallint check (severity between 1 and 5),
    promised_in_writing boolean not null default false,
    resolution          text check (char_length(resolution) <= 500),
    created_by          uuid not null references auth.users (id),
    created_at          timestamptz not null default now(),
    -- Soft delete: a defect may have been edited or photographed, so removing it
    -- is a deliberate act that should not be silently undone by a later write.
    deleted_at          timestamptz
);

comment on table visit_defects is
    'Problems found on a Visit (DESIGN §9.7). A Check marked as a problem promotes '
    'into one of these, carrying its unit and from_item_key. Soft-deleted.';

create index visit_defects_visit_idx
    on visit_defects (visit_id, created_at desc) where deleted_at is null;
create index visit_defects_unit_idx
    on visit_defects (visit_unit_id) where visit_unit_id is not null;

-- Promotion is once-only per (visit, item, unit), including rows the member has
-- since deleted: toggling a Check off and on must not resurrect a defect that
-- was deliberately removed, and must never create a second copy. A partial
-- unique index states that rather than leaving it to application care.
create unique index visit_defects_one_per_promoted_check
    on visit_defects (visit_id, from_item_key, coalesce(visit_unit_id, visit_id))
    where from_item_key is not null;

-- A defect's unit must belong to its own Visit — the same cross-scope guard the
-- entries and units tables already carry.
create function private.enforce_visit_defect_shape()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.visit_unit_id is not null and not exists (
        select 1 from public.visit_units u
        where u.id = new.visit_unit_id and u.visit_id = new.visit_id
    ) then
        raise exception 'visit unit % does not belong to visit %', new.visit_unit_id, new.visit_id
            using errcode = '23514';
    end if;
    return new;
end;
$$;

create trigger visit_defects_enforce_shape
    before insert or update on visit_defects
    for each row execute function private.enforce_visit_defect_shape();

alter table visit_defects enable row level security;

create policy visit_defects_member_read
    on visit_defects for select to authenticated
    using (private.member_role(private.visit_hunt_id(visit_id)) is not null);

create policy visit_defects_member_insert
    on visit_defects for insert to authenticated
    with check (
        created_by = auth.uid()
        and private.member_role(private.visit_hunt_id(visit_id)) is not null
    );

-- Any member may edit or remove a defect: on a tour the person holding the
-- phone is often not the person who spotted the problem, and a defect is shared
-- knowledge about the property rather than one member's opinion.
create policy visit_defects_member_update
    on visit_defects for update to authenticated
    using (private.member_role(private.visit_hunt_id(visit_id)) is not null)
    with check (private.member_role(private.visit_hunt_id(visit_id)) is not null);

alter publication supabase_realtime add table visit_defects;
