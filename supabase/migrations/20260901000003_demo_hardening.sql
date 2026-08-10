-- Migration: Demo Mode hardening (DESIGN §16 / §20 v3.54).
--
-- Answers the findings in docs/demo-mode-security-impl-analysis.md. The three
-- release-blocking ones in this file are C1 (the kill switch reached only the
-- global fact tables), C2 (private Storage was readable bucket-wide and ignored
-- Property scoping), and H1 (DESIGN promised explicit guards inside the
-- money-spending RPCs and the code did not have them).

-- ── C1: the kill switch must reach Hunt-scoped data ──────────────────────────
-- The original scoping (20260901000001) applied only to the eight global fact
-- tables. Everything Hunt-scoped -- hunts, hunt_listings, jobs, job_events,
-- scores, comments, ratings, overrides, fees, every visit_* table and the views
-- over them -- authorizes through private.member_role(), which knew nothing
-- about demo_enabled. So flipping the switch off left a live token reading the
-- whole Demo Hunt, and DESIGN §16's claim that disabling "darkens PostgREST and
-- Realtime" was false.
--
-- Fixed at the one place every Hunt-scoped policy already funnels through
-- rather than by adding restrictive policies to forty tables: private.
-- can_read_hunt() and can_read_hunt_governance() are both defined in terms of
-- member_role(), so all three become demo-aware together, for reads and writes,
-- including any table added later. A demo account whose switch is off now has
-- no role anywhere, which is exactly the intent -- it is not a member of
-- anything until the demo is on.
--
-- The `not is_demo_account(...)` disjunct is evaluated first and is a cheap
-- STABLE call, so a real member's plans are unchanged.
create or replace function private.member_role(h uuid)
returns hunt_role
language sql
stable
security definer
set search_path = public
as $$
    select hm.role
      from hunt_members hm
     where hm.hunt_id = h
       and hm.user_id = auth.uid()
       and (
           not private.is_demo_account(auth.uid())
           or (
               coalesce((select s.demo_enabled from site_settings s), false)
               and h = (select s.demo_hunt_id from site_settings s)
           )
       )
$$;

comment on function private.member_role(uuid) is
  'The Hunt role of the calling user, or null. Demo-aware since v3.54: a Demo '
  'Account has no role at all unless demo_enabled is true and this is the Demo '
  'Hunt, which is what makes the kill switch reach PostgREST and Realtime '
  'rather than only the API. can_read_hunt() and can_read_hunt_governance() '
  'inherit this.';

