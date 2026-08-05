-- Migration: Demo Mode foundation (DM-3, DESIGN §16 / §20 v3.53).
--
-- A Demo Account is one shared, Site-Admin-provisioned account that a stranger
-- signs into from the public internet. It holds a genuine Supabase session in a
-- browser we do not control, so every control here assumes the JWT will be
-- driven straight at PostgREST with the API bypassed entirely. The API-layer
-- check that accompanies this migration is a legible error message, not a
-- boundary; this file is the boundary.
--
-- Why a trigger rather than amending the write policies: roughly twenty
-- migrations' worth of write policies gate on `private.member_role(hunt_id) is
-- not null` -- "any member" -- which a demo Curator satisfies. Amending each is
-- a wide diff whose failure mode is silent, and whose next author has to
-- remember. One trigger covers every table in `public`, including tables that
-- do not exist yet, and is independent of who wrote which policy.
--
-- Known coverage limits, asserted at the bottom of this file rather than
-- assumed: `public` only; not TRUNCATE unless separately attached; and views
-- only when they carry an INSTEAD OF trigger, which is why the second
-- self-check refuses any writable view instead.

-- ── demo_accounts ────────────────────────────────────────────────────────────
-- Expected cardinality is one. It is a table rather than a config value so the
-- identity is a foreign key -- deleting the auth user takes the marker with it,
-- which is the safe direction: no marker means no demo, never an unguarded one.
create table if not exists demo_accounts (
    user_id    uuid primary key references auth.users (id) on delete cascade,
    created_by uuid references auth.users (id) on delete set null,
    created_at timestamptz not null default now(),
    note       text
);

comment on table demo_accounts is
  'DESIGN §16: accounts that are read-only at the database layer. A row here '
  'means every statement carrying this user''s JWT is refused by '
  'private.demo_write_guard(), and reads are scoped by the restrictive policies '
  'in the companion migration.';

alter table demo_accounts enable row level security;

-- Readable by authenticated users because the frontend must know it is in demo
-- mode before it renders anything. There is nothing sensitive in the fact.
-- Writes are service-role only: no policy admits them.
drop policy if exists demo_accounts_read on demo_accounts;
create policy demo_accounts_read on demo_accounts
    for select to authenticated using (true);

-- ── site_settings ────────────────────────────────────────────────────────────
-- Single row, enforced by the primary key check. There is no runtime settings
-- surface in this codebase today (config.py is env-only), so this is a new
-- moving part and NFR5 requires it be named in the Decision Log -- it is,
-- under v3.53.
create table if not exists site_settings (
    id           boolean primary key default true check (id),
    demo_enabled boolean not null default false,
    demo_hunt_id uuid references hunts (id) on delete set null,
    updated_by   uuid references auth.users (id) on delete set null,
    updated_at   timestamptz not null default now()
);

comment on table site_settings is
  'Single-row site configuration. demo_enabled defaults to false: a fresh '
  'database, and every `supabase db reset`, comes up with the demo off.';

insert into site_settings (id) values (true) on conflict (id) do nothing;

alter table site_settings enable row level security;

drop policy if exists site_settings_read on site_settings;
create policy site_settings_read on site_settings
    for select to authenticated using (true);

-- ── private.is_demo_account ──────────────────────────────────────────────────
-- Mirrors private.is_site_admin (20260826000000). STABLE so the planner may
-- cache it for the duration of a statement -- load-bearing, because it is
-- called once per statement by the guard and once per query by each restrictive
-- read policy.
--
-- is_demo_account(null) is false by construction. That is deliberate and it is
-- also the guard's blind spot: service-role statements have a null auth.uid(),
-- so the worker and the seed script pass through untouched -- and so do the
-- SECURITY DEFINER membership RPCs, which is why DM-4 guards their user-id
-- *parameter* separately rather than relying on this.
create or replace function private.is_demo_account(u uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select exists (select 1 from demo_accounts where user_id = u);
$$;

revoke all on function private.is_demo_account(uuid) from public, anon;
grant execute on function private.is_demo_account(uuid) to authenticated;

-- ── private.demo_write_guard ─────────────────────────────────────────────────
-- Statement-level, so it costs one call per statement rather than one per row,
-- and so it fires even on statements that match zero rows (a per-row trigger
-- would let `delete from comments where false` through silently -- harmless in
-- itself, but it makes the guard's behaviour depend on the data, which is not a
-- property a security control should have).
--
-- Foreign-key cascades are covered without further work: Postgres performs them
-- as ordinary UPDATE/DELETE against the referencing table, firing its triggers.
create or replace function private.demo_write_guard()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if private.is_demo_account(auth.uid()) then
        raise exception 'demo accounts are read-only'
            using errcode = '42501',  -- insufficient_privilege
                  detail  = format('blocked %s on %I.%I',
                                   tg_op, tg_table_schema, tg_table_name),
                  hint    = 'This account exists to demonstrate the app; '
                            'nothing it does is saved.';
    end if;
    return null;  -- ignored for statement-level triggers
end $$;

-- ── Attach to every base table in public ─────────────────────────────────────
do $$
declare
    v_table text;
begin
    for v_table in
        select c.relname
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public'
           and c.relkind in ('r', 'p')   -- ordinary + partitioned tables
         order by c.relname
    loop
        execute format(
            'create or replace trigger demo_write_guard '
            'before insert or update or delete on public.%I '
            'for each statement execute function private.demo_write_guard()',
            v_table);

        -- TRUNCATE cannot share a trigger with the other three verbs, and it
        -- ignores RLS entirely. PostgREST exposes no TRUNCATE verb, so this is
        -- defence in depth against a future direct-SQL path rather than a live
        -- hole -- but Supabase's stock bootstrap grants ALL on public tables to
        -- `authenticated`, so the privilege is genuinely there to be used.
        execute format(
            'create or replace trigger demo_truncate_guard '
            'before truncate on public.%I '
            'for each statement execute function private.demo_write_guard()',
            v_table);
    end loop;
end $$;

-- ── Self-check 1: every base table carries the guard ─────────────────────────
-- Note what this does and does not catch. It runs at *this* migration's point
-- in history, so it sees only the tables that exist by now -- a table added by
-- a later migration will not be caught here, however much the phrasing "every
-- table" suggests otherwise.
--
-- The durable check is therefore a test, not this block:
-- `api/tests/test_demo_guard.py::test_every_public_table_carries_the_write_guard`
-- runs against the schema as it finally stands and fails when a new table
-- arrives without the guard. This block stays because it makes the migration
-- refuse to land in a half-applied state, which is a different job.
do $$
declare
    v_missing text;
begin
    select string_agg(c.relname, ', ' order by c.relname)
      into v_missing
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public'
       and c.relkind in ('r', 'p')
       and not exists (
           select 1 from pg_trigger t
            where t.tgrelid = c.oid
              and t.tgname = 'demo_write_guard'
              and not t.tgisinternal);

    if v_missing is not null then
        raise exception
            'Tables missing the demo write guard: %. Re-run the attachment '
            'loop in 20260901000000_demo_mode_foundation.sql.', v_missing;
    end if;
end $$;

-- ── Revoke stray write grants on views ───────────────────────────────────────
-- Supabase's bootstrap issues a blanket `grant all on all tables in schema
-- public` which sweeps up views, so all twelve of this schema's views arrived
-- INSERT/UPDATE/DELETE-able by `authenticated`. Nothing writes through them --
-- they are derived read models (`current_*`, the roll-ups, `hunt_activity`),
-- and this codebase's whole shape is append-only base tables read through
-- current-value views.
--
-- To be precise about the risk being closed, because it is smaller than it
-- looks: an auto-updatable view rewrites to a statement on its base table,
-- which fires that table's guard, and `auth.uid()` reads a request GUC that
-- does not change with the executing role -- so even a SECURITY DEFINER view
-- could not launder a demo write past the trigger today. This is hygiene and
-- defence in depth, removing a grant nobody uses so that the self-check below
-- can assert a simple property instead of reasoning about updatability.
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
            'from authenticated, anon', v_view);
    end loop;
end $$;

-- ── Self-check 2: no view in public is writable by authenticated ─────────────
-- Statement triggers on a view fire only when the view has an INSTEAD OF
-- trigger, and a SECURITY DEFINER auto-updatable view would bypass both the
-- base table's RLS and the guard in a single step. Every view today is
-- security_invoker, and the one definer-owned view (hunt_activity) is a UNION
-- and therefore not auto-updatable -- so rather than attach triggers to views,
-- assert the property that makes them irrelevant.
do $$
declare
    v_writable text;
begin
    select string_agg(c.relname, ', ' order by c.relname)
      into v_writable
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public'
       and c.relkind = 'v'
       and (has_table_privilege('authenticated', c.oid, 'INSERT')
         or has_table_privilege('authenticated', c.oid, 'UPDATE')
         or has_table_privilege('authenticated', c.oid, 'DELETE'));

    if v_writable is not null then
        raise exception
            'Views writable by authenticated bypass the demo write guard: %. '
            'Revoke the write grant, or give the view an INSTEAD OF trigger '
            'that calls private.demo_write_guard().', v_writable;
    end if;
end $$;
