-- P3-22: durable product notifications. Supabase Auth continues to own
-- authentication/security email; these tables back Manzil-owned Hunt mail.

create table public.user_notification_prefs (
    user_id uuid not null references auth.users (id) on delete cascade,
    event_type text not null check (event_type in (
        'checkpoint_waiting', 'run_failed', 'listing_score_changed',
        'comment_added', 'rating_changed'
    )),
    channel text not null check (channel = 'email'),
    enabled boolean not null,
    updated_at timestamptz not null default now(),
    primary key (user_id, event_type, channel)
);

create table public.hunt_notification_prefs (
    hunt_id uuid not null references public.hunts (id) on delete cascade,
    user_id uuid not null references auth.users (id) on delete cascade,
    event_type text not null check (event_type in (
        'checkpoint_waiting', 'run_failed', 'listing_score_changed',
        'comment_added', 'rating_changed'
    )),
    channel text not null check (channel = 'email'),
    enabled boolean not null,
    updated_at timestamptz not null default now(),
    primary key (hunt_id, user_id, event_type, channel)
);

alter table public.user_notification_prefs enable row level security;
alter table public.hunt_notification_prefs enable row level security;

create policy user_notification_prefs_self_select
    on public.user_notification_prefs for select to authenticated
    using (user_id = auth.uid());
create policy user_notification_prefs_self_insert
    on public.user_notification_prefs for insert to authenticated
    with check (user_id = auth.uid());
create policy user_notification_prefs_self_update
    on public.user_notification_prefs for update to authenticated
    using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy user_notification_prefs_self_delete
    on public.user_notification_prefs for delete to authenticated
    using (user_id = auth.uid());

create policy hunt_notification_prefs_self_select
    on public.hunt_notification_prefs for select to authenticated
    using (
        user_id = auth.uid()
        and private.member_role(hunt_id) is not null
    );
create policy hunt_notification_prefs_self_insert
    on public.hunt_notification_prefs for insert to authenticated
    with check (
        user_id = auth.uid()
        and private.member_role(hunt_id) is not null
    );
create policy hunt_notification_prefs_self_update
    on public.hunt_notification_prefs for update to authenticated
    using (
        user_id = auth.uid()
        and private.member_role(hunt_id) is not null
    ) with check (
        user_id = auth.uid()
        and private.member_role(hunt_id) is not null
    );
create policy hunt_notification_prefs_self_delete
    on public.hunt_notification_prefs for delete to authenticated
    using (
        user_id = auth.uid()
        and private.member_role(hunt_id) is not null
    );

select private.attach_demo_guards('public.user_notification_prefs');
select private.attach_demo_guards('public.hunt_notification_prefs');

