-- Migration 0004: schema-alignment batch (DESIGN §20, 2026-07-09).
-- Three changes from the schema review:
--   (A) jobs.hunt_id           — direct hunt scoping for the Tasks query + P2-1 RLS.
--   (B) hunt_listings.unavailable_at — first-class "no available floor plans" state
--       (dimmed row, null score), distinct from an error.
--   (C) floor_plans natural unique key — idempotent upsert across refreshes so a plan
--       keeps a stable id (scores/pins stay attached).

-- (A) jobs.hunt_id ----------------------------------------------------------------
-- Every job belongs to a hunt. Listing-scoped jobs (ingest/refresh/investigate) reach
-- it via hunt_listing_id; hunt-level jobs (rescore) carry it in the payload. A first
-- class column collapses both into one indexed predicate and de-risks P2-1 RLS.
-- Left nullable in Phase 1: the app always sets it (both enqueue paths), and
-- `list_jobs`/`_assert_job_owner` treat a null hunt_id as "no hunt association".
-- Tightening to NOT NULL rides with P2-1 RLS, once every job creator is enforced.
alter table jobs add column hunt_id uuid references hunts (id) on delete cascade;

update jobs j set hunt_id = hl.hunt_id
    from hunt_listings hl
    where j.hunt_listing_id = hl.id and j.hunt_id is null;
update jobs set hunt_id = (payload ->> 'hunt_id')::uuid
    where hunt_id is null and payload ? 'hunt_id';

create index jobs_hunt_id_idx on jobs (hunt_id);

-- (B) hunt_listings.unavailable_at ------------------------------------------------
-- Set to now() when an ingest/refresh completes with zero scorable floor plans — a
-- legitimate "no availability" result, NOT an error (§8.2). Cleared to null when plans
-- are found, so the state reverses on refresh. Null while pending or scored.
alter table hunt_listings add column unavailable_at timestamptz;

-- (C) floor_plans natural unique key ----------------------------------------------
-- One plan per (source, name, beds, baths). Lets the worker upsert on refresh instead
-- of inserting duplicate rows with new ids that orphan `scores` and dangle
-- `hunt_listings.pins` (which reference floor_plan_id).
alter table floor_plans
    add constraint floor_plans_source_plan_key unique (source_id, plan_name, beds, baths);
