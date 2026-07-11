-- Owner membership is part of Hunt creation, not a fallible second request.
create or replace function private.add_hunt_owner_membership()
returns trigger
language plpgsql security definer set search_path = public
as $$
begin
    insert into hunt_members (hunt_id, user_id, role)
    values (new.id, new.owner_id, 'owner')
    on conflict (hunt_id, user_id) do nothing;
    return new;
end;
$$;

create trigger hunts_add_owner_membership
after insert on hunts
for each row execute function private.add_hunt_owner_membership();

-- RPC functions called through the Supabase Data API must be in an exposed
-- schema. `public` is safe here because EXECUTE is explicitly restricted and
-- the function derives identity from auth.uid().
create or replace function public.submit_listing(
    p_hunt_id uuid, p_url text, p_placeholder_name text, p_source_policy text
)
returns setof hunt_listings
language plpgsql security definer set search_path = public
as $$
declare
    v_property_id uuid;
    v_listing hunt_listings;
begin
    if auth.uid() is null or private.member_role(p_hunt_id) is null then
        raise exception 'hunt membership required' using errcode = '42501';
    end if;
    if p_source_policy not in (
        'trust_link', 'tier_1', 'tiers_1_2', 'tiers_1_2_3', 'tier_1_plus_official'
    ) then
        raise exception 'invalid source policy' using errcode = '22023';
    end if;
    insert into properties (name, canonical_address)
    values (p_placeholder_name, p_placeholder_name) returning id into v_property_id;
    insert into hunt_listings (hunt_id, property_id, added_by, source_policy)
    values (p_hunt_id, v_property_id, auth.uid(), p_source_policy)
    returning * into v_listing;
    insert into jobs (hunt_id, hunt_listing_id, type, state, payload)
    values (p_hunt_id, v_listing.id, 'ingest', 'queued',
            jsonb_build_object('url', p_url, 'source_policy', p_source_policy));
    return next v_listing;
end;
$$;
revoke all on function public.submit_listing(uuid, text, text, text) from public, anon;
grant execute on function public.submit_listing(uuid, text, text, text) to authenticated;

create or replace function public.answer_job_checkpoint(
    p_job_id uuid, p_payload jsonb, p_detail jsonb
)
returns setof jobs
language plpgsql security definer set search_path = public
as $$
declare
    v_job jobs;
    v_role hunt_role;
    v_own boolean;
begin
    select * into v_job from jobs where id = p_job_id for update;
    if not found or v_job.state <> 'waiting_user' then
        raise exception 'job is not waiting for a checkpoint' using errcode = '22023';
    end if;
    v_role := private.member_role(v_job.hunt_id);
    select exists (
        select 1 from hunt_listings
        where id = v_job.hunt_listing_id and added_by = auth.uid()
    ) into v_own;
    if v_role is null or (v_role = 'member' and not v_own) then
        raise exception 'checkpoint permission denied' using errcode = '42501';
    end if;
    update jobs set state = 'queued', payload = p_payload
    where id = p_job_id returning * into v_job;
    insert into job_events (job_id, stage, event, detail)
    values (p_job_id, coalesce(v_job.current_stage, 'checkpoint'),
            'checkpoint_answered', p_detail);
    return next v_job;
end;
$$;
revoke all on function public.answer_job_checkpoint(uuid, jsonb, jsonb) from public, anon;
grant execute on function public.answer_job_checkpoint(uuid, jsonb, jsonb) to authenticated;
