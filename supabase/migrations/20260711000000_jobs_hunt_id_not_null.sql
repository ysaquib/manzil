-- Migration 0005: jobs.hunt_id NOT NULL (DESIGN §20, 2026-07-09).
-- Reverses 0004's deferral ("NOT NULL rides with P2-1"): both enqueue paths already
-- set hunt_id, 0004 backfills legacy rows, and no live databases exist — the
-- constraint IS the enforcement, so waiting on P2-1 RLS only left a window for a
-- future job creator to silently omit it.
alter table jobs alter column hunt_id set not null;