-- ── C2: private Storage must respect Property scoping ────────────────────────
-- `property-images` is a private bucket, but its SELECT policy authorized every
-- authenticated user for every object in it. The original comment ("Table RLS
-- decides which image paths the UI learns") shows the reasoning: path secrecy.
-- That holds only while every account belongs to someone trusted -- a shared
-- public account can simply list the bucket.
--
-- Object keys are `properties/<property_id>/<content_hash>.webp`, so the object
-- maps back to a Property and can take the same predicate the metadata table
-- uses.
create or replace function private.demo_readable_storage_object(object_name text)
returns boolean
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
    v_property uuid;
begin
    -- Real members keep the existing global-fact posture: Properties and their
    -- images are deliberately shared across Hunts (DESIGN §8.3). This narrows
    -- the demo account only.
    if not private.is_demo_account(auth.uid()) then
        return true;
    end if;

    begin
        v_property := (storage.foldername(object_name))[2]::uuid;
    exception when others then
        return false;  -- unparseable key: fail closed
    end;

    if v_property is null then
        return false;
    end if;

    return private.demo_readable_property(v_property);
end $$;

revoke all on function private.demo_readable_storage_object(text) from public, anon;
grant execute on function private.demo_readable_storage_object(text) to authenticated;

drop policy if exists property_images_storage_authenticated_select on storage.objects;
create policy property_images_storage_authenticated_select
    on storage.objects for select to authenticated
    using (
        bucket_id = 'property-images'
        and private.demo_readable_storage_object(name)
    );

-- ── M1: Curator, exactly ─────────────────────────────────────────────────────
-- The first version refused `owner` but accepted `member`, while DESIGN §3 says
-- Curator and nothing else. The difference is not cosmetic: permission-derived
-- UI reads the role, so a demo account silently holding `member` would show a
-- different app than the one the demo is meant to show.
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

    if v_demo_hunt is null or new.hunt_id is distinct from v_demo_hunt then
        raise exception 'a demo account may only belong to the Demo Hunt'
            using errcode = '42501',
                  detail  = format('attempted membership of hunt %s', new.hunt_id),
                  hint    = 'Set site_settings.demo_hunt_id first, or use a '
                            'non-demo account.';
    end if;

    if new.role is distinct from 'curator'::hunt_role then
        raise exception 'a demo account must hold exactly the Curator role'
            using errcode = '42501',
                  detail  = format('attempted role %s', new.role),
                  hint    = 'DESIGN §3: a Demo Account is a Curator of the Demo '
                            'Hunt and nothing else.';
    end if;

    return new;
end $$;

-- ── M3: the singleton is a constraint, not a comment ─────────────────────────
-- The table said "expected cardinality is one" and permitted many. A second
-- demo identity would make the reconciler, the session endpoint and the
-- preflight all quietly wrong.
create unique index if not exists demo_accounts_singleton_idx
    on demo_accounts ((true));

comment on index demo_accounts_singleton_idx is
  'Exactly one Demo Account may exist. Enforced rather than assumed: the '
  'session endpoint, the reconciler and demo_preflight() all speak of "the" '
  'demo account.';

-- ── M4: the settings row cannot describe an impossible demo ──────────────────
alter table site_settings
    drop constraint if exists site_settings_enabled_needs_hunt;
alter table site_settings
    add constraint site_settings_enabled_needs_hunt
    check (not demo_enabled or demo_hunt_id is not null);

-- ── H3: guard attachment is reusable, and enabling runs a preflight ──────────
-- The attachment loop in 20260901000000 covers tables existing at that point in
-- history. A later migration can still create an unguarded table; the test
-- suite catches it, but CI detection is not a database invariant and a
-- deployment that skips tests would carry a live bypass.
--
-- Two additions: a helper each new table-creating migration can call, and a
-- preflight the enable path runs inside its own transaction, so demo mode
-- cannot be switched on while a bypass exists.
create or replace function private.attach_demo_guards(t regclass)
returns void
language plpgsql
as $$
begin
    execute format(
        'create or replace trigger demo_write_guard '
        'before insert or update or delete on %s '
        'for each statement execute function private.demo_write_guard()', t);
    execute format(
        'create or replace trigger demo_truncate_guard '
        'before truncate on %s '
        'for each statement execute function private.demo_write_guard()', t);
end $$;

comment on function private.attach_demo_guards(regclass) is
  'Call this from any migration that creates a table in public. The final-'
  'schema test in api/tests/test_demo_guard.py fails when it is forgotten.';

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
        v_problems := v_problems || 'no demo account is configured'::text;
    end if;
    if v_hunt is null then
        v_problems := v_problems || 'site_settings.demo_hunt_id is null'::text;
    end if;

    -- Every base table guarded.
    select string_agg(c.relname, ', ' order by c.relname) into v_list
      from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind in ('r', 'p')
       and not exists (select 1 from pg_trigger t
                        where t.tgrelid = c.oid and t.tgname = 'demo_write_guard'
                          and not t.tgisinternal);
    if v_list is not null then
        v_problems := v_problems || ('tables without the write guard: ' || v_list)::text;
    end if;

    -- No writable view.
    select string_agg(c.relname, ', ' order by c.relname) into v_list
      from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind = 'v'
       and (has_table_privilege('authenticated', c.oid, 'INSERT')
         or has_table_privilege('authenticated', c.oid, 'UPDATE')
         or has_table_privilege('authenticated', c.oid, 'DELETE'));
    if v_list is not null then
        v_problems := v_problems || ('views writable by authenticated: ' || v_list)::text;
    end if;

    -- cleaned_text still withheld.
    if has_column_privilege('authenticated', 'public.property_sources',
                            'cleaned_text', 'SELECT') then
        v_problems := v_problems || 'property_sources.cleaned_text is readable'::text;
    end if;

    -- The demo account is a Curator of the Demo Hunt and nothing else.
    if v_demo is not null then
        if exists (select 1 from hunt_members
                    where user_id = v_demo
                      and (hunt_id is distinct from v_hunt or role <> 'curator'))
        then
            v_problems := v_problems
                || 'the demo account holds a membership that is not Curator of the Demo Hunt'::text;
        end if;
        if v_hunt is not null and not exists (
            select 1 from hunt_members
             where user_id = v_demo and hunt_id = v_hunt and role = 'curator')
        then
            v_problems := v_problems
                || 'the demo account is not a Curator of the Demo Hunt'::text;
        end if;
    end if;

    -- The Demo Hunt is owned by the primordial Site Admin (DESIGN §3).
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

comment on function private.demo_preflight() is
  'Returns the reasons demo mode must not be enabled, empty when it may be. '
  'public.set_demo_enabled(true) refuses on a non-empty result.';

-- The only supported way to turn the demo on. Service-role only: the API calls
-- it from the audited admin route, which is also where the Admin Audit Log
-- entry is written.
create or replace function public.set_demo_enabled(p_enabled boolean, p_actor uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_problems text[];
begin
    if p_enabled then
        v_problems := private.demo_preflight();
        if array_length(v_problems, 1) > 0 then
            raise exception 'demo mode preflight failed'
                using errcode = '42501',
                      detail  = array_to_string(v_problems, '; ');
        end if;
    end if;

    update site_settings
       set demo_enabled = p_enabled,
           updated_by   = p_actor,
           updated_at   = now();

    return jsonb_build_object('demo_enabled', p_enabled);
end $$;

revoke all on function public.set_demo_enabled(boolean, uuid) from public, anon, authenticated;

-- ── M2: narrow the demo metadata surface ─────────────────────────────────────
-- demo_accounts and site_settings were readable in full by every authenticated
-- user, exposing who the demo identity is, who granted it, operator notes and
-- every future settings column. The frontend needs two facts, so give it two
-- facts.
drop policy if exists demo_accounts_read on demo_accounts;
drop policy if exists site_settings_read on site_settings;

create or replace function public.demo_context()
returns jsonb
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select jsonb_build_object(
        'is_demo', private.is_demo_account(auth.uid()),
        'enabled', coalesce((select demo_enabled from site_settings), false),
        'hunt_id', case
            when coalesce((select demo_enabled from site_settings), false)
            then (select demo_hunt_id from site_settings)
            else null
        end
    );
$$;

comment on function public.demo_context() is
  'The only demo metadata a client may read: am I the Demo Account, is the '
  'demo on, and which Hunt is it. Replaces direct SELECT on demo_accounts and '
  'site_settings so operator notes and future settings columns are not public.';

revoke all on function public.demo_context() from public, anon;
grant execute on function public.demo_context() to authenticated;

-- ── H1: explicit guards inside the money-spending RPCs ───────────────────────
-- DESIGN §16 item 4 requires these; the previous migration argued they were
-- redundant because the statement guard already refuses their writes. The
-- report's counter-argument is accepted and is the stronger one: these are
-- SECURITY DEFINER, cost-bearing entry points, and a guard that depends on
-- reaching a particular INSERT breaks the moment one of them grows a side
-- effect before that INSERT. Guard at entry instead.
--
-- The bodies are not retyped. Each definition is read back from the catalogue
-- and the guard call injected after its body's BEGIN, so the original text is
-- preserved exactly and re-running is a no-op.
create or replace function private.assert_not_demo(p_context text)
returns void
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
begin
    if private.is_demo_account(auth.uid()) then
        raise exception 'demo accounts are read-only'
            using errcode = '42501',
                  detail  = format('blocked %s', p_context),
                  hint    = 'This account exists to demonstrate the app; '
                            'nothing it does is saved.';
    end if;
end $$;

revoke all on function private.assert_not_demo(text) from public, anon;
grant execute on function private.assert_not_demo(text) to authenticated;

do $outer$
declare
    v_fn   text;
    v_def  text;
    v_pos  int;
begin
    foreach v_fn in array array[
        'public.submit_listing(uuid,text,text,text)',
        'public.answer_job_checkpoint(uuid,jsonb,jsonb)',
        'public.set_listing_source_policy(uuid,text)',
        'public.correct_auto_resolved_checkpoint(uuid,jsonb)'
    ] loop
        v_def := pg_get_functiondef(v_fn::regprocedure);

        if position('assert_not_demo' in v_def) > 0 then
            continue;  -- already guarded; idempotent re-run
        end if;

        v_pos := position(e'\nbegin\n' in v_def);
        if v_pos = 0 then
            raise exception 'could not find the body BEGIN of %', v_fn;
        end if;

        execute substr(v_def, 1, v_pos + 6)
             || format('    perform private.assert_not_demo(%L);', v_fn) || e'\n'
             || substr(v_def, v_pos + 7);
    end loop;
end $outer$;

do $$
declare
    v_fn text;
begin
    foreach v_fn in array array[
        'public.submit_listing(uuid,text,text,text)',
        'public.answer_job_checkpoint(uuid,jsonb,jsonb)',
        'public.set_listing_source_policy(uuid,text)',
        'public.correct_auto_resolved_checkpoint(uuid,jsonb)'
    ] loop
        if position('assert_not_demo' in pg_get_functiondef(v_fn::regprocedure)) = 0
        then
            raise exception 'guard injection failed for %', v_fn;
        end if;
    end loop;
end $$;
