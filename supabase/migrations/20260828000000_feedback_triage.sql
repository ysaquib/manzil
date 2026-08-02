-- Feedback triage state (AD-2, DESIGN §20 v3.41).
--
-- The only schema change the inbox needs. `feedback` already carries everything
-- that makes a two-line report actionable — reporter, route including drawer
-- params, Hunt, build, browser — and has deliberately had no SELECT policy since
-- P3-16, whose migration called this table's eventual reader "the admin view".
-- This is that reader arriving; all it was missing was somewhere to record that
-- a report had been dealt with.
--
-- A column rather than a `feedback_triage` table: there is exactly one state per
-- report and it is owned by whoever is reading the inbox. A side table would buy
-- a history of triage decisions nobody has asked for, at the cost of a join on
-- every list.

alter table feedback add column triage text not null default 'new'
    check (triage in ('new', 'seen', 'actioned', 'wont_fix'));

alter table feedback add column triaged_at timestamptz;
alter table feedback add column triaged_by uuid references auth.users (id) on delete set null;

comment on column feedback.triage is
    'Inbox state (AD-2): new | seen | actioned | wont_fix. Written only through '
    'the service-role admin router — feedback still has no client SELECT policy.';

-- The inbox opens on "new, newest first", which is the read this serves. The
-- P3-16 (user_id, created_at) index still serves the rate-limit trigger.
create index feedback_triage_created_idx on feedback (triage, created_at desc);

-- No new policies. `feedback` keeps its single insert-only policy for
-- authenticated callers: a submitter still cannot read their own report, let
-- alone anyone else's, and triage is not something a client may set.
