-- Migration: scope global-fact reads, and make §16's cleaned-text claim true
-- (DM-1, DESIGN §16 / §20 v3.53).
--
-- This is not a demo feature. DESIGN §16 has said since 2026-06-28 that
-- "cleaned Source text may embed page content and remains service-role-only."
-- It never did. `property_sources` is `for select to authenticated using
-- (true)` (20260714000000:59-75) and no column-level grant exists anywhere in
-- the migration set, so `cleaned_text` -- added later as a plain column for
-- debugging (20260713000000) -- has been readable by every account since it
-- landed. So have every canonical address, every global extraction, and every
-- source URL, across every Hunt.
--
-- Nothing was exploited, because there are two accounts and both belong to
-- people who could read the database anyway. That is the entire mitigation, and
-- it stops being one the moment an untrusted party holds a session. Demo Mode
-- is what made this urgent; the fix is worth having regardless, and the second
-- half of this file (the column revoke) applies to every member, not just demo.

-- ── The scope predicate ──────────────────────────────────────────────────────
-- One helper drives every policy below, because all eight tables reach
-- `properties` in at most one hop and a single definition is one thing to audit
-- rather than eight things to keep in step.
--
-- The `not is_demo_account(...)` disjunct is first for a reason: it is a cheap
-- STABLE call, so for every real member Postgres short-circuits before touching
-- hunt_listings, and their query plans are unchanged. Only demo sessions pay
-- for the scoping subquery.
--
-- demo_enabled participates here, which is what makes the kill switch real.
-- Checked only in FastAPI it would gate FastAPI; folded into RLS it darkens
-- PostgREST and Realtime too, since both go through these policies and neither
-- has ever heard of our API.
create or replace function private.demo_readable_property(p uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select not private.is_demo_account(auth.uid())
        or (
            coalesce((select s.demo_enabled from site_settings s), false)
            and exists (
                select 1
                  from hunt_listings hl
                 where hl.property_id = p
                   and hl.hunt_id = (select s.demo_hunt_id from site_settings s)
            )
        );
$$;

comment on function private.demo_readable_property(uuid) is
  'True unless the caller is a Demo Account reading a Property outside the '
  'enabled Demo Hunt. Used as a RESTRICTIVE select predicate so it ANDs onto '
  'the existing permissive policies instead of replacing them.';

revoke all on function private.demo_readable_property(uuid) from public, anon;
grant execute on function private.demo_readable_property(uuid) to authenticated;

-- ── Restrictive SELECT policies ──────────────────────────────────────────────
-- RESTRICTIVE is the point: these AND with the permissive `using (true)`
-- policies rather than replacing them, so this migration adds a constraint
-- without touching, or needing to understand, the twenty-odd policies already
-- in place.
--
-- criteria_catalog and utility_baselines are deliberately absent: they are
-- reference data with no Property, no Hunt, and nothing to leak.

drop policy if exists properties_demo_scope on properties;
create policy properties_demo_scope on properties
    as restrictive for select to authenticated
    using (private.demo_readable_property(id));

drop policy if exists property_sources_demo_scope on property_sources;
create policy property_sources_demo_scope on property_sources
    as restrictive for select to authenticated
    using (private.demo_readable_property(property_id));

drop policy if exists floor_plans_demo_scope on floor_plans;
create policy floor_plans_demo_scope on floor_plans
    as restrictive for select to authenticated
    using (private.demo_readable_property(property_id));

drop policy if exists property_images_demo_scope on property_images;
create policy property_images_demo_scope on property_images
    as restrictive for select to authenticated
    using (private.demo_readable_property(property_id));

drop policy if exists property_contacts_demo_scope on property_contacts;
create policy property_contacts_demo_scope on property_contacts
    as restrictive for select to authenticated
    using (private.demo_readable_property(property_id));

drop policy if exists extractions_demo_scope on extractions;
create policy extractions_demo_scope on extractions
    as restrictive for select to authenticated
    using (private.demo_readable_property(property_id));

-- The two join tables carry no property_id of their own and so take the hop.
drop policy if exists floor_plan_images_demo_scope on floor_plan_images;
create policy floor_plan_images_demo_scope on floor_plan_images
    as restrictive for select to authenticated
    using (private.demo_readable_property(
        (select fp.property_id from floor_plans fp where fp.id = floor_plan_id)));

drop policy if exists extraction_images_demo_scope on extraction_images;
create policy extraction_images_demo_scope on extraction_images
    as restrictive for select to authenticated
    using (private.demo_readable_property(
        (select pi.property_id from property_images pi
          where pi.id = property_image_id)));

-- ── cleaned_text: make §16 true for everyone ─────────────────────────────────
-- Column-level REVOKE does not work while a table-level SELECT grant stands --
-- the table grant simply wins. The only way to withhold one column is to drop
-- the table-level grant and re-grant the columns individually.
--
-- Built dynamically rather than typed out, because a hand-written column list
-- is a landmine: it would be correct today and quietly wrong after the next
-- `alter table ... add column`. The consequence of doing it this way is that a
-- future column is *not* granted until someone re-runs an equivalent statement,
-- which fails closed -- the new column is invisible rather than silently
-- exposed. The self-check below states that contract so the next author meets
-- it as a clear error rather than a mystery.
--
-- Nothing outside the worker reads this column: neither `api/src` nor
-- `frontend/src` mentions it, and the worker holds the service role, which
-- these grants do not touch.
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

    execute format('grant select (%s) on property_sources to authenticated',
                   v_cols);
end $$;

comment on column property_sources.cleaned_text is
  'Phase-1 debugging artifact: exact cleaned page text the extraction model '
  'saw. Service-role only (DESIGN §16) -- enforced by column grant since '
  'DM-1: `authenticated` holds SELECT on every column of this table EXCEPT '
  'this one. Adding a column requires re-granting it (see '
  '20260901000001_demo_read_scoping.sql); new columns are invisible until you '
  'do, which is the intended direction of failure.';

-- ── Self-checks ──────────────────────────────────────────────────────────────
do $$
begin
    if has_column_privilege('authenticated', 'public.property_sources',
                            'cleaned_text', 'SELECT') then
        raise exception
            'property_sources.cleaned_text is readable by authenticated; '
            'DESIGN §16 requires it be service-role only.';
    end if;
end $$;

-- The inverse: having dropped the table-level grant, every *other* column must
-- still be readable, or this migration has quietly broken the app.
do $$
declare
    v_hidden text;
begin
    select string_agg(column_name, ', ' order by ordinal_position)
      into v_hidden
      from information_schema.columns
     where table_schema = 'public'
       and table_name   = 'property_sources'
       and column_name <> 'cleaned_text'
       and not has_column_privilege('authenticated', 'public.property_sources',
                                    column_name, 'SELECT');

    if v_hidden is not null then
        raise exception
            'These property_sources columns lost their SELECT grant: %. '
            'Re-run the grant block in this migration.', v_hidden;
    end if;
end $$;

-- fetch_adapter_registry.adapter_config is world-readable jsonb and is the
-- natural place a proxy zone or unblocker credential would eventually land.
-- It holds no secrets today; this states that it must not start.
comment on column fetch_adapter_registry.adapter_config is
  'Per-domain fetch settings. NEVER SECRETS: this column is readable by every '
  'authenticated user, including the shared Demo Account. Credentials belong '
  'in worker environment variables.';
