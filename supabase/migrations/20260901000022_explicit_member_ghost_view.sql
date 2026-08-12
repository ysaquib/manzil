-- A Site Admin may deliberately enter audited Ghost View from Admin → Hunts
-- even when they also hold a Hunt membership (DESIGN v3.93). The API remains
-- the only caller of this private function and proves Site Admin status first;
-- the function repeats that proof as defense in depth.
create or replace function private.delete_hunt_listing_permanently(
    p_listing_id uuid,
    p_actor_id uuid,
    p_confirmation_name text,
    p_as_site_admin boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_listing public.hunt_listings%rowtype;
    v_property_name text;
    v_impact jsonb;
begin
    select hl.* into v_listing
    from public.hunt_listings hl
    where hl.id = p_listing_id
    for update;

    if not found then
        raise exception 'listing_not_found' using errcode = 'P0002';
    end if;

    if p_as_site_admin then
        if not exists (
            select 1 from public.site_admins sa where sa.user_id = p_actor_id
        ) then
            raise exception 'not_site_admin' using errcode = '42501';
        end if;
    elsif p_actor_id is distinct from auth.uid()
       or private.member_role(v_listing.hunt_id) is distinct from 'owner'::public.hunt_role then
        raise exception 'insufficient_role' using errcode = '42501';
    end if;

    select p.name into v_property_name
    from public.properties p where p.id = v_listing.property_id;

    if v_listing.status <> 'archived' then
        raise exception 'listing_not_archived' using errcode = 'P0001';
    end if;
    if p_confirmation_name is distinct from v_property_name then
        raise exception 'listing_confirmation_mismatch' using errcode = '22023';
    end if;
    if exists (
        select 1 from public.jobs j
        where j.hunt_listing_id = v_listing.id
          and j.state in ('queued', 'running', 'waiting_user')
    ) then
        raise exception 'listing_has_active_jobs' using errcode = '55000';
    end if;

    v_impact := private.listing_deletion_impact(v_listing.id);

    insert into public.deletion_tombstones (
        entity_type, entity_id, hunt_id, label, via_cascade, deleted_by, detail
    )
    values (
        'hunt_listing', v_listing.id, v_listing.hunt_id, v_property_name,
        false, p_actor_id,
        jsonb_build_object(
            'property_id', v_listing.property_id,
            'status', v_listing.status,
            'counts', v_impact -> 'counts'
        )
    );

    delete from public.extractions e
    where e.hunt_id = v_listing.hunt_id and e.property_id = v_listing.property_id;

    delete from public.hunt_listings hl where hl.id = v_listing.id;

    return v_impact;
end;
$$;
