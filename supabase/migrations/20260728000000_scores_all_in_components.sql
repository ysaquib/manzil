-- P3-9 follow-up (DESIGN §9.5, §20 2026-07-18): per-plan §9.5 composition
-- detail. The listing-level hunt_listings.all_in_components holds only the
-- display plan's composition, so every unit-group row rendered one plan's
-- rent; the cell/drawer need the composition of the plan they display.
-- Display metadata beside the pinned breakdown — never scoring truth.
alter table scores add column all_in_components jsonb;
