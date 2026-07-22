-- P3-5: why this Listing lacks cross-Source corroboration. Nullable means the
-- baseline slate has at least one sibling. `discover_failed` is distinct from
-- `discover_exhausted`: provider/budget failure must not be presented as proof
-- that no other site lists the Property.
alter table hunt_listings
    add column single_source_reason text check (
        single_source_reason in ('trust_link', 'discover_exhausted', 'discover_failed')
    );

comment on column hunt_listings.single_source_reason is
    'P3-5 assurance state: explicit trust_link, no sibling found, or discovery unavailable.';

-- Change one Listing's policy atomically with any DISCOVER refresh it unlocks.
-- Relaxation here means a higher sibling tier cap (including leaving
-- trust_link). Enabling the official-site carve-out is metadata-only because
-- DISCOVER finds the official link under every non-trust policy; P3-6 later
-- decides whether unresolved facts warrant fetching that arbiter. Previously known
-- Sources remain append-only but later planning obeys the new cap.
create or replace function public.set_listing_source_policy(
    p_listing_id uuid, p_source_policy text
)
returns setof hunt_listings
language plpgsql security definer set search_path = public
as $$
declare
    v_listing hunt_listings;
    v_old_cap integer;
    v_new_cap integer;
    v_relaxed boolean;
    v_url text;
begin
    if p_source_policy not in (
        'trust_link', 'tier_1', 'tiers_1_2', 'tiers_1_2_3', 'tier_1_plus_official'
    ) then
        raise exception 'invalid source policy' using errcode = '22023';
    end if;

    select * into v_listing from hunt_listings where id = p_listing_id for update;
    if not found then
        raise exception 'listing not found' using errcode = 'P0002';
    end if;
    if private.member_role(v_listing.hunt_id) is null
       or (private.member_role(v_listing.hunt_id) <> 'owner'
           and v_listing.added_by <> auth.uid()) then
        raise exception 'source policy permission denied' using errcode = '42501';
    end if;

    v_old_cap := case v_listing.source_policy
        when 'trust_link' then 0 when 'tier_1' then 1
        when 'tier_1_plus_official' then 1 when 'tiers_1_2' then 2 else 3 end;
    v_new_cap := case p_source_policy
        when 'trust_link' then 0 when 'tier_1' then 1
        when 'tier_1_plus_official' then 1 when 'tiers_1_2' then 2 else 3 end;
    v_relaxed := v_new_cap > v_old_cap;

    update hunt_listings set
        source_policy = p_source_policy,
        single_source_reason = case
            when p_source_policy = 'trust_link' then 'trust_link'
            when v_relaxed then null
            else single_source_reason
        end
    where id = p_listing_id
    returning * into v_listing;

    if v_relaxed then
        select payload ->> 'url' into v_url
        from jobs
        where hunt_listing_id = p_listing_id and type = 'ingest'
          and payload ? 'url'
        order by created_at asc
        limit 1;
        if v_url is null then
            raise exception 'listing has no submitted source URL' using errcode = '22023';
        end if;
        insert into jobs (hunt_id, hunt_listing_id, type, state, payload)
        values (
            v_listing.hunt_id,
            p_listing_id,
            'refresh',
            'queued',
            jsonb_build_object(
                'hunt_id', v_listing.hunt_id,
                'listing_id', p_listing_id,
                'url', v_url,
                'scope', 'discover',
                'source_policy', p_source_policy
            )
        );
    end if;
    return next v_listing;
end;
$$;

revoke all on function public.set_listing_source_policy(uuid, text) from public, anon;
grant execute on function public.set_listing_source_policy(uuid, text) to authenticated;
