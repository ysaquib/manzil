-- Migration: the Demo Account becomes a virtual principal (C3, DESIGN §20 v3.55).
--
-- Finding C3 in docs/demo-mode-security-impl-analysis.md: a shared GoTrue
-- identity is an account-takeover and denial-of-service primitive, no matter
-- how read-only the database is. Three shapes were tested against the running
-- stack rather than reasoned about, because the answer was not obvious:
--
--   1. A real account + a self-minted, sessionless token.
--      GoTrue accepted it: PUT /auth/v1/user returned 200 and changed the
--      password. Minting alone fixes nothing.
--   2. The same, with the account BANNED (ban_duration far future).
--      Still 200. A ban blocks password sign-in (400 user_banned) and nothing
--      else; GoTrue trusts any validly-signed JWT for /user operations.
--   3. A token whose `sub` has no auth.users row at all.
--      PostgREST: 200, auth.uid() resolves, RLS applies normally.
--      GoTrue:    403 user_not_found on /user, updateUser, logout, and
--                 reauthenticate -- every operation.
--
-- So the demo principal is now a UUID with no account behind it. There is no
-- password to change, no email to rebind, no MFA to enrol, and no session to
-- invalidate, because there is no user. That is a stronger guarantee than any
-- configuration flag, and it does not depend on GoTrue's behaviour staying the
-- same -- there is simply nothing for it to act on.
--
-- The cost is that the principal cannot appear in tables that reference
-- auth.users, hunt_members among them. Its Curator role is therefore
-- synthesised by member_role() rather than stored, which is also why the demo
-- visitor is absent from the member list and from Presence -- correct, since
-- they are not a person in the Hunt.

-- The subject is no longer an account.
alter table demo_accounts drop constraint if exists demo_accounts_user_id_fkey;

comment on table demo_accounts is
  'The virtual principal(s) the public demo runs as. `user_id` is deliberately '
  'NOT a foreign key to auth.users: there is no account, which is what makes '
  'the shared identity impossible to take over or sign out (DESIGN §20 v3.55). '
  'A row here means every statement carrying this subject is refused by '
  'private.demo_write_guard() and scoped by the restrictive read policies.';

comment on column demo_accounts.user_id is
  'A UUID with no auth.users row. The API mints short-lived tokens for it; '
  'GoTrue rejects every operation on it with user_not_found.';

-- ── member_role synthesises the demo role ────────────────────────────────────
-- With no auth.users row the principal cannot hold a hunt_members row, so its
-- Curator role is computed. This keeps the kill switch in exactly the same
-- place as before: no role at all unless the demo is enabled and this is the
-- Demo Hunt, which is what darkens PostgREST and Realtime rather than only the
-- API. can_read_hunt() and can_read_hunt_governance() inherit it.
create or replace function private.member_role(h uuid)
returns hunt_role
language sql
stable
security definer
set search_path = public
as $$
    select coalesce(
        -- Ordinary members. A demo principal never matches, but the guard is
        -- explicit so that marking a real account as demo also revokes it.
        (select hm.role
           from hunt_members hm
          where hm.hunt_id = h
            and hm.user_id = auth.uid()
            and not private.is_demo_account(auth.uid())),
        -- The demo principal: Curator of the Demo Hunt, and only while enabled.
        (select 'curator'::hunt_role
          where private.is_demo_account(auth.uid())
            and coalesce((select s.demo_enabled from site_settings s), false)
            and h = (select s.demo_hunt_id from site_settings s))
    )
$$;

comment on function private.member_role(uuid) is
  'The Hunt role of the calling user, or null. Demo-aware since v3.54 and '
  'demo-synthesising since v3.55: the demo principal has no hunt_members row '
  'because it has no account, and is Curator of the Demo Hunt only while '
  'demo_enabled is true. can_read_hunt() and can_read_hunt_governance() '
  'inherit this, which is what makes the kill switch reach PostgREST and '
  'Realtime rather than only the API.';

-- ── The membership guard refuses every stored membership ─────────────────────
-- Previously it permitted Curator of the Demo Hunt, because that was how the
-- role was held. The role is synthesised now, so a stored row is never correct
-- for a demo principal -- and the FK means one cannot exist for a virtual
-- subject anyway. The guard stays for the case the FK cannot cover: an
-- ordinary account being marked demo, where a stale membership would otherwise
-- survive and grant real access.
create or replace function private.demo_membership_guard()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if not private.is_demo_account(new.user_id) then
        return new;
    end if;

    raise exception 'a demo principal may not hold a stored Hunt membership'
        using errcode = '42501',
              detail  = format('attempted %s of hunt %s', new.role, new.hunt_id),
              hint    = 'The demo Curator role is synthesised by '
                        'private.member_role() and is scoped to the Demo Hunt '
                        'while demo_enabled is true.';
end $$;

-- ── Preflight follows the new shape ──────────────────────────────────────────
create or replace function private.demo_preflight()
returns text[]
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
    v_problems text[] := '{}';
    v_hunt uuid;
    v_demo uuid;
    v_list text;
begin
    select demo_hunt_id into v_hunt from site_settings;
    select user_id into v_demo from demo_accounts limit 1;

    if v_demo is null then
        v_problems := v_problems || 'no demo principal is configured'::text;
    end if;
    if v_hunt is null then
        v_problems := v_problems || 'site_settings.demo_hunt_id is null'::text;
    end if;

    select string_agg(c.relname, ', ' order by c.relname) into v_list
      from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind in ('r', 'p')
       and not exists (select 1 from pg_trigger t
                        where t.tgrelid = c.oid and t.tgname = 'demo_write_guard'
                          and not t.tgisinternal);
    if v_list is not null then
        v_problems := v_problems || ('tables without the write guard: ' || v_list)::text;
    end if;

    select string_agg(c.relname, ', ' order by c.relname) into v_list
      from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind = 'v'
       and (has_table_privilege('authenticated', c.oid, 'INSERT')
         or has_table_privilege('authenticated', c.oid, 'UPDATE')
         or has_table_privilege('authenticated', c.oid, 'DELETE'));
    if v_list is not null then
        v_problems := v_problems || ('views writable by authenticated: ' || v_list)::text;
    end if;

    if has_column_privilege('authenticated', 'public.property_sources',
                            'cleaned_text', 'SELECT') then
        v_problems := v_problems || 'property_sources.cleaned_text is readable'::text;
    end if;

    -- The principal must be virtual. An auth.users row would reintroduce the
    -- whole GoTrue takeover surface this design exists to remove.
    if v_demo is not null and exists (select 1 from auth.users where id = v_demo) then
        v_problems := v_problems
            || 'the demo principal has an auth.users row; it must be virtual'::text;
    end if;

    -- And it must hold no stored membership anywhere.
    if v_demo is not null and exists (select 1 from hunt_members where user_id = v_demo) then
        v_problems := v_problems
            || 'the demo principal holds a stored hunt membership'::text;
    end if;

    if v_hunt is not null and not exists (
        select 1 from hunts h
          join site_admins sa on sa.user_id = h.owner_id and sa.is_primordial
         where h.id = v_hunt)
    then
        v_problems := v_problems
            || 'the Demo Hunt is not owned by the primordial Site Admin'::text;
    end if;

    return v_problems;
end $$;

-- issue_demo_session speaks of "the demo principal" now; its body is unchanged
-- but the comment should not claim an account exists.
comment on function public.issue_demo_session(text, text, integer, integer) is
  'Checks the kill switch and both rate ceilings and records the attempt in one '
  'statement, so racing API instances cannot both pass. Returns the virtual '
  'principal the API should mint a token for. Service-role only.';
