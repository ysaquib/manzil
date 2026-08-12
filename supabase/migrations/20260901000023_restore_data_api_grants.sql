-- Explicit Data API privileges after Supabase CLI >= 2.106.
--
-- CLI v2.106 flipped `[api].auto_expose_new_tables` to default false
-- (supabase/cli#5524).  Our schema was authored against the old blanket GRANT
-- + RLS model (see 20260901000000 / 20260901000010 comments), so without
-- explicit privileges PostgREST fails with `permission denied for table hunts`
-- before RLS runs.
--
-- Grant the app's *existing* public relations to its two Data API principals:
-- authenticated user JWTs (which remain RLS-bound) and the server-held service
-- key.  Anonymous PostgREST table access is unused: anonymous authentication
-- calls GoTrue and the public demo routes are served by the API.
--
-- Crucially, revoke the legacy defaults instead of restoring them.  Every
-- future public table, sequence, and function must opt in in its own owning
-- migration.  That prevents a new, unreviewed relation from silently becoming
-- reachable over the Data API.

revoke all on all tables in schema public from anon;
revoke all on all sequences in schema public from anon;

alter default privileges for role postgres in schema public
    revoke all on tables
    from anon, authenticated, service_role;

alter default privileges for role postgres in schema public
    revoke all on sequences
    from anon, authenticated, service_role;

alter default privileges for role postgres in schema public
    revoke all on functions from public, anon, authenticated, service_role;

grant select, insert, update, delete on all tables in schema public
    to authenticated, service_role;

grant usage, select on all sequences in schema public
    to authenticated, service_role;

-- DM-1: withhold property_sources.cleaned_text (20260901000001).
do $$
declare
    v_cols text;
begin
    revoke select on property_sources from authenticated;

    select string_agg(quote_ident(column_name), ', ' order by ordinal_position)
      into v_cols
      from information_schema.columns
     where table_schema = 'public'
       and table_name   = 'property_sources'
       and column_name <> 'cleaned_text';

    execute format(
        'grant select (%s) on property_sources to authenticated',
        v_cols
    );
end $$;

-- jobs.payload withheld (20260901000010); soft-delete columns included dynamically.
do $$
declare
    v_cols text;
    v_role text;
begin
    select string_agg(quote_ident(column_name), ', ' order by ordinal_position)
      into v_cols
      from information_schema.columns
     where table_schema = 'public'
       and table_name   = 'jobs'
       and column_name <> 'payload';

    foreach v_role in array array['authenticated'] loop
        execute format('revoke select on jobs from %I', v_role);
        execute format('grant select (%s) on jobs to %I', v_cols, v_role);
    end loop;
end $$;

-- Worker liveness stays service-role only (20260901000021), and still needs the
-- demo write/truncate guards every public table carries (forgot at create time).
revoke all on table public.worker_heartbeats from anon, authenticated;
select private.attach_demo_guards('public.worker_heartbeats');

-- View write hygiene (20260901000000).
do $$
declare
    v_view text;
begin
    for v_view in
        select c.relname
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public' and c.relkind = 'v'
         order by c.relname
    loop
        execute format(
            'revoke insert, update, delete, truncate on public.%I '
            'from authenticated, anon, service_role', v_view
        );
    end loop;
end $$;

-- This is the only service-key PostgREST RPC that previously relied on the
-- legacy default function grant.  Other service RPCs grant EXECUTE explicitly
-- in the migrations that define them.
grant execute on function public.issue_demo_session(text, integer, integer)
    to service_role;

-- Self-checks: core membership tables are reachable; withholdings hold.
do $$
begin
    if not has_table_privilege('authenticated', 'public.hunts', 'SELECT')
       or not has_table_privilege('authenticated', 'public.hunt_members', 'SELECT')
       or not has_table_privilege('authenticated', 'public.visits', 'SELECT')
       or not has_table_privilege('authenticated', 'public.visits', 'INSERT') then
        raise exception
            'Data API grants missing on hunts/hunt_members/visits; '
            'authenticated cannot reach PostgREST.';
    end if;

    if has_column_privilege('authenticated', 'public.property_sources',
                            'cleaned_text', 'SELECT')
       or has_column_privilege('authenticated', 'public.jobs', 'payload', 'SELECT') then
        raise exception
            'Column withholdings lost while restoring Data API grants.';
    end if;

    if has_table_privilege('authenticated', 'public.worker_heartbeats', 'SELECT')
       or has_table_privilege('anon', 'public.worker_heartbeats', 'SELECT') then
        raise exception
            'worker_heartbeats must remain unreachable to anon/authenticated.';
    end if;

    if exists (
        select 1
          from pg_default_acl d
          cross join lateral aclexplode(d.defaclacl)
            as acl(grantor, grantee, privilege_type, is_grantable)
         where d.defaclrole = 'postgres'::regrole
           and d.defaclnamespace = 'public'::regnamespace
           and d.defaclobjtype in ('r', 'S', 'f')
           and acl.grantee in (
               'anon'::regrole,
               'authenticated'::regrole,
               'service_role'::regrole,
               0
           )
    ) then
        raise exception
            'Future public relations/functions must receive explicit Data API grants.';
    end if;

    if not has_function_privilege(
        'service_role',
        'public.issue_demo_session(text, integer, integer)',
        'EXECUTE'
    ) then
        raise exception
            'service_role lacks EXECUTE on issue_demo_session; '
            'POST /v1/demo/session will 500.';
    end if;
end $$;
