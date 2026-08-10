-- Migration: demo session issuance is serialized and its storage is bounded
-- (R2 C2, M6).
--
-- Two defects in one function, from docs/demo-mode-security-impl-reanalysis.md.
--
-- **The ceilings did not hold.** `issue_demo_session` counted, decided, and then
-- inserted, with no lock. Under READ COMMITTED every concurrent caller sees the
-- same below-limit count and every one of them issues. The old comment claimed
-- "the check and the record happen in one statement so racing instances cannot
-- both pass" -- but being *called* as one statement says nothing about the
-- function's internal reads and writes, which are ordinary and interleavable.
--
-- **Refusals were durable and unbounded.** Every request inserted a row,
-- including `disabled` ones -- so an unauthenticated attacker could grow the
-- database, the WAL and the indexes without limit *while Demo Mode was off*.
-- The kill switch made it worse rather than better: it turned every request
-- into a guaranteed write.
--
-- The replacement is a fixed-size counter table. Storage per hour is bounded by
-- construction rather than by how well-behaved callers are: client keys are
-- hashed into a fixed number of buckets, so the row count per window has a hard
-- ceiling no traffic pattern can exceed, and a refusal increments an integer
-- instead of appending a row.
--
-- What that costs, stated plainly: two visitors whose keys collide share a
-- per-key quota. With 4096 buckets and a demo-scale audience that is rare, and
-- the global ceiling is the one that actually matters here anyway -- every
-- visitor shares one identity, so an attacker rotating IPs is the expected
-- shape, not the exceptional one. Griefing a colliding stranger's quota is
-- possible and bounded; exhausting the database is not.

-- ── Bounded counters replace the per-request log ─────────────────────────────
create table if not exists demo_session_counters (
    window_start  timestamptz not null,
    -- 0..4095 for a per-caller bucket; -1 is the global bucket. A fixed domain
    -- is what makes the table's size independent of the traffic hitting it.
    client_bucket smallint    not null,
    issued        integer     not null default 0,
    rate_limited  integer     not null default 0,
    disabled      integer     not null default 0,
    primary key (window_start, client_bucket)
);

create index if not exists demo_session_counters_window_idx
    on demo_session_counters (window_start);

comment on table demo_session_counters is
  'Rate-limit state and abuse telemetry for POST /v1/demo/session, shared '
  'across API instances. At most 4097 rows per hourly window regardless of '
  'traffic, and refusals increment a counter rather than appending a row -- so '
  'the one unauthenticated endpoint in this system cannot be used to grow the '
  'database (R2 C2). Stores a bucket number derived from a truncated HMAC of '
  'the caller IP: not the IP, and no longer even the HMAC.';

alter table demo_session_counters enable row level security;
-- No policy: service-role only. Nothing about who visited the demo is public.

select private.attach_demo_guards('public.demo_session_counters');

-- The old table is dropped rather than retained: keeping it would leave the
-- unbounded-growth path reachable by anything that still inserted into it, and
-- its contents are request telemetry with no downstream consumer.
drop table if exists demo_session_issuance;

-- ── Counting ─────────────────────────────────────────────────────────────────
-- Both the per-caller bucket and the global bucket move together, so the two
-- ceilings can never disagree about what happened.
create or replace function private.demo_count(
    p_window timestamptz, p_bucket smallint, p_outcome text
)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_buckets smallint[] := case
        when p_bucket = -1 then array[-1]::smallint[]
        else array[-1, p_bucket]::smallint[]
    end;
    v_bucket smallint;
begin
    foreach v_bucket in array v_buckets loop
        insert into demo_session_counters as c
               (window_start, client_bucket, issued, rate_limited, disabled)
        values (p_window, v_bucket,
                (p_outcome = 'issued')::int,
                (p_outcome = 'rate_limited')::int,
                (p_outcome = 'disabled')::int)
        on conflict (window_start, client_bucket) do update
           set issued       = c.issued       + (p_outcome = 'issued')::int,
               rate_limited = c.rate_limited + (p_outcome = 'rate_limited')::int,
               disabled     = c.disabled     + (p_outcome = 'disabled')::int;
    end loop;
end $$;

revoke all on function private.demo_count(timestamptz, smallint, text)
    from public, anon, authenticated;

-- ── Issuance ─────────────────────────────────────────────────────────────────
-- `p_user_agent` is gone. It was truncated and stored per request; with counters
-- there is nowhere to put it, and not collecting it at all is the better answer
-- for the one endpoint in this system that people who are not users can reach
-- (§16 PII posture).
drop function if exists public.issue_demo_session(text, text, integer, integer);

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
    v_bucket := case
        when p_client_key is null then -1
        else (abs(hashtextextended(p_client_key, 0)) % c_buckets)::smallint
    end;

    perform pg_advisory_xact_lock(c_lock);

    -- Retention. Runs under the lock, scans an index range that is empty in the
    -- steady state, and keeps enough history to investigate an incident.
    delete from demo_session_counters
     where window_start < now() - interval '48 hours';

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
  'Service-role only; the API signs the token, this decides whether it may.';
