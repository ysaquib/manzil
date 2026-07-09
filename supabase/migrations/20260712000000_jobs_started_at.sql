-- Migration 0006: jobs.started_at (DESIGN §8.2, §20 2026-07-09).
-- Operational metrics column. Splits a job's wall-clock into two spans:
--   queue-wait  = created_at → started_at   (how long it sat queued)
--   run-time    = started_at → finished_at  (how long it actually ran)
-- Stamped on the FIRST claim only (`claim_next_job` sets it via
-- coalesce(started_at, now())), so a reclaim/resume after an orphan never resets
-- it. Nullable is correct: null while queued, before any worker has claimed it.
-- Deliberately NOT surfaced on JobResponse/OpenAPI/frontend — ops-only, not UX.
alter table jobs add column started_at timestamptz;
