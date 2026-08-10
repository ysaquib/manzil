-- Permanent Hunt Listing deletion (DESIGN v3.68).
--
-- A Listing is Hunt-local opinion over a globally shared Property. Permanent
-- deletion therefore removes the Hunt association and everything owned by it,
-- but never the Property, its Sources/Floor Plans/images, or another Hunt's
-- Listing. The only survivors in this Hunt are the deliberately minimal
-- deletion tombstone and (for Ghost View) the Admin Audit Log row.

-- A Visit has always required this Hunt/Property Listing pair. Make that
-- invariant structural so a concurrent Visit INSERT cannot race a Listing
-- delete and commit an orphan. The existing unique(hunt_id, property_id) on
-- hunt_listings is the referenced key.
alter table visits
    add constraint visits_hunt_listing_fkey
    foreign key (hunt_id, property_id)
    references hunt_listings (hunt_id, property_id)
    on delete cascade;

create or replace function private.record_hunt_listing_tombstone()
returns trigger language plpgsql security definer set search_path = ''
as $$
declare
    v_cascade boolean := not exists (
        select 1 from public.hunts where id = old.hunt_id
    );
begin
    -- The permanent-delete function pre-writes a richer row. Hunt-cascade
    -- deletion reaches only this generic backstop. The Listing row lock makes
    -- the existence check race-free without imposing a uniqueness rule on the
    -- older polymorphic tombstone ledger.
    if exists (
        select 1 from public.deletion_tombstones t
        where t.entity_type = 'hunt_listing'
          and t.entity_id = old.id
          and t.hunt_id = old.hunt_id
    ) then
        return old;
    end if;
    insert into public.deletion_tombstones (
        entity_type, entity_id, hunt_id, label, via_cascade, deleted_by, detail
    )
    values (
        'hunt_listing', old.id, old.hunt_id,
        (select name from public.properties where id = old.property_id),
        v_cascade, auth.uid(),
        jsonb_build_object('property_id', old.property_id, 'status', old.status)
    );
    return old;
end;
$$;

-- The impact object is used by the confirmation UI, the deletion receipt and
-- the tombstone. It groups related rows rather than exposing deleted content.
create or replace function private.listing_deletion_impact(p_listing_id uuid)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    with listing as (
        select hl.id, hl.hunt_id, hl.property_id, hl.status, p.name as property_name
        from public.hunt_listings hl
        join public.properties p on p.id = hl.property_id
        where hl.id = p_listing_id
    ), listing_jobs as (
        select j.id, j.state from public.jobs j where j.hunt_listing_id = p_listing_id
    ), listing_visits as (
        select v.id
        from public.visits v
        join listing l on l.hunt_id = v.hunt_id and l.property_id = v.property_id
    )
    select jsonb_build_object(
        'listing_id', l.id,
        'property_id', l.property_id,
        'property_name', l.property_name,
        'status', l.status,
        'active_jobs', (
            select count(*) from listing_jobs
            where state in ('queued', 'running', 'waiting_user')
        ),
        'counts', jsonb_build_object(
            'unit_groups', (
                select count(*) from (
                    select distinct fp.beds, fp.baths
                    from public.floor_plans fp
                    where fp.property_id = l.property_id
                      and fp.is_current
                      and fp.beds is not null
                      and fp.baths is not null
                ) groups
            ),
            'scores', (
                select count(*) from public.scores s where s.hunt_listing_id = l.id
            ),
            'manual_values',
                (select count(*) from public.overrides o where o.hunt_listing_id = l.id)
              + (select count(*) from public.utility_overrides u where u.hunt_listing_id = l.id)
              + (select count(*) from public.fee_checklist f where f.hunt_listing_id = l.id)
              + (select count(*) from public.fee_checklist_history f where f.hunt_listing_id = l.id),
            'collaboration_records',
                (select count(*) from public.comments c where c.hunt_listing_id = l.id)
              + (select count(*) from public.ratings r where r.hunt_listing_id = l.id)
              + (select count(*) from public.listing_unit_group_states s where s.hunt_listing_id = l.id),
            'task_records',
                (select count(*) from listing_jobs)
              + (select count(*) from public.job_events e where e.job_id in (select id from listing_jobs))
              + (select count(*) from public.job_stage_costs c where c.job_id in (select id from listing_jobs))
              + (select count(*) from public.hunt_listing_refresh_status r where r.hunt_listing_id = l.id)
              + (select count(*) from public.hunt_listing_history h where h.hunt_listing_id = l.id),
            'visits', (select count(*) from listing_visits),
            'visit_records',
                (select count(*) from public.visit_units u where u.visit_id in (select id from listing_visits))
              + (select count(*) from public.visit_custom_items i where i.visit_id in (select id from listing_visits))
              + (select count(*) from public.visit_entries e where e.visit_id in (select id from listing_visits))
              + (select count(*) from public.visit_defects d where d.visit_id in (select id from listing_visits))
              + (select count(*) from public.visit_fee_proposals p where p.visit_id in (select id from listing_visits)),
            'hunt_scoped_extractions', (
                select count(*) from public.extractions e
                where e.hunt_id = l.hunt_id and e.property_id = l.property_id
            )
        )
    )
    from listing l
