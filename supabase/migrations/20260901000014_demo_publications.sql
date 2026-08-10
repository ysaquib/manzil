-- Admin-managed Demo Hunt publications (DESIGN §20 v3.72).
--
-- A Demo Hunt is now an ordinary Hunt owned by the Site Admin who publishes
-- it.  The live Hunt remains the read source; only the expensive/derived demo
-- assets (Replay Captures and map stills) are versioned here.  Everything in
-- `private` is reachable only by the API/worker's server credential.

create table private.demo_publications (
    id                  uuid primary key default gen_random_uuid(),
    -- A selected Hunt is protected by the trigger at the end of this migration.
    -- Historical releases for an unselected Hunt must not make that Hunt
    -- undeletable forever, so they follow it away.
    hunt_id             uuid not null references public.hunts (id) on delete cascade,
    -- Audit identities deliberately outlive Auth accounts (the same contract
    -- as admin_audit_log.admin_user_id). A foreign key here would make an old
    -- publication an invisible blocker in the account-deletion flow.
    requested_by        uuid not null,
    state               text not null default 'queued'
                        check (state in ('queued', 'building', 'ready', 'failed', 'superseded')),
    enable_on_success   boolean not null default false,
    expected_generation bigint not null,
    source_fingerprint  text not null,
    map_manifest        jsonb not null default '{}',
    replay_count        integer not null default 0 check (replay_count between 0 and 50),
    mapped_count        integer not null default 0 check (mapped_count between 0 and 100),
    warnings            jsonb not null default '[]',
    error               text,
    attempts            integer not null default 0 check (attempts between 0 and 3),
    locked_by           text,
    locked_at           timestamptz,
    created_at          timestamptz not null default now(),
    started_at          timestamptz,
    finished_at         timestamptz,
    published_at        timestamptz
);

create unique index demo_publications_one_inflight
    on private.demo_publications ((true))
    where state in ('queued', 'building');
create index demo_publications_hunt_created
    on private.demo_publications (hunt_id, created_at desc);

create table private.demo_replay_captures (
    publication_id uuid not null references private.demo_publications (id) on delete cascade,
    ordinal        integer not null check (ordinal between 0 and 49),
    -- These are immutable provenance ids, not live references. Restoring or
    -- permanently deleting an archived Listing must only mark the release
    -- stale; it must not tear a capture out of the release visitors are using.
    hunt_listing_id uuid not null,
    job_id          uuid not null,
    payload         jsonb not null,
    payload_bytes   integer not null check (payload_bytes between 1 and 1048576),
    fingerprint     text not null,
    primary key (publication_id, ordinal),
    unique (publication_id, hunt_listing_id)
);

create table private.demo_publish_confirmations (
    id                 uuid primary key default gen_random_uuid(),
    actor_id           uuid not null references auth.users (id) on delete cascade,
    hunt_id            uuid not null references public.hunts (id) on delete cascade,
    source_fingerprint text not null,
    inventory          jsonb not null,
    expires_at         timestamptz not null default now() + interval '10 minutes',
    consumed_at        timestamptz,
    created_at         timestamptz not null default now()
);
create index demo_publish_confirmations_expiry
    on private.demo_publish_confirmations (expires_at);

alter table public.site_settings
    add column demo_release_id uuid
    references private.demo_publications (id) on delete set null;

comment on column public.site_settings.demo_release_id is
  'The atomically promoted, complete set of derived Demo assets. The selected '
  'Hunt and release survive disable; demo_generation revokes visitor tokens.';

-- Versioned, private map stills. There are deliberately no storage.objects
-- policies for this bucket: the API authenticates a current Demo token and
-- streams bytes with its server credential, so a leaked object path grants
-- nothing and disabling the Demo blocks future downloads.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('demo-assets', 'demo-assets', false, 2097152, array['image/webp'])
on conflict (id) do update
set public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

revoke all on all tables in schema private from public, anon, authenticated;

-- The reusable, configuration-independent half of preflight. Candidate Hunt
-- publication calls this before a release exists; enablement calls the full
-- `demo_preflight()` below.
create or replace function private.demo_security_preflight()
returns text[]
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
    v_problems text[] := '{}';
    v_demo uuid;
    v_list text;
begin
    select user_id into v_demo from demo_accounts limit 1;
    if v_demo is null then
        v_problems := v_problems || 'no demo principal is configured'::text;
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
    if has_column_privilege('authenticated', 'public.jobs', 'payload', 'SELECT') then
        v_problems := v_problems || 'jobs.payload is readable'::text;
    end if;
    if v_demo is not null and exists (select 1 from auth.users where id = v_demo) then
        v_problems := v_problems
            || 'the demo principal has an auth.users row; it must be virtual'::text;
    end if;
    if v_demo is not null and exists (select 1 from hunt_members where user_id = v_demo) then
        v_problems := v_problems
            || 'the demo principal holds a stored hunt membership'::text;
    end if;
    return v_problems;
end $$;

revoke all on function private.demo_security_preflight() from public, anon, authenticated;

