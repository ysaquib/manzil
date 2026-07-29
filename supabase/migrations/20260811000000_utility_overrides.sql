-- Per-Listing, per-utility human corrections (§9.5).  Unlike the extracted
-- utilities_included list, each decision is independently revertible.
-- `included` and `monthly_amount` form one editable utility decision; both
-- NULL is the append-only revert tombstone.
create table utility_overrides (
    id              uuid primary key default gen_random_uuid(),
    hunt_listing_id uuid not null references hunt_listings (id) on delete cascade,
    utility         text not null check (utility in ('electric', 'gas', 'water', 'sewer', 'cooling', 'heat', 'trash')),
    included        boolean,
    monthly_amount  numeric(10, 2) check (monthly_amount is null or monthly_amount >= 0),
    user_id         uuid not null,
    note            text,
    created_at      timestamptz not null default clock_timestamp()
);
create index utility_overrides_current_idx
    on utility_overrides (hunt_listing_id, utility, created_at desc, id desc);

create view current_utility_overrides
with (security_invoker = true)
as
select distinct on (hunt_listing_id, utility) *
from utility_overrides
order by hunt_listing_id, utility, created_at desc, id desc;

alter table utility_overrides enable row level security;
create policy utility_overrides_member_select
    on utility_overrides for select to authenticated
    using (
        exists (
            select 1 from hunt_listings hl
            where hl.id = utility_overrides.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );
create policy utility_overrides_curator_insert
    on utility_overrides for insert to authenticated
    with check (
        user_id = auth.uid()
        and exists (
            select 1 from hunt_listings hl
            where hl.id = utility_overrides.hunt_listing_id
              and private.member_role(hl.hunt_id) in ('owner', 'curator')
        )
    );
create policy utility_overrides_member_insert_own
    on utility_overrides for insert to authenticated
    with check (
        user_id = auth.uid()
        and exists (
            select 1 from hunt_listings hl
            where hl.id = utility_overrides.hunt_listing_id
              and private.member_role(hl.hunt_id) = 'member'
              and hl.added_by = auth.uid()
        )
    );

grant select on current_utility_overrides to authenticated;
