-- Product feedback (P3-16, DESIGN §20 v3.27): category + description submitted
-- from anywhere in the app, carrying the context that makes a two-line report
-- actionable — the route the reporter was on (including the Drawer params), the
-- Hunt, the build, and the browser.
--
-- **Insert-only for every authenticated caller.** There is deliberately no
-- SELECT policy — not even for a submitter's own rows — and no UPDATE or DELETE
-- policy at all. Reads belong to an operator holding `service_role`; a feedback
-- table its submitters can read is a support inbox nobody built, and the two
-- postures have very different privacy properties once several people share a
-- Hunt. RLS is the boundary: hiding the table in the UI would not be.

create table feedback (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    -- Vocabulary is pinned here rather than in the API so a direct PostgREST
    -- insert cannot invent a category the eventual admin view has no column for.
    category text not null check (
        category in ('bug', 'feature', 'confusing', 'wrong_data', 'other')
    ),
    body text not null check (
        char_length(btrim(body)) between 1 and 4000
        and body = btrim(body)
    ),
    -- Where the reporter was. Path + query only; the API strips the origin, so
    -- this never becomes a place to smuggle an arbitrary URL into an admin view.
    route text check (char_length(route) <= 500),
    -- Null outside a Hunt (switcher, account settings). ON DELETE SET NULL keeps
    -- the report after its Hunt is gone — the bug it describes usually outlives
    -- the Hunt it was found in.
    hunt_id uuid references hunts (id) on delete set null,
    app_version text check (char_length(app_version) <= 100),
    user_agent text check (char_length(user_agent) <= 500),
    created_at timestamptz not null default now()
);

comment on table feedback is
    'Admin-only product feedback. Authenticated INSERT with user_id = auth.uid(); '
    'no SELECT/UPDATE/DELETE policy exists — read it with service_role.';

-- Serves both the rate-limit trigger's lookup and the eventual admin view's
-- "newest first, optionally by reporter" read.
create index feedback_user_created_idx on feedback (user_id, created_at desc);

alter table feedback enable row level security;

create policy feedback_self_insert
    on feedback for insert to authenticated
    with check (user_id = auth.uid());

-- Rate limit lives in the database, not the API process: it survives restarts,
-- stays correct if the API is ever run with more than one worker, and cannot be
-- bypassed by a direct PostgREST insert. SECURITY DEFINER because the caller
-- has no SELECT privilege on the very rows being counted.
create or replace function private.enforce_feedback_rate_limit()
returns trigger language plpgsql security definer set search_path = public
as $$
declare
    v_recent integer;
begin
    select count(*) into v_recent
    from feedback
    where user_id = new.user_id and created_at > now() - interval '1 hour';

    if v_recent >= 10 then
        -- 53400 = configuration_limit_exceeded; the API maps it to 429 rather
        -- than letting it read as a generic permission failure.
        raise exception 'feedback rate limit exceeded' using errcode = '53400';
    end if;
    return new;
end;
$$;

create trigger feedback_rate_limit
before insert on feedback
for each row execute function private.enforce_feedback_rate_limit();