create or replace function private.demo_preflight()
returns text[]
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
    v_problems text[] := private.demo_security_preflight();
    v_hunt uuid;
    v_release uuid;
begin
    select demo_hunt_id, demo_release_id into v_hunt, v_release from site_settings;
    if v_hunt is null then
        v_problems := v_problems || 'site_settings.demo_hunt_id is null'::text;
    end if;
    if v_release is null then
        v_problems := v_problems || 'site_settings.demo_release_id is null'::text;
    end if;
    if v_hunt is not null and not exists (
        select 1 from hunts h join site_admins sa on sa.user_id = h.owner_id
         where h.id = v_hunt)
    then
        v_problems := v_problems || 'the Demo Hunt is not owned by a Site Admin'::text;
    end if;
    if v_release is not null and not exists (
        select 1 from private.demo_publications p
         join hunts h on h.id = p.hunt_id
         where p.id = v_release and p.hunt_id = v_hunt and p.state = 'ready'
           and p.requested_by = h.owner_id)
    then
        v_problems := v_problems
            || 'the promoted Demo release is not ready and owner-consented for the selected Hunt'::text;
    end if;
    if v_hunt is not null and exists (
        select 1 from hunt_members hm
         where hm.hunt_id = v_hunt
           and (hm.display_name is null or btrim(hm.display_name) = ''))
    then
        v_problems := v_problems
            || 'the Demo Hunt has members without explicit per-Hunt display names'::text;
    end if;
    return v_problems;
end $$;

-- A claim can reach `scoped` only while a complete release exists and the
-- Hunt's current owner remains a Site Admin. Ownership transfer or grant
-- revocation therefore darkens already-issued tokens without waiting for an
-- API-side repair.
create or replace function private.demo_identity()
returns text
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
    v_claimed  boolean := private.has_demo_claim();
    v_uid      uuid := auth.uid();
    v_marked   boolean;
    v_count    integer;
    v_enabled  boolean;
    v_gen      bigint;
    v_hunt     uuid;
    v_release  uuid;
begin
    v_marked := private.is_demo_account(v_uid);
    if not v_claimed and not v_marked then return 'none'; end if;

    select count(*) into v_count from demo_accounts;
    select demo_enabled, demo_generation, demo_hunt_id, demo_release_id
      into v_enabled, v_gen, v_hunt, v_release from site_settings;

    if not v_marked or v_count <> 1 or not coalesce(v_enabled, false) then
        return 'dark';
    end if;
    if v_claimed and coalesce(private.demo_claims() ->> 'manzil_demo_gen', '')
                    is distinct from v_gen::text then
        return 'dark';
    end if;
    if v_hunt is null or v_release is null or not exists (
        select 1
          from hunts h
          join site_admins sa on sa.user_id = h.owner_id
          join private.demo_publications p
            on p.id = v_release and p.hunt_id = h.id and p.state = 'ready'
           and p.requested_by = h.owner_id
         where h.id = v_hunt
           and not exists (
               select 1 from hunt_members hm
                where hm.hunt_id = h.id
                  and (hm.display_name is null or btrim(hm.display_name) = '')
           ))
    then
        return 'dark';
    end if;
    return 'scoped';
end $$;

revoke all on function private.demo_identity() from public, anon;
grant execute on function private.demo_identity() to authenticated;

-- Cheap server-only availability probe for the unauthenticated config/session
-- endpoints. It deliberately shares the same release/owner conditions as
-- `demo_identity()`; the public response remains one boolean.
create or replace function public.demo_available()
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select exists (
        select 1
          from site_settings s
          join hunts h on h.id = s.demo_hunt_id
          join site_admins sa on sa.user_id = h.owner_id
          join private.demo_publications p
            on p.id = s.demo_release_id and p.hunt_id = h.id and p.state = 'ready'
           and p.requested_by = h.owner_id
         where s.demo_enabled
           and not exists (
               select 1 from hunt_members hm
                where hm.hunt_id = h.id
                  and (hm.display_name is null or btrim(hm.display_name) = '')
           )
    );
$$;
revoke all on function public.demo_available() from public, anon, authenticated;
grant execute on function public.demo_available() to service_role;

-- Existing Hunt deletion is deliberately refused while selected. This avoids
-- ON DELETE SET NULL turning a retained selection into an unexplained partial
-- configuration. Select another Hunt first; disabling alone keeps selection.
create or replace function private.protect_selected_demo_hunt()
returns trigger language plpgsql security definer set search_path = public, pg_temp
as $$
begin
    if exists (select 1 from site_settings where demo_hunt_id = old.id) then
        raise exception 'the selected Demo Hunt cannot be deleted'
            using errcode = '23503',
                  hint = 'Select and publish another Demo Hunt before deleting this Hunt.';
    end if;
    return old;
end $$;

drop trigger if exists hunts_protect_selected_demo on public.hunts;
create trigger hunts_protect_selected_demo
before delete on public.hunts for each row execute function private.protect_selected_demo_hunt();
