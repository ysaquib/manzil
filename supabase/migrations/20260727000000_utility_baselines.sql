-- P3-9 (DESIGN §8.2, §9.5, §20 2026-07-18): utility-baseline vocabulary checks
-- + per-listing all-in composition detail.
--
-- `utility_baselines` itself exists since migration 0001; the scheduled metro
-- job (worker scheduler tick, NOT a jobs row — jobs.hunt_id is NOT NULL and
-- this is global, hunt-less maintenance) starts writing it now, so pin the
-- vocabulary it writes:
--   metro        — properties.city (city-as-metro proxy, v1)
--   beds_bucket  — 0..3, where 3 means "3 or more bedrooms"
--   utility      — 'electric' (base, no heating), 'electric_heat' (winter-
--                  weighted electric INCLUDING electric heating), 'gas_heat'
--                  (winter-weighted heating gas), 'water', 'sewer', 'trash'
alter table utility_baselines
    add constraint utility_baselines_beds_bucket_check
        check (beds_bucket between 0 and 3),
    add constraint utility_baselines_utility_check check (
        utility in ('electric', 'electric_heat', 'gas_heat', 'water', 'sewer', 'trash')
    );

-- Per-listing §9.5 composition detail for the display score's plan: components
-- with actual/estimated/unknown tags + badges ('fees_unverified',
-- 'heat_unknown', 'utilities_not_estimated'). Display metadata ONLY — the
-- pinned scores.breakdown (§9.3) remains the scoring truth; this column exists
-- so the Overview all-in cell and drawer render the estimated portion without
-- reshaping the pinned contract. Written by the ingest projection and rescore
-- in the same transaction as scores.
alter table hunt_listings add column all_in_components jsonb;
