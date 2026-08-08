-- Migration: demo identity is claim-aware and fails closed (R2 C1/H2).
--
-- Finding C1 in docs/demo-mode-security-impl-reanalysis.md. Every control in
-- this series has so far asked one question: `private.is_demo_account(auth.uid())`,
-- which is true only while a row exists in `demo_accounts`. Both read predicates
-- are written as
--
--     not private.is_demo_account(auth.uid()) or <scoping>
--
-- so the *absence* of the marker row is indistinguishable from "this is an
-- ordinary member". Delete the singleton -- a mis-ordered reconcile, a manual
-- service-role cleanup, a future cascade -- and every unexpired demo token
-- silently becomes a fully privileged authenticated reader: all Properties, all
-- Sources, all Floor Plans, every object in `property-images`, across every
-- Hunt. The kill switch does not help, because the unrestricted branch never
-- reaches `demo_enabled`. `demo_accounts.user_id` lost its foreign key when the
-- principal went virtual (v3.55), so nothing prevents that deletion.
--
-- The fix is to stop deriving identity from configuration alone. The API
-- already mints a signed top-level `manzil_demo` claim; the database ignored
-- it. Now it does not.
--
-- Why the claim is safe to trust *as a restriction*: PostgREST verifies the
-- project signature before any of this runs, so a claim cannot be forged into
-- existence. It is used only to take privilege away. Visibility is still
-- granted by the marker row and the enabled Demo Hunt, never by the claim --
-- so a valid signature cannot mint itself access to anything either.
--
-- The second half of this migration (H2) closes token revival. The kill switch
-- reads current `demo_enabled`, and nothing in a token records which
-- configuration issued it -- so disabling during an incident, remediating, and
-- re-enabling hands every still-unexpired token its access back. A generation
-- counter bumped on every toggle, minted into the token and required to match,
-- makes disable-then-enable a real revocation rather than a pause.

-- ── The generation counter ───────────────────────────────────────────────────
alter table site_settings
    add column if not exists demo_generation bigint not null default 1;

comment on column site_settings.demo_generation is
  'Bumped by set_demo_enabled() on every toggle in either direction. Minted '
  'into each demo token as `manzil_demo_gen` and required to match, so tokens '
  'issued before a disable stay dark after a re-enable (R2 H2). This is the '
  'revocation lever that does not wait for `exp`.';

-- ── The claim ────────────────────────────────────────────────────────────────
-- Read defensively. A malformed claims GUC must not raise from inside forty
-- RLS policies, and `request.jwt.claims` is unset entirely for service-role
-- statements run outside PostgREST (the worker, the seed, these tests).
create or replace function private.demo_claims()
returns jsonb
language plpgsql
stable
set search_path = public, pg_temp
as $$
declare
    v_raw text;
begin
    v_raw := coalesce(
        nullif(current_setting('request.jwt.claims', true), ''),
        nullif(current_setting('request.jwt.claim', true), '')
    );
    if v_raw is null then
        return null;
    end if;
    return v_raw::jsonb;
exception when others then
    return null;   -- unparseable claims are treated as no claims
end $$;

create or replace function private.has_demo_claim()
returns boolean
language sql
stable
set search_path = public, pg_temp
as $$
    select coalesce(private.demo_claims() ->> 'manzil_demo', '') = 'true';
$$;

comment on function private.has_demo_claim() is
  'True when the caller presented one of our minted demo tokens. Signed by the '
  'project secret and verified by PostgREST before this runs, so it cannot be '
  'forged -- but it is used only to REMOVE privilege, never to grant it.';

revoke all on function private.demo_claims() from public, anon;
revoke all on function private.has_demo_claim() from public, anon;
grant execute on function private.demo_claims() to authenticated;
grant execute on function private.has_demo_claim() to authenticated;

