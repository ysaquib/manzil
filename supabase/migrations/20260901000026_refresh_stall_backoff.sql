-- Refresh stall/backoff observability (DESIGN §14, §20 2026-08-25).
--
-- A "stall" is a class-scoped refresh attempt that finished without advancing
-- that class's hunt_listing_refresh_status.last_success_at marker — either a
-- hard job failure, or a job that completed but the class stayed excluded
-- (e.g. an images gallery still short of usable candidates, a reviews/location
-- ENRICH failure). Repeated stalls back off exponentially so the scheduler
-- tick never keeps retrying the same non-result every five minutes, and this
-- table is the durable, queryable record of that backoff so it can surface in
-- the UI and never fail or skip a Listing silently.

create table hunt_listing_refresh_stalls (
    hunt_listing_id uuid not null references hunt_listings (id) on delete cascade,
    refresh_class text not null check (
        refresh_class in ('pricing', 'listing_details', 'images', 'reviews', 'location')
    ),
    consecutive_stalls integer not null default 1 check (consecutive_stalls >= 1),
    last_attempt_at timestamptz not null default now(),
    last_outcome_code text not null,
    last_outcome_detail jsonb not null default '{}'::jsonb,
    next_eligible_at timestamptz not null,
    primary key (hunt_listing_id, refresh_class)
);

create index hunt_listing_refresh_stalls_next_eligible_idx
    on hunt_listing_refresh_stalls (next_eligible_at);

alter table hunt_listing_refresh_stalls enable row level security;

create policy hunt_listing_refresh_stalls_member_select
    on hunt_listing_refresh_stalls for select to authenticated
    using (
        exists (
            select 1
            from hunt_listings hl
            where hl.id = hunt_listing_refresh_stalls.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );

alter publication supabase_realtime add table hunt_listing_refresh_stalls;

-- Worker/service-role only writes, same posture as hunt_listing_refresh_status:
-- the API creates Jobs; it never declares a refresh stalled or recovered.
comment on table hunt_listing_refresh_stalls is
    'Per-Listing/class refresh backoff state (2026-08-25): a row exists only while that class is being withheld by exponential backoff after repeated non-progress; a successful class projection deletes it. Service-role writes only.';
