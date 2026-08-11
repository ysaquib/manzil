-- Migration: a member may end their own membership (DESIGN §4.2, §9.1, §20 v3.76).
--
-- Until now the only exit from a Hunt was the Owner removing you:
-- `hunt_members_owner_delete_others` was the sole DELETE policy on the table and
-- it requires the caller to *be* the Owner. A Curator or Member who no longer
-- wanted the Hunt had no way out of it at all.
--
-- Two rules bound the new policy, and both are facts about the Hunt rather than
-- about the caller:
--
--   1. **The Owner may not leave.** A Hunt has exactly one Owner ([§9.1]) and
--      an Owner walking out would leave it with none — no rubric editor, no
--      member management, nobody who can archive it. Ownership transfers first;
--      afterwards the ex-Owner is a Curator and the ordinary rule applies.
--   2. **The last member may not leave.** A Hunt nobody belongs to is
--      unreachable for everyone including the person who just left, and its
--      rows are visible to no one. Archiving is the action for "I am done with
--      this Hunt", and it keeps the data readable.
--
-- Rule 1 implies rule 2 as the schema stands — the last member is necessarily
-- the Owner, since the Owner row cannot be deleted and every Hunt is created
-- with one. The count is still stated, because a policy whose correctness rests
-- on an invariant maintained three migrations away is a boundary that rots
-- quietly. It reads through a SECURITY DEFINER helper: a plain subquery over
-- `hunt_members` inside a `hunt_members` policy re-enters policy evaluation,
-- which is exactly the recursion `private.member_role` exists to avoid.
--
-- Not added here: anything to stop a Demo Account leaving the Demo Hunt. The
-- statement-level `demo_write_guard` from 20260901000000 already covers DELETE
-- on every table in `public`, so a demo session is refused before RLS is
-- consulted.

create or replace function private.hunt_member_count(h uuid)
returns integer
language sql
stable
security definer
set search_path = public
as $$
    select count(*)::integer from hunt_members where hunt_id = h
$$;

revoke all on function private.hunt_member_count(uuid) from public, anon;
grant execute on function private.hunt_member_count(uuid) to authenticated;

comment on function private.hunt_member_count(uuid) is
  'Members of a Hunt, counted with RLS bypassed so a hunt_members policy can '
  'read it without re-entering policy evaluation. Used by '
  'hunt_members_self_leave_delete to keep the last member from leaving.';

-- Dropped first so the file is re-runnable. This migration was renamed
-- (20260901000016 → ...018) to repair an ordering collision *after* the
-- original had already been applied to production, so `supabase db push` saw a
-- new version and replayed DDL the database already had: the deploy failed on
-- `policy ... already exists (42710)`. A rename is a normal way to resolve a
-- collision between branches, and every statement here is `create or replace`
-- except this one — which is the only reason the replay was not a no-op.
drop policy if exists hunt_members_self_leave_delete on hunt_members;

create policy hunt_members_self_leave_delete
    on hunt_members for delete to authenticated
    using (
        user_id = auth.uid()
        and role <> 'owner'
        and private.hunt_member_count(hunt_id) > 1
    );

-- ── Self-check ───────────────────────────────────────────────────────────────
-- Structural, in the style of the other guards in this series: assert the
-- policy landed on the table it is meant to govern. The behavioural proof — a
-- Curator leaving, an Owner refused, a lone member refused — lives in
-- `api/tests/test_rls_matrix.py`, where it runs against real sessions.
do $$
begin
    if not exists (
        select 1
          from pg_policies
         where schemaname = 'public'
           and tablename  = 'hunt_members'
           and policyname = 'hunt_members_self_leave_delete')
    then
        raise exception 'hunt_members_self_leave_delete is not attached to hunt_members';
    end if;
end $$;