-- ── The one identity question every control now asks ─────────────────────────
-- Three answers:
--
--   'none'   -- an ordinary subject. Behaviour is exactly what it was.
--   'scoped' -- a demo subject, correctly configured, demo enabled. Reads the
--               Demo Hunt and nothing else; writes still refused.
--   'dark'   -- a demo subject whose configuration does not hold: marker
--               missing, duplicated, or naming a different subject; generation
--               stale; or the demo simply switched off. Reads nothing outside
--               reference data; writes refused.
--
-- The important asymmetry: a *claim* is enough to reach 'dark', but reaching
-- 'scoped' additionally requires the marker row, the enabled switch, and a
-- matching generation. Losing configuration therefore removes access instead of
-- conferring it, which is the inversion C1 is about.
create or replace function private.demo_identity()
returns text
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
    v_claimed  boolean := private.has_demo_claim();
    v_uid      uuid    := auth.uid();
    v_marked   boolean;
    v_count    integer;
    v_enabled  boolean;
    v_gen      bigint;
begin
    v_marked := private.is_demo_account(v_uid);

    if not v_claimed and not v_marked then
        return 'none';
    end if;

    select count(*) into v_count from demo_accounts;
    select demo_enabled, demo_generation into v_enabled, v_gen from site_settings;

    -- Any inconsistency at all is darkness, not ordinary membership.
    if not v_marked or v_count <> 1 or not coalesce(v_enabled, false) then
        return 'dark';
    end if;

    -- Generation is checked only for minted tokens. A real account marked demo
    -- -- the operator's escape hatch, and the case the membership guard still
    -- exists for -- carries no token of ours and no generation to compare.
    if v_claimed and coalesce(private.demo_claims() ->> 'manzil_demo_gen', '')
                     is distinct from v_gen::text then
        return 'dark';
    end if;

    return 'scoped';
end $$;

comment on function private.demo_identity() is
  'none | scoped | dark. The single demo question every RLS predicate, the '
  'write guard and the RPC guards ask. Configuration loss produces `dark` '
  '(no access) rather than `none` (full authenticated access) -- see R2 C1.';

revoke all on function private.demo_identity() from public, anon;
grant execute on function private.demo_identity() to authenticated;

