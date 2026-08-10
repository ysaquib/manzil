-- Migration: the hardening tail from the second security review (R2 `R6`–`R8`).
--
-- Three small things, none of them exploitable today, all of them the kind of
-- gap that becomes exploitable when something else changes. They are in one
-- migration because they share a subject -- the public demo's two remaining
-- rough edges -- and none is large enough to be worth its own file.

-- ── `R7`: the image policy pins the bucket prefix, not only the id ───────────
--
-- `can_read_property_image` read `(storage.foldername(name))[2]` as the Property
-- id without checking `[1]`, so `zzz/<property-uuid>/x.webp` authorised exactly
-- as `properties/<property-uuid>/x.webp` does.
--
-- Security review confirmed this is **not exploitable today**: the only
-- `authenticated` policies on `storage.objects` are SELECT
-- (`20260723000000:25-26`, `20260901000008:77-82`), so there is no client path
-- that can place an object under a prefix of its choosing. That is a fact about
-- the *other* policies, though, not about this function -- and this function is
-- the one that answers "may you read this object". A predicate that authorises
-- a key it was never shown how to parse is a latent grant waiting for the day
-- somebody adds an INSERT policy. Pin the prefix.
create or replace function private.can_read_property_image(object_name text)
returns boolean
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
    v_parts text[];
    v_property uuid;
begin
    -- Keys are `properties/<property_id>/<content_hash>.webp`, written by
    -- stages/image_fetch.py and stages/image_classify.py. Anything else is not
    -- an object this policy knows how to authorize, so it is refused -- and
    -- "anything else" now includes a key that carries a real Property id under
    -- some other prefix.
    v_parts := storage.foldername(object_name);
    if array_length(v_parts, 1) is distinct from 2 or v_parts[1] <> 'properties' then
        return false;
    end if;

    begin
        v_property := v_parts[2]::uuid;
    exception when others then
        return false;
    end;

    if v_property is null then
        return false;
    end if;

    -- A Hunt context containing that Property. `member_role()` carries the demo
    -- scoping and the kill switch, so a demo subject reaches only the Demo
    -- Hunt's images and reaches nothing at all once the demo is off or its
    -- configuration stops holding.
    return exists (
        select 1
          from hunt_listings hl
         where hl.property_id = v_property
           and private.member_role(hl.hunt_id) is not null
    ) or private.is_site_admin();
end $$;

comment on function private.can_read_property_image(text) is
  'DESIGN §8.3: signed-URL access to a private image is granted only in an '
  'authenticated Hunt context containing that Property. Applies to every '
  'authenticated subject, not only the demo principal (R2 H5). The key must be '
  'exactly `properties/<uuid>/<file>` -- both the prefix and the shape are '
  'checked, so a real Property id parked under another prefix is refused (R2 '
  'R7). Site Admins are admitted for support, and is_site_admin() is itself '
  'demo-aware.';

-- ── `R8`: the bucket expression cannot raise, and cannot reach the sentinel ──
--
-- `abs(hashtextextended(p_client_key, 0)) % c_buckets` raises `22003` on one
-- input: `bigint` min has no positive counterpart, so `abs()` overflows. That
-- turns one unlucky client key into a 500 on the public endpoint, permanently,
-- for whoever holds it.
--
-- The obvious repair is worse than the bug. Postgres `%` and `mod()` keep the
-- *dividend's* sign, so `hashtextextended(...) % 4096` yields −4095..4095 --
-- and `-1` is the **reserved global bucket** (`20260901000007:69-80, :180-186`).
-- A key hashing to `-1` would take the sentinel branch, escape the per-key
-- ceiling entirely, and double-count the global row. The double modulo below is
-- the whole fix and it has to be written exactly this way.
alter table demo_session_counters
    drop constraint if exists demo_session_counters_bucket_domain;
alter table demo_session_counters
    add constraint demo_session_counters_bucket_domain
    check (client_bucket >= -1);

comment on constraint demo_session_counters_bucket_domain on demo_session_counters is
  'Belt to the function''s braces (R2 R8). -1 is the global bucket and 0..4095 '
  'are caller buckets; anything below -1 means the bucket expression has '
  'started producing signed remainders, and the table refuses to record it '
  'rather than let it quietly share a row with the global counter.';

