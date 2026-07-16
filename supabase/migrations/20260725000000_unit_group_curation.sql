-- Per-Hunt, per-Unit-Group decision state plus normalized Property locality.
-- A Unit Group remains derived; this table attaches Hunt opinion to its stable key.

alter table properties add column city text;

create table listing_unit_group_states (
    hunt_listing_id uuid not null references hunt_listings(id) on delete cascade,
    unit_group_key text not null,
    interest_status text,
    visited boolean not null default false,
    updated_by uuid not null references auth.users(id),
    updated_at timestamptz not null default now(),
    primary key (hunt_listing_id, unit_group_key),
    constraint listing_unit_group_states_key_format check (
        unit_group_key ~ '^[0-9]+-[0-9]+(\.[0-9]+)?$'
    ),
    constraint listing_unit_group_states_interest_status_check check (
        interest_status is null or interest_status in (
            'interested', 'not_interested', 'applied', 'application_rejected',
            'application_withdrawn', 'offer_received', 'offer_accepted',
            'offer_declined', 'offer_rescinded', 'unavailable'
        )
    )
);

create index listing_unit_group_states_listing_idx
    on listing_unit_group_states (hunt_listing_id);

alter table listing_unit_group_states enable row level security;

create policy listing_unit_group_states_member_select
    on listing_unit_group_states for select to authenticated
    using (
        exists (
            select 1 from hunt_listings hl
            where hl.id = listing_unit_group_states.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );

create policy listing_unit_group_states_curator_insert
    on listing_unit_group_states for insert to authenticated
    with check (
        updated_by = auth.uid()
        and private.listing_has_unit_group(hunt_listing_id, unit_group_key)
        and exists (
            select 1 from hunt_listings hl
            where hl.id = listing_unit_group_states.hunt_listing_id
              and private.member_role(hl.hunt_id) in ('owner', 'curator')
        )
    );

create policy listing_unit_group_states_curator_update
    on listing_unit_group_states for update to authenticated
    using (
        exists (
            select 1 from hunt_listings hl
            where hl.id = listing_unit_group_states.hunt_listing_id
              and private.member_role(hl.hunt_id) in ('owner', 'curator')
        )
    )
    with check (
        updated_by = auth.uid()
        and private.listing_has_unit_group(hunt_listing_id, unit_group_key)
        and exists (
            select 1 from hunt_listings hl
            where hl.id = listing_unit_group_states.hunt_listing_id
              and private.member_role(hl.hunt_id) in ('owner', 'curator')
        )
    );

alter publication supabase_realtime add table listing_unit_group_states;