-- ── Reads ────────────────────────────────────────────────────────────────────
-- Same shape as before, but the fall-through for a demo subject is now `false`
-- rather than an unrestricted `true`.
create or replace function private.demo_readable_property(p uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select case private.demo_identity()
        when 'none' then true
        when 'dark' then false
        else exists (
            select 1
              from hunt_listings hl
             where hl.property_id = p
               and hl.hunt_id = (select s.demo_hunt_id from site_settings s)
        )
    end;
$$;

comment on function private.demo_readable_property(uuid) is
  'True unless the caller is a demo subject reading a Property outside the '
  'enabled Demo Hunt -- or a demo subject whose configuration does not hold, '
  'which reads nothing. RESTRICTIVE predicate: it ANDs onto the existing '
  'permissive policies rather than replacing them.';

create or replace function private.demo_readable_storage_object(object_name text)
returns boolean
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
    v_identity text := private.demo_identity();
    v_property uuid;
begin
    -- Ordinary members keep the current posture here. DESIGN §8.3 says image
    -- access belongs in a Hunt context for everyone, which this does not yet
    -- do; that is Phase D of .claude/plans/demo-mode-hardening.md and it
    -- rewrites this branch.
    if v_identity = 'none' then
        return true;
    end if;
    if v_identity = 'dark' then
        return false;
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

-- ── member_role: the Hunt-scoped half of the kill switch ─────────────────────
create or replace function private.member_role(h uuid)
returns hunt_role
language sql
stable
security definer
set search_path = public
as $$
    select coalesce(
        -- Ordinary members. A demo subject never matches: a claim alone
        -- disqualifies the branch, so marking a real account demo -- or
        -- presenting a demo token whose configuration has gone -- revokes
        -- stored memberships too.
        (select hm.role
           from hunt_members hm
          where hm.hunt_id = h
            and hm.user_id = auth.uid()
            and private.demo_identity() = 'none'),
        -- The demo principal: Curator of the Demo Hunt, and only while its
        -- configuration holds. `dark` reaches neither branch, which is what
        -- darkens PostgREST and Realtime.
        (select 'curator'::hunt_role
          where private.demo_identity() = 'scoped'
            and h = (select s.demo_hunt_id from site_settings s))
    )
$$;

comment on function private.member_role(uuid) is
  'The Hunt role of the calling user, or null. Demo-synthesising since v3.55 '
  'and claim-aware since the R2 C1 fix: the demo principal has no hunt_members '
  'row because it has no account, and is Curator of the Demo Hunt only while '
  'private.demo_identity() = ''scoped''. can_read_hunt() and '
  'can_read_hunt_governance() inherit this, which is what makes the kill '
  'switch reach PostgREST and Realtime rather than only the API.';

-- ── The two read paths that route around member_role() ───────────────────────
-- Making `member_role()` demo-aware covers the Hunt-scoped tables, but two
-- predicates deliberately bypass it and would have kept answering for a demo
-- subject:
--
--   * `hunts_member_select` admits `owner_id = auth.uid()` directly, so
--     PostgREST can return the creation response before membership-backed
--     visibility exists (§20 2026-07-11).
--   * `is_site_admin()` grants support reads across every Hunt.
--
-- Neither is reachable by the *virtual* principal, which owns nothing and
-- administers nothing. Both are reachable by the other demo shape -- a real
-- account marked in `demo_accounts` -- and by any token bearing our demo claim.
-- Since the whole point of the change above is that identity no longer depends
-- on configuration surviving, leaving two predicates keyed to the subject alone
-- would reintroduce the split-brain in miniature.
create or replace function private.is_site_admin(u uuid default auth.uid())
returns boolean language sql stable security definer set search_path = public
as $$
    select private.demo_identity() = 'none'
       and exists (select 1 from site_admins where user_id = u);
$$;

comment on function private.is_site_admin(uuid) is
    'True when the user is a Site Admin and is not a demo subject. SECURITY '
    'DEFINER because the caller has no SELECT privilege on site_admins. The '
    'demo clause is a restriction only: it can withhold admin reads, never '
    'confer them.';

drop policy if exists hunts_member_select on hunts;
create policy hunts_member_select on hunts for select to authenticated
    using (
        private.can_read_hunt(id)
        or (owner_id = auth.uid() and private.demo_identity() = 'none')
    );

-- ── Writes ───────────────────────────────────────────────────────────────────
-- Both the statement guard and the RPC entry guard refuse `dark` as firmly as
-- `scoped`. A token whose configuration has been torn out is still a token we
-- minted for a visitor, and it must not be able to write while the operator is
-- mid-repair.
create or replace function private.demo_write_guard()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if private.demo_identity() <> 'none' then
        raise exception 'demo accounts are read-only'
            using errcode = '42501',  -- insufficient_privilege
                  detail  = format('blocked %s on %I.%I',
                                   tg_op, tg_table_schema, tg_table_name),
                  hint    = 'This account exists to demonstrate the app; '
                            'nothing it does is saved.';
    end if;
    return null;  -- ignored for statement-level triggers
end $$;

-- The four money-spending RPCs call this at entry; their bodies are untouched
-- (20260901000003 injected the call from the catalogue), so widening the
-- question here widens all four.
create or replace function private.assert_not_demo(p_context text)
returns void
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
begin
    if private.demo_identity() <> 'none' then
        raise exception 'demo accounts are read-only'
            using errcode = '42501',
                  detail  = format('blocked %s', p_context),
                  hint    = 'This account exists to demonstrate the app; '
                            'nothing it does is saved.';
    end if;
end $$;

-- ── Client-visible context ───────────────────────────────────────────────────
-- `is_demo` must be true for a claim-holder even when configuration is broken,
-- or the frontend would drop its read-only affordances at exactly the moment
-- the database has stopped answering.
create or replace function public.demo_context()
returns jsonb
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select jsonb_build_object(
        'is_demo', private.demo_identity() <> 'none',
        'enabled', private.demo_identity() = 'scoped',
        'hunt_id', case
            when private.demo_identity() = 'scoped'
            then (select demo_hunt_id from site_settings)
            else null
        end
    );
$$;

-- ── Toggling rotates the generation ──────────────────────────────────────────
create or replace function public.set_demo_enabled(p_enabled boolean, p_actor uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_problems text[];
    v_gen      bigint;
begin
    if p_enabled then
        v_problems := private.demo_preflight();
        if array_length(v_problems, 1) > 0 then
            raise exception 'demo mode preflight failed'
                using errcode = '42501',
                      detail  = array_to_string(v_problems, '; ');
        end if;
    end if;

    -- Bumped in both directions, and unconditionally: an operator who disables
    -- and re-enables has revoked every token issued before the incident, and an
    -- operator who re-enables twice has not accidentally resurrected the first
    -- batch. Cheap enough to do on a no-op toggle rather than reason about
    -- whether the value actually changed.
    update site_settings
       set demo_enabled    = p_enabled,
           demo_generation = demo_generation + 1,
           updated_by      = p_actor,
           updated_at      = now()
     returning demo_generation into v_gen;

    return jsonb_build_object('demo_enabled', p_enabled, 'demo_generation', v_gen);
end $$;

revoke all on function public.set_demo_enabled(boolean, uuid) from public, anon, authenticated;

-- ── Issuance carries the generation ──────────────────────────────────────────
-- The API needs it to mint a token that will still be accepted. Returned rather
-- than read separately so the value cannot drift between the two statements.
create or replace function public.issue_demo_session(
    p_client_key   text,
    p_user_agent   text,
    p_per_key_hour integer default 20,
    p_global_hour  integer default 600
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_enabled   boolean;
    v_hunt      uuid;
    v_gen       bigint;
    v_demo_user uuid;
    v_per_key   integer;
    v_global    integer;
begin
    select demo_enabled, demo_hunt_id, demo_generation
      into v_enabled, v_hunt, v_gen
      from site_settings;

    if not coalesce(v_enabled, false) then
        insert into demo_session_issuance (client_key, user_agent, outcome)
        values (p_client_key, left(p_user_agent, 300), 'disabled');
        return jsonb_build_object('status', 'disabled');
    end if;

    select count(*) into v_global
      from demo_session_issuance
     where outcome = 'issued' and issued_at > now() - interval '1 hour';

    select count(*) into v_per_key
      from demo_session_issuance
     where outcome = 'issued' and client_key is not distinct from p_client_key
       and issued_at > now() - interval '1 hour';

    if v_global >= p_global_hour or v_per_key >= p_per_key_hour then
        insert into demo_session_issuance (client_key, user_agent, outcome)
        values (p_client_key, left(p_user_agent, 300), 'rate_limited');
        return jsonb_build_object('status', 'rate_limited');
    end if;

    select user_id into v_demo_user from demo_accounts limit 1;
    if v_demo_user is null then
        insert into demo_session_issuance (client_key, user_agent, outcome)
        values (p_client_key, left(p_user_agent, 300), 'disabled');
        return jsonb_build_object('status', 'disabled');
    end if;

    insert into demo_session_issuance (client_key, user_agent, outcome)
    values (p_client_key, left(p_user_agent, 300), 'issued');

    return jsonb_build_object(
        'status',     'issued',
        'user_id',    v_demo_user,
        'hunt_id',    v_hunt,
        'generation', v_gen
    );
end $$;

revoke all on function public.issue_demo_session(text, text, integer, integer)
    from public, anon, authenticated;
