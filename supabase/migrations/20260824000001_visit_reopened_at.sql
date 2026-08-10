-- VC-9 — reopening a Visit is its own event (DESIGN §9.7, §20).
--
-- Until now `reopen` set `ended_at` to null. That made the derived state right
-- and the record wrong: the tour's end time is a fact about a real afternoon,
-- and it was being destroyed to record that somebody came back to the notes on
-- Friday. Two different events were sharing one column.
--
-- `reopened_at` holds **only the most recent** reopen. There is no history here
-- on purpose: the useful question after a tour is "has this been revisited
-- since it ended", and every actual edit is already attributable and timestamped
-- because `visit_entries` is append-only. A reopen log would duplicate that at
-- one row per curiosity.
--
-- State stays derived (DESIGN §9.7 — there is no status column and this does not
-- add one):
--
--     cancelled_at is not null                                  -> cancelled
--     ended_at is not null and (reopened_at is null
--                               or reopened_at <= ended_at)     -> completed
--     started_at is not null                                    -> in progress
--     otherwise                                                 -> planned
--
-- Ending a reopened Visit stamps a *new* `ended_at` later than `reopened_at`,
-- which lands back on completed without clearing the reopen stamp. That is why
-- there is no `reopened_at >= ended_at` constraint: after the second end, the
-- reopen legitimately sits before the end it preceded.

alter table visits
    add column reopened_at timestamptz;

comment on column visits.reopened_at is
    'When this Visit was most recently reopened after ending (VC-9). Only the '
    'latest reopen is kept; a further reopen replaces it. Never clears ended_at.';

-- You cannot reopen a tour that never ended, and you cannot have reopened it
-- before it began. Both are statements about one row, so they belong here rather
-- than in application care.
alter table visits
    add constraint visits_reopen_requires_end
        check (reopened_at is null or ended_at is not null),
    add constraint visits_reopen_after_start
        check (reopened_at is null or started_at is null or reopened_at >= started_at);

-- Deliberately *not* constrained: a cancelled Visit may carry a reopen stamp.
-- Cancellation already outranks every other state in the derivation above, and
-- a constraint forbidding the combination would make cancelling a reopened tour
-- fail with a check violation — turning a cosmetic tidiness preference into a
-- refused action on a surface where cancelling is the honest thing to do.