create or replace function public.issue_demo_session(
    p_client_key   text,
    p_per_key_hour integer default 20,
    p_global_hour  integer default 600
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    -- A fixed key: every issuance decision serializes against every other one.
    -- Held for the duration of the calling transaction, which for a PostgREST
    -- RPC is this call. Cheap at demo scale -- the global ceiling is a few
    -- hundred an hour -- and it is what makes the ceilings below true rather
    -- than approximate.
    c_lock    constant bigint  := 8274531;
    c_buckets constant integer := 4096;

    v_window  timestamptz;
    v_bucket  smallint;
    v_enabled boolean;
    v_hunt    uuid;
    v_gen     bigint;
    v_user    uuid;
    v_per_key integer;
    v_global  integer;
begin
    -- ── Parameter hygiene (M6) ───────────────────────────────────────────────
    -- Only the API calls this today, but a SECURITY DEFINER function should not
    -- take the caller's word for its own limits.
    if p_client_key is not null and p_client_key !~ '^[0-9a-f]{1,64}$' then
        raise exception 'client key must be a lowercase hex digest'
            using errcode = '22023';
    end if;
    if p_per_key_hour is null or p_per_key_hour < 1 or p_per_key_hour > 100000 then
        raise exception 'per-key ceiling out of range' using errcode = '22023';
    end if;
    if p_global_hour is null or p_global_hour < 1 or p_global_hour > 1000000 then
        raise exception 'global ceiling out of range' using errcode = '22023';
    end if;

    -- Tumbling hourly window rather than the old sliding one. A caller can
    -- therefore burst across a boundary and briefly see up to twice the hourly
    -- rate; that is an accepted, documented weakening in exchange for counters
    -- that occupy fixed space. The ceiling that protects the system -- the
    -- global one -- is unaffected in aggregate.
    v_window := date_trunc('hour', now());
    -- The double modulo is deliberate and must not be simplified: see the note
    -- above this function. `abs()` raises on `bigint` min; a single `%` returns
    -- the dividend's sign and can land on the reserved global bucket.
    v_bucket := case
        when p_client_key is null then -1
        else (((hashtextextended(p_client_key, 0) % c_buckets) + c_buckets)
              % c_buckets)::smallint
    end;
    -- And an assertion, because the whole point of the expression above is that
    -- a keyed caller can never reach the sentinel. If that ever stops being
    -- true, failing here is far better than silently escaping the per-key
    -- ceiling and corrupting the global count.
    if p_client_key is not null and (v_bucket < 0 or v_bucket >= c_buckets) then
        raise exception 'demo bucket % is outside 0..%', v_bucket, c_buckets - 1
            using errcode = 'XX000';
    end if;

    perform pg_advisory_xact_lock(c_lock);

    -- Retention. Runs under the lock, scans an index range that is empty in the
    -- steady state, and keeps enough history to investigate an incident.
    delete from demo_session_counters
     where window_start < now() - interval '48 hours';

    -- `R6`: this read stays **under** the lock, and must not be moved above it.
    -- Reading the kill switch before acquiring the lock and not again after
    -- widens the window in which an operator disables the demo while an
    -- issuance is already in flight; today that is survivable only because the
    -- rotated generation renders the minted token `dark`
    -- (`20260901000006:137-140`), and a second control quietly compensating for
    -- a first one's gap is not a thing to leave undocumented.
    select demo_enabled, demo_hunt_id, demo_generation
      into v_enabled, v_hunt, v_gen
      from site_settings;

    if not coalesce(v_enabled, false) then
        perform private.demo_count(v_window, v_bucket, 'disabled');
        return jsonb_build_object('status', 'disabled');
    end if;

    select coalesce(issued, 0) into v_global
      from demo_session_counters
     where window_start = v_window and client_bucket = -1;

    if v_bucket = -1 then
        v_per_key := 0;   -- no client key: only the global ceiling applies
    else
        select coalesce(issued, 0) into v_per_key
          from demo_session_counters
         where window_start = v_window and client_bucket = v_bucket;
    end if;

    if coalesce(v_global, 0) >= p_global_hour
       or coalesce(v_per_key, 0) >= p_per_key_hour then
        perform private.demo_count(v_window, v_bucket, 'rate_limited');
        return jsonb_build_object('status', 'rate_limited');
    end if;

    select user_id into v_user from demo_accounts limit 1;
    if v_user is null then
        perform private.demo_count(v_window, v_bucket, 'disabled');
        return jsonb_build_object('status', 'disabled');
    end if;

    perform private.demo_count(v_window, v_bucket, 'issued');

    return jsonb_build_object(
        'status',     'issued',
        'user_id',    v_user,
        'hunt_id',    v_hunt,
        'generation', v_gen
    );
end $$;

revoke all on function public.issue_demo_session(text, integer, integer)
    from public, anon, authenticated;

comment on function public.issue_demo_session(text, integer, integer) is
  'Decides whether a visitor may have a demo token, under an advisory lock so '
  'racing API instances cannot both pass a ceiling. Records the attempt in a '
  'fixed-size counter rather than a row per request. Returns the virtual '
  'principal and the current demo generation the API must mint into the token. '
  'Service-role only; the API signs the token, this decides whether it may. '
  'ACCEPTED RESIDUAL (R2 R6): every request -- including a refused one, and '
  'including one arriving while the demo is off -- upserts the single global '
  'counter row, so unauthenticated traffic contends on one tuple lock and '
  'writes one dead tuple and one WAL record apiece. That cannot be removed in '
  'SQL: moving the advisory lock only relocates the contention, because '
  'private.demo_count() touches the same row either way. The remedy is the '
  'edge limiter specified in docs/production-deployment-render-supabase.md '
  '§7.0.1, owed at deploy time. This function is defence in depth, not the '
  'first packet sink.';
