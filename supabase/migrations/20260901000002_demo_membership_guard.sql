-- Migration: a Demo Account belongs to the Demo Hunt and nowhere else (DM-4,
-- DESIGN §3 / §16 / §20 v3.53).
--
-- The write guard in 20260901000000 keys on `auth.uid()`, which is the identity
-- of whoever's JWT carried the statement. That covers everything a demo browser
-- can send -- including the SECURITY DEFINER RPCs reachable from PostgREST,
-- because SECURITY DEFINER changes the executing *role* and not the request
-- GUCs that auth.uid() reads. Verified: `submit_listing`'s `insert into jobs`
-- is refused 42501 under a demo JWT.
--
-- What it cannot see is the other direction. `accept_hunt_invite`,
-- `join_hunt_invitation_link` and `transfer_hunt_ownership` are executed by the
-- API through the *service-role* client (api/privileged.py), which passes the
-- subject as a parameter. There `auth.uid()` is null, `is_demo_account(null)`
-- is false, and the guard correctly stands aside -- it has no way to know the
-- row being written is about a demo account.
--
-- So guard the subject instead of the session. This is a per-row trigger on
-- hunt_members, and it holds no matter who executes the statement: the API, the
-- worker, the seed script, or a psql session.
--
-- Deliberately *not* done here: prepending an explicit demo check to each of
-- the four money-spending RPCs. Reproducing three SECURITY DEFINER function
-- bodies to add a redundant check is a real risk of transcription error in
-- exchange for no additional coverage, since the statement guard already
-- refuses every write they attempt. If that reasoning ever stops holding --
-- say a stage begins enqueueing through the service role on a user's behalf --
-- the fix belongs here, as another subject guard on `jobs`.

create or replace function private.demo_membership_guard()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_demo_hunt uuid;
begin
    if not private.is_demo_account(new.user_id) then
        return new;
    end if;

    select demo_hunt_id into v_demo_hunt from site_settings;

    -- A Demo Account is a Curator of the Demo Hunt and nothing else (DESIGN §3).
    -- This is the sentence in the glossary, enforced. The path it closes is an
    -- invitation link or email invite: both run service-role, so without this a
    -- demo visitor who got hold of a token could join a real Hunt and read it.
    if v_demo_hunt is null or new.hunt_id is distinct from v_demo_hunt then
        raise exception 'a demo account may only belong to the Demo Hunt'
            using errcode = '42501',
                  detail  = format('attempted membership of hunt %s', new.hunt_id),
                  hint    = 'Set site_settings.demo_hunt_id first, or use a '
                            'non-demo account.';
    end if;

    -- And never as Owner. An Owner can edit the Rubric, manage members, and
    -- archive the Hunt; ownership is also what account deletion blocks on
    -- (§18). A shared public account must not hold any of that, even over the
    -- Demo Hunt itself.
    if new.role = 'owner' then
        raise exception 'a demo account may not own a Hunt'
            using errcode = '42501',
                  hint    = 'The Demo Hunt is owned by the primordial Site Admin.';
    end if;

    return new;
end $$;

drop trigger if exists demo_membership_guard on hunt_members;
create trigger demo_membership_guard
    before insert or update on hunt_members
    for each row execute function private.demo_membership_guard();

comment on function private.demo_membership_guard() is
  'DESIGN §3/§16: enforces that a Demo Account is a Curator of the Demo Hunt '
  'and nothing else. Keys on the row subject rather than auth.uid(), so it '
  'holds for the service-role invite and ownership-transfer RPCs, which the '
  'session-keyed write guard cannot see.';

-- ── Self-check ───────────────────────────────────────────────────────────────
-- Structural only, matching the other guards in this series: assert the trigger
-- is attached to the table it is supposed to protect. Behavioural proof (that a
-- demo account is actually refused a foreign Hunt, and refused ownership of its
-- own) belongs in the adversarial pass, where it can run against a real session
-- instead of a simulated one -- see DM-8.
do $$
begin
    if not exists (
        select 1
          from pg_trigger t
          join pg_class c on c.oid = t.tgrelid
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public'
           and c.relname = 'hunt_members'
           and t.tgname  = 'demo_membership_guard'
           and not t.tgisinternal)
    then
        raise exception 'demo_membership_guard is not attached to hunt_members';
    end if;
end $$;