$$;

-- One core for the Owner RPC and the audited service-role Ghost View route.
-- It is private and has no authenticated grant: only the checked public wrapper
-- and the API's database connection may reach it.
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
        if exists (
            select 1 from public.hunt_members hm
            where hm.hunt_id = v_listing.hunt_id and hm.user_id = p_actor_id
        ) then
            raise exception 'ghost_view_unavailable' using errcode = '42501';
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

    -- Custom-Criterion facts are Hunt-scoped but attach to Hunt + Property, not
    -- the Listing row, so they are the one truth-store cleanup not supplied by
    -- an FK from hunt_listings.
    delete from public.extractions e
    where e.hunt_id = v_listing.hunt_id and e.property_id = v_listing.property_id;

    -- Existing child FKs remove all Listing-local records. The new composite
    -- Visit FK removes the whole tour subtree in the same statement.
    delete from public.hunt_listings hl where hl.id = v_listing.id;

    return v_impact;
end;
$$;

create or replace function public.get_listing_deletion_impact(p_listing_id uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_hunt_id uuid;
    v_impact jsonb;
begin
    perform private.assert_not_demo('public.get_listing_deletion_impact(uuid)');
    select hunt_id into v_hunt_id
    from public.hunt_listings where id = p_listing_id;
    if not found or private.member_role(v_hunt_id) is distinct from 'owner'::public.hunt_role then
        raise exception 'listing_not_found' using errcode = 'P0002';
    end if;
    v_impact := private.listing_deletion_impact(p_listing_id);
    return v_impact;
end;
$$;

create or replace function public.delete_listing_permanently(
    p_listing_id uuid,
    p_confirmation_name text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
begin
    perform private.assert_not_demo('public.delete_listing_permanently(uuid,text)');
    return private.delete_hunt_listing_permanently(
        p_listing_id, auth.uid(), p_confirmation_name, false
    );
end;
$$;

revoke all on function private.listing_deletion_impact(uuid) from public, anon, authenticated;
revoke all on function private.delete_hunt_listing_permanently(uuid, uuid, text, boolean)
    from public, anon, authenticated;
revoke all on function public.get_listing_deletion_impact(uuid) from public, anon;
revoke all on function public.delete_listing_permanently(uuid, text) from public, anon;
grant execute on function public.get_listing_deletion_impact(uuid) to authenticated;
grant execute on function public.delete_listing_permanently(uuid, text) to authenticated;

-- Direct table DELETE used to be Owner-authorized even though the API called
-- it "archive". Remove that bypass: permanent deletion must pass the archived,
-- confirmation, active-Job, Visit and custom-Extraction controls above.
drop policy if exists hunt_listings_owner_delete on hunt_listings;

-- The old broad UPDATE policies let a direct PostgREST caller change columns
-- more freely than the API's role checks. Keep the existing policies as the
-- coarse row gate, then enforce the exact column/action matrix in one trigger.
create or replace function private.enforce_hunt_listing_update_rules()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_role public.hunt_role;
    v_old_source_cap integer;
    v_new_source_cap integer;
begin
    -- Worker/service-role projections have no JWT subject and remain allowed.
    if auth.uid() is null then
        return new;
    end if;

    v_role := private.member_role(old.hunt_id);

    if (to_jsonb(new) - array['status', 'source_policy', 'single_source_reason', 'pins'])
       is distinct from
       (to_jsonb(old) - array['status', 'source_policy', 'single_source_reason', 'pins']) then
        raise exception 'Listing identity and projection columns are not client-editable'
            using errcode = '42501';
    end if;

    if new.status is distinct from old.status and v_role is distinct from 'owner' then
        raise exception 'Only the Hunt Owner may archive or restore Listings'
            using errcode = '42501';
    end if;
    if new.pins is distinct from old.pins
       and v_role is distinct from 'owner'
       and v_role is distinct from 'curator'
       and (v_role is distinct from 'member' or old.added_by <> auth.uid()) then
        raise exception 'Members may pin Floor Plans only on their own Listings'
            using errcode = '42501';
    end if;
    if new.source_policy is distinct from old.source_policy
       and v_role is distinct from 'owner'
       and old.added_by <> auth.uid() then
        raise exception 'Only the Listing submitter or Hunt Owner may change Source Policy'
            using errcode = '42501';
    end if;

    -- `set_listing_source_policy` updates this assurance field in the same
    -- statement. Require its full deterministic transition even when a direct
    -- PostgREST caller changes only source_policy and leaves a stale reason.
    if new.source_policy is distinct from old.source_policy then
        v_old_source_cap := case old.source_policy
            when 'trust_link' then 0 when 'tier_1' then 1
            when 'tier_1_plus_official' then 1 when 'tiers_1_2' then 2 else 3 end;
        v_new_source_cap := case new.source_policy
            when 'trust_link' then 0 when 'tier_1' then 1
            when 'tier_1_plus_official' then 1 when 'tiers_1_2' then 2 else 3 end;
        if new.source_policy = 'trust_link' then
            if new.single_source_reason is distinct from 'trust_link' then
                raise exception 'Invalid Single-Source reason transition'
                    using errcode = '42501';
            end if;
        elsif v_new_source_cap > v_old_source_cap then
            if new.single_source_reason is not null then
                raise exception 'Invalid Single-Source reason transition'
                    using errcode = '42501';
            end if;
        elsif new.single_source_reason is distinct from old.single_source_reason then
            raise exception 'Invalid Single-Source reason transition'
                using errcode = '42501';
        end if;
    elsif new.single_source_reason is distinct from old.single_source_reason then
        raise exception 'Single-Source reason is not client-editable'
            using errcode = '42501';
    end if;

    return new;
end;
$$;

create trigger hunt_listings_enforce_update_rules
before update on hunt_listings
for each row execute function private.enforce_hunt_listing_update_rules();

-- Migration-time assertions: neither a future policy edit nor a forgotten
-- grant may reopen the two bypasses this migration closes.
do $$
begin
    if exists (
        select 1 from pg_policies
        where schemaname = 'public' and tablename = 'hunt_listings' and cmd = 'DELETE'
    ) then
        raise exception 'hunt_listings must not expose a direct DELETE policy';
    end if;
    if has_function_privilege(
        'authenticated',
        'private.delete_hunt_listing_permanently(uuid,uuid,text,boolean)',
        'EXECUTE'
    ) then
        raise exception 'authenticated must not execute the private deletion core';
    end if;
end;
$$;