-- Replace all nullable Hunt overrides in one database transaction. The API
-- submits the complete fixed event map; a five-request delete/upsert loop could
-- otherwise leave a partially saved preference set after a network failure.
create or replace function public.set_hunt_notification_preferences(
    p_hunt_id uuid,
    p_overrides jsonb
) returns void language plpgsql
set search_path = public, private, pg_temp as $$
declare v_user_id uuid := auth.uid();
begin
    if v_user_id is null or private.member_role(p_hunt_id) is null then
        raise exception 'Hunt membership required' using errcode = '42501';
    end if;
    if p_overrides is null or jsonb_typeof(p_overrides) <> 'object'
       or (select array_agg(key order by key)
             from jsonb_object_keys(p_overrides) as keys(key))
          <> array[
              'checkpoint_waiting', 'comment_added', 'listing_score_changed',
              'rating_changed', 'run_failed'
          ]::text[]
       or exists (
          select 1 from jsonb_each(p_overrides)
           where jsonb_typeof(value) not in ('boolean', 'null')
       ) then
        raise exception 'Invalid Hunt notification preference map' using errcode = '22023';
    end if;

    delete from public.hunt_notification_prefs
     where hunt_id = p_hunt_id and user_id = v_user_id and channel = 'email';
    insert into public.hunt_notification_prefs(
        hunt_id, user_id, event_type, channel, enabled, updated_at
    )
    select p_hunt_id, v_user_id, key, 'email', (value #>> '{}')::boolean, now()
      from jsonb_each(p_overrides)
     where jsonb_typeof(value) = 'boolean';
end $$;
revoke all on function public.set_hunt_notification_preferences(uuid, jsonb)
    from public, anon;
grant execute on function public.set_hunt_notification_preferences(uuid, jsonb)
    to authenticated;

create table private.notification_events (
    id uuid primary key default gen_random_uuid(),
    event_type text not null check (event_type in (
        'hunt_invited', 'checkpoint_waiting', 'run_failed',
        'listing_score_changed', 'comment_added', 'rating_changed'
    )),
    hunt_id uuid references public.hunts (id) on delete cascade,
    actor_user_id uuid,
    source_kind text not null,
    source_id uuid not null,
    dedupe_key text not null unique,
    context jsonb not null default '{}',
    created_at timestamptz not null default now()
);

create table private.notification_deliveries (
    id uuid primary key default gen_random_uuid(),
    event_id uuid not null references private.notification_events (id) on delete cascade,
    recipient_user_id uuid references auth.users (id) on delete set null,
    recipient_email text not null,
    channel text not null default 'email' check (channel = 'email'),
    status text not null default 'queued' check (status in (
        'queued', 'sending', 'sent', 'delivered', 'delayed', 'failed',
        'bounced', 'suppressed', 'complained', 'disabled', 'cancelled'
    )),
    attempts integer not null default 0,
    next_attempt_at timestamptz not null default now(),
    locked_by text,
    locked_at timestamptz,
    provider_message_id text unique,
    provider_status_at timestamptz,
    last_error text,
    sent_at timestamptz,
    delivered_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (event_id, recipient_email, channel)
);
create index notification_deliveries_claim_idx
    on private.notification_deliveries (next_attempt_at, created_at)
    where status in ('queued', 'sending');

create table private.notification_webhook_events (
    svix_id text primary key,
    provider_message_id text,
    event_type text not null,
    provider_at timestamptz not null,
    received_at timestamptz not null default now()
);

revoke all on private.notification_events from public, anon, authenticated;
revoke all on private.notification_deliveries from public, anon, authenticated;
revoke all on private.notification_webhook_events from public, anon, authenticated;

create or replace function private.notification_default_enabled(p_event_type text)
returns boolean language sql immutable as $$
    select p_event_type in ('checkpoint_waiting', 'run_failed')
$$;

create or replace function private.notification_enabled(
    p_user_id uuid, p_hunt_id uuid, p_event_type text
) returns boolean language sql stable security definer
set search_path = public, private, auth, pg_temp as $$
    select coalesce(
        (select enabled from public.hunt_notification_prefs
          where hunt_id = p_hunt_id and user_id = p_user_id
            and event_type = p_event_type and channel = 'email'),
        (select enabled from public.user_notification_prefs
          where user_id = p_user_id and event_type = p_event_type and channel = 'email'),
        private.notification_default_enabled(p_event_type)
    )
$$;

create or replace function private.notification_event(
    p_event_type text,
    p_hunt_id uuid,
    p_actor_user_id uuid,
    p_source_kind text,
    p_source_id uuid,
    p_dedupe_key text,
    p_context jsonb
) returns uuid language plpgsql security definer
set search_path = public, private, pg_temp as $$
declare v_id uuid;
begin
    insert into private.notification_events (
        event_type, hunt_id, actor_user_id, source_kind, source_id, dedupe_key, context
    ) values (
        p_event_type, p_hunt_id, p_actor_user_id, p_source_kind, p_source_id,
        p_dedupe_key, coalesce(p_context, '{}'::jsonb)
    ) on conflict (dedupe_key) do nothing returning id into v_id;
    if v_id is null then
        select id into v_id from private.notification_events where dedupe_key = p_dedupe_key;
    end if;
    return v_id;
end $$;

create or replace function private.notification_add_user_delivery(
    p_event_id uuid, p_user_id uuid, p_hunt_id uuid, p_event_type text
) returns void language plpgsql security definer
set search_path = public, private, auth, pg_temp as $$
declare v_email text;
begin
    if not private.notification_enabled(p_user_id, p_hunt_id, p_event_type) then
        return;
    end if;
    select email into v_email from auth.users where id = p_user_id;
    if v_email is null then return; end if;
    insert into private.notification_deliveries(event_id, recipient_user_id, recipient_email)
    values (p_event_id, p_user_id, lower(v_email)) on conflict do nothing;
end $$;

create or replace function private.enqueue_hunt_invitation()
returns trigger language plpgsql security definer
set search_path = public, private, auth, pg_temp as $$
declare v_event uuid; v_hunt_name text; v_inviter text;
begin
    if new.email is null then return new; end if;
    select h.name, coalesce(hm.display_name, up.default_display_name, 'A Manzil Hunt Owner')
      into v_hunt_name, v_inviter
      from public.hunts h
      left join public.hunt_members hm on hm.hunt_id = h.id and hm.user_id = new.created_by
      left join public.user_profiles up on up.user_id = new.created_by
     where h.id = new.hunt_id;
    v_event := private.notification_event(
        'hunt_invited', new.hunt_id, new.created_by, 'invite', new.id,
        'hunt_invited:' || new.id,
        jsonb_build_object('hunt_name', v_hunt_name, 'inviter_name', v_inviter,
                           'role', new.role_granted::text, 'expires_at', new.expires_at)
    );
    insert into private.notification_deliveries(event_id, recipient_email)
    values (v_event, lower(new.email)) on conflict do nothing;
    return new;
end $$;
create trigger invites_enqueue_notification
after insert on public.invites for each row execute function private.enqueue_hunt_invitation();

create or replace function private.cancel_hunt_invitation_delivery()
returns trigger language plpgsql security definer
set search_path = public, private, pg_temp as $$
begin
    update private.notification_deliveries d set status = 'cancelled', updated_at = now()
      from private.notification_events e
     where d.event_id = e.id and e.source_kind = 'invite' and e.source_id = old.id
       and d.status in ('queued', 'sending');
    return old;
end $$;
create trigger invites_cancel_notification
before delete on public.invites for each row execute function private.cancel_hunt_invitation_delivery();

create or replace function private.enqueue_comment_notification()
returns trigger language plpgsql security definer
set search_path = public, private, auth, pg_temp as $$
declare v_event uuid; v_hunt uuid; v_hunt_name text; v_property text; v_actor text; v_member record;
begin
    select hl.hunt_id, h.name, p.name into v_hunt, v_hunt_name, v_property
      from public.hunt_listings hl join public.properties p on p.id = hl.property_id
      join public.hunts h on h.id = hl.hunt_id
     where hl.id = new.hunt_listing_id;
    select coalesce(hm.display_name, up.default_display_name, 'A Hunt member') into v_actor
      from public.hunt_members hm left join public.user_profiles up on up.user_id = hm.user_id
     where hm.hunt_id = v_hunt and hm.user_id = new.user_id;
    v_event := private.notification_event(
        'comment_added', v_hunt, new.user_id, 'comment', new.id,
        'comment_added:' || new.id,
        jsonb_build_object('hunt_name', v_hunt_name, 'property_name', v_property, 'actor_name', v_actor,
                           'listing_id', new.hunt_listing_id,
                           'unit_group_key', new.unit_group_key)
    );
    for v_member in select user_id from public.hunt_members
                     where hunt_id = v_hunt and user_id <> new.user_id loop
        perform private.notification_add_user_delivery(v_event, v_member.user_id, v_hunt, 'comment_added');
    end loop;
    return new;
end $$;
create trigger comments_enqueue_notification
after insert on public.comments for each row execute function private.enqueue_comment_notification();

create or replace function private.enqueue_rating_notification()
returns trigger language plpgsql security definer
set search_path = public, private, auth, pg_temp as $$
declare v_event uuid; v_hunt uuid; v_hunt_name text; v_property text; v_actor text; v_member record;
begin
    if tg_op = 'UPDATE' and new.rating is not distinct from old.rating then return new; end if;
    select hl.hunt_id, h.name, p.name into v_hunt, v_hunt_name, v_property
      from public.hunt_listings hl join public.properties p on p.id = hl.property_id
      join public.hunts h on h.id = hl.hunt_id
     where hl.id = new.hunt_listing_id;
    select coalesce(hm.display_name, up.default_display_name, 'A Hunt member') into v_actor
      from public.hunt_members hm left join public.user_profiles up on up.user_id = hm.user_id
     where hm.hunt_id = v_hunt and hm.user_id = new.user_id;
    v_event := private.notification_event(
        'rating_changed', v_hunt, new.user_id, 'rating', new.hunt_listing_id,
        'rating_changed:' || new.hunt_listing_id || ':' || new.unit_group_key || ':'
            || new.user_id || ':' || new.rating || ':' || txid_current(),
        jsonb_build_object('hunt_name', v_hunt_name, 'property_name', v_property, 'actor_name', v_actor,
                           'listing_id', new.hunt_listing_id, 'unit_group_key', new.unit_group_key,
                           'rating', new.rating)
    );
    for v_member in select user_id from public.hunt_members
                     where hunt_id = v_hunt and user_id <> new.user_id loop
        perform private.notification_add_user_delivery(v_event, v_member.user_id, v_hunt, 'rating_changed');
    end loop;
    return new;
end $$;
create trigger ratings_enqueue_notification
after insert or update of rating on public.ratings
for each row execute function private.enqueue_rating_notification();

create or replace function private.enqueue_checkpoint_notification()
returns trigger language plpgsql security definer
set search_path = public, private, auth, pg_temp as $$
declare v_event uuid; v_job record; v_property text;
begin
    if new.event <> 'checkpoint_asked' then return new; end if;
    select j.hunt_id, j.hunt_listing_id, hl.added_by
      into v_job from public.jobs j
      left join public.hunt_listings hl on hl.id = j.hunt_listing_id where j.id = new.job_id;
    if v_job.added_by is null then return new; end if;
    select p.name into v_property from public.hunt_listings hl
      join public.properties p on p.id = hl.property_id where hl.id = v_job.hunt_listing_id;
    v_event := private.notification_event(
        'checkpoint_waiting', v_job.hunt_id, null, 'job_event', new.id,
        'checkpoint_waiting:' || new.id,
        jsonb_build_object('job_id', new.job_id, 'listing_id', v_job.hunt_listing_id,
                           'property_name', v_property, 'stage', new.stage)
    );
    perform private.notification_add_user_delivery(
        v_event, v_job.added_by, v_job.hunt_id, 'checkpoint_waiting'
    );
    return new;
end $$;
create trigger job_events_enqueue_checkpoint_notification
after insert on public.job_events for each row execute function private.enqueue_checkpoint_notification();

create or replace function private.enqueue_failed_job_notification()
returns trigger language plpgsql security definer
set search_path = public, private, auth, pg_temp as $$
declare v_event uuid; v_submitter uuid; v_owner uuid; v_property text;
begin
    if new.state <> 'failed' or old.state = 'failed' then return new; end if;
    select hl.added_by, p.name into v_submitter, v_property
      from public.hunt_listings hl join public.properties p on p.id = hl.property_id
     where hl.id = new.hunt_listing_id;
    select owner_id into v_owner from public.hunts where id = new.hunt_id;
    v_event := private.notification_event(
        'run_failed', new.hunt_id, null, 'job', new.id, 'run_failed:' || new.id,
        jsonb_build_object('job_id', new.id, 'listing_id', new.hunt_listing_id,
                           'property_name', coalesce(v_property, 'Hunt refresh'),
                           'error', left(coalesce(new.error, 'The run failed.'), 500))
    );
    if v_submitter is not null then
        perform private.notification_add_user_delivery(v_event, v_submitter, new.hunt_id, 'run_failed');
    end if;
    if v_owner is not null and v_owner is distinct from v_submitter then
        perform private.notification_add_user_delivery(v_event, v_owner, new.hunt_id, 'run_failed');
    end if;
    return new;
end $$;
create trigger jobs_enqueue_failure_notification
after update of state on public.jobs for each row execute function private.enqueue_failed_job_notification();

-- Worker seam: a successful Job may report one already-aggregated Listing
-- score change. The worker owns comparison; this function owns durable fan-out.
create or replace function private.enqueue_score_change_notification(
    p_job_id uuid, p_hunt_listing_id uuid, p_changes jsonb
) returns uuid language plpgsql security definer
set search_path = public, private, auth, pg_temp as $$
declare v_event uuid; v_hunt uuid; v_submitter uuid; v_property text;
begin
    select hl.hunt_id, hl.added_by, p.name into v_hunt, v_submitter, v_property
      from public.hunt_listings hl join public.properties p on p.id = hl.property_id
     where hl.id = p_hunt_listing_id;
    if v_hunt is null or coalesce(jsonb_array_length(p_changes), 0) = 0 then return null; end if;
    v_event := private.notification_event(
        'listing_score_changed', v_hunt, null, 'job', p_job_id,
        'listing_score_changed:' || p_job_id || ':' || p_hunt_listing_id,
        jsonb_build_object('job_id', p_job_id, 'listing_id', p_hunt_listing_id,
                           'property_name', v_property, 'changes', p_changes)
    );
    perform private.notification_add_user_delivery(
        v_event, v_submitter, v_hunt, 'listing_score_changed'
    );
    return v_event;
end $$;
revoke all on function private.enqueue_score_change_notification(uuid, uuid, jsonb)
    from public, anon, authenticated;

-- `private` has authenticated USAGE because RLS predicates call a small set of
-- explicitly granted helpers. PostgreSQL grants EXECUTE on new functions to
-- PUBLIC by default, so every outbox helper must be revoked explicitly: none
-- is a browser/RPC surface.
revoke all on function private.notification_default_enabled(text)
    from public, anon, authenticated;
revoke all on function private.notification_enabled(uuid, uuid, text)
    from public, anon, authenticated;
revoke all on function private.notification_event(text, uuid, uuid, text, uuid, text, jsonb)
    from public, anon, authenticated;
revoke all on function private.notification_add_user_delivery(uuid, uuid, uuid, text)
    from public, anon, authenticated;
revoke all on function private.enqueue_hunt_invitation()
    from public, anon, authenticated;
revoke all on function private.cancel_hunt_invitation_delivery()
    from public, anon, authenticated;
revoke all on function private.enqueue_comment_notification()
    from public, anon, authenticated;
revoke all on function private.enqueue_rating_notification()
    from public, anon, authenticated;
revoke all on function private.enqueue_checkpoint_notification()
    from public, anon, authenticated;
revoke all on function private.enqueue_failed_job_notification()
    from public, anon, authenticated;
