-- Migration: demo session issuance and its rate limit (DM-5, DESIGN §16).
--
-- `POST /v1/demo/session` is the only unauthenticated public endpoint in this
-- system, so its ceiling has to be real. This repo has no rate-limiting
-- middleware -- the one limiter that exists is a database trigger behind the
-- feedback route -- and an in-process counter is worse than none here, because
-- Render runs more than one instance and restarts reset it.
--
-- So the limit lives in the database, where every instance shares it. The table
-- doubles as abuse telemetry: it is the only record that a visitor arrived.
--
-- No IP address is stored. A truncated HMAC of it is enough to rate-limit a
-- repeat caller and cannot be turned back into a visitor -- which matters
-- because this is the one place the app would otherwise start collecting
-- personal data about people who are not users (§16 PII posture).

create table if not exists demo_session_issuance (
    id         bigserial primary key,
    issued_at  timestamptz not null default now(),
    client_key text,          -- truncated HMAC of the caller's IP, never the IP
    user_agent text,
    outcome    text not null  -- 'issued' | 'rate_limited' | 'disabled'
        check (outcome in ('issued', 'rate_limited', 'disabled'))
);

create index if not exists demo_session_issuance_recent_idx
    on demo_session_issuance (issued_at desc);
create index if not exists demo_session_issuance_client_idx
    on demo_session_issuance (client_key, issued_at desc);

comment on table demo_session_issuance is
  'One row per demo-session request. Shared rate-limit state across API '
  'instances, and the only telemetry that a public visitor arrived. Stores a '
  'truncated HMAC of the caller IP, never the IP itself.';

alter table demo_session_issuance enable row level security;
-- No policy: service-role only. Nothing about who visited the demo is public.

select private.attach_demo_guards('public.demo_session_issuance');

-- ── Issuance ─────────────────────────────────────────────────────────────────
-- Ceilings are checked and the attempt recorded in one statement, so two
-- instances racing cannot both pass. The global ceiling matters more than the
-- per-caller one here: every visitor shares a single identity, so an attacker
-- rotating IPs is the expected shape rather than the exceptional one.
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
    v_demo_user uuid;
    v_per_key   integer;
    v_global    integer;
begin
    select demo_enabled, demo_hunt_id into v_enabled, v_hunt from site_settings;

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
        'status',  'issued',
        'user_id', v_demo_user,
        'hunt_id', v_hunt
    );
end $$;

revoke all on function public.issue_demo_session(text, text, integer, integer)
    from public, anon, authenticated;

comment on function public.issue_demo_session(text, text, integer, integer) is
  'Checks the kill switch and both rate ceilings and records the attempt in one '
  'statement, so racing API instances cannot both pass. Service-role only; the '
  'API signs the actual token, this decides whether it may.';
