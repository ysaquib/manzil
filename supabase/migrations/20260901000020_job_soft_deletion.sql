-- Retain Job cost/timeline truth while removing deleted work from product views.

alter table public.jobs
    add column if not exists requested_by uuid,
    add column if not exists deleted_at timestamptz,
    add column if not exists deleted_by uuid,
    add column if not exists deleted_from_state public.job_state;

alter table public.jobs
    add constraint jobs_deleted_shape check (
        (state <> 'deleted' and deleted_at is null and deleted_by is null
         and deleted_from_state is null)
        or
        (state = 'deleted' and deleted_at is not null and deleted_by is not null
         and deleted_from_state in ('failed', 'cancelled', 'done'))
    );

update public.jobs j
   set requested_by = hl.added_by
  from public.hunt_listings hl
 where hl.id = j.hunt_listing_id and j.type = 'ingest' and j.requested_by is null;

create index jobs_visible_hunt_created_idx
    on public.jobs (hunt_id, created_at desc) where state <> 'deleted';

grant select (requested_by, deleted_at, deleted_by, deleted_from_state)
    on public.jobs to authenticated;

create or replace function private.jobs_attribute_requester()
returns trigger language plpgsql set search_path = public
as $$
begin
    if new.requested_by is null and auth.uid() is not null then
        new.requested_by := auth.uid();
    end if;
    return new;
end $$;

create trigger jobs_attribute_requester before insert on public.jobs
for each row execute function private.jobs_attribute_requester();

create or replace function public.delete_failed_job(p_job_id uuid)
returns jsonb
language plpgsql security definer set search_path = public, private
as $$
declare
    v_job public.jobs;
    v_listing public.hunt_listings;
    v_owner uuid;
    v_locked_at timestamptz;
    v_archived_at timestamptz;
    v_removed_listing boolean := false;
    v_property_id uuid;
begin
    select * into v_job from public.jobs where id = p_job_id for update;
    if not found then raise exception 'job_not_found' using errcode = 'P0002'; end if;
    select owner_id, locked_at, archived_at
      into v_owner, v_locked_at, v_archived_at
      from public.hunts where id = v_job.hunt_id;
    if v_job.state = 'deleted' then
        raise exception 'job_already_deleted' using errcode = '22023';
    end if;
    if v_job.state <> 'failed' then
        raise exception 'job_not_failed' using errcode = '22023';
    end if;
    if v_locked_at is not null then raise exception 'hunt_locked' using errcode = '55000'; end if;
    if v_archived_at is not null then
        raise exception 'hunt_archived' using errcode = '55000';
    end if;

    if v_job.hunt_listing_id is not null then
        select * into v_listing from public.hunt_listings where id = v_job.hunt_listing_id;
    end if;
    if auth.uid() is null or (
        auth.uid() <> v_owner
        and auth.uid() is distinct from v_job.requested_by
        and (v_listing.id is null or auth.uid() <> v_listing.added_by)
    ) then
        raise exception 'job_delete_permission_denied' using errcode = '42501';
    end if;

    if v_job.type = 'ingest' and v_job.hunt_listing_id is not null
       and v_listing.submitted_source_id is null
       and not exists (select 1 from public.property_sources ps
                        where ps.property_id = v_listing.property_id)
       and not exists (select 1 from public.scores s where s.hunt_listing_id = v_listing.id)
       and not exists (
           select 1 from public.jobs other where other.hunt_listing_id = v_listing.id
             and other.id <> v_job.id and other.state <> 'deleted'
       ) then
        v_property_id := v_listing.property_id;
        update public.jobs set hunt_listing_id = null where id = v_job.id;
        delete from public.hunt_listings where id = v_listing.id;
        v_removed_listing := true;
        delete from public.properties p where p.id = v_property_id
          and not exists (select 1 from public.hunt_listings hl where hl.property_id = p.id)
          and not exists (select 1 from public.property_sources ps where ps.property_id = p.id);
    end if;

    update public.jobs set state = 'deleted', deleted_at = now(), deleted_by = auth.uid(),
        deleted_from_state = 'failed', locked_by = null, locked_at = null
     where id = p_job_id returning * into v_job;

    return jsonb_build_object(
        'job_id', v_job.id, 'deleted_at', v_job.deleted_at,
        'deleted_from_state', v_job.deleted_from_state,
        'removed_placeholder_listing', v_removed_listing,
        'retained_cost_usd', v_job.cost_actual_usd
    );
end $$;

revoke all on function public.delete_failed_job(uuid) from public, anon;
grant execute on function public.delete_failed_job(uuid) to authenticated;
