-- Hunt-wide shared Overview filters (DESIGN §13.2, §20 2026-07-19).
-- View state, deliberately outside the pinned hunts.settings contract:
-- Owner/Curator publish a filter set that seeds every member's Overview on
-- open; members deviate locally without touching this row.

create table hunt_shared_filters (
    hunt_id uuid primary key references hunts(id) on delete cascade,
    filters jsonb not null,
    updated_by uuid not null references auth.users(id),
    updated_at timestamptz not null default now()
);

alter table hunt_shared_filters enable row level security;

create policy hunt_shared_filters_member_select
    on hunt_shared_filters for select to authenticated
    using (private.member_role(hunt_id) is not null);

create policy hunt_shared_filters_curator_insert
    on hunt_shared_filters for insert to authenticated
    with check (
        updated_by = auth.uid()
        and private.member_role(hunt_id) in ('owner', 'curator')
    );

create policy hunt_shared_filters_curator_update
    on hunt_shared_filters for update to authenticated
    using (private.member_role(hunt_id) in ('owner', 'curator'))
    with check (
        updated_by = auth.uid()
        and private.member_role(hunt_id) in ('owner', 'curator')
    );

create policy hunt_shared_filters_curator_delete
    on hunt_shared_filters for delete to authenticated
    using (private.member_role(hunt_id) in ('owner', 'curator'));
