-- DESIGN v3.4: ratings belong to Unit Group rows; comments may optionally
-- target one Unit Group and expose edit history.

create function private.unit_group_key(p_beds integer, p_baths numeric)
returns text
language sql
immutable
set search_path = ''
as $$
    select p_beds::text || '-' || rtrim(rtrim(p_baths::text, '0'), '.')
$$;

create function private.listing_has_unit_group(
    p_hunt_listing_id uuid,
    p_unit_group_key text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.hunt_listings hl
        join public.floor_plans fp on fp.property_id = hl.property_id
        where hl.id = p_hunt_listing_id
          and private.unit_group_key(fp.beds, fp.baths) = p_unit_group_key
    )
$$;

alter table comments
    add column unit_group_key text,
    add column edited_at timestamptz,
    add constraint comments_unit_group_key_format check (
        unit_group_key is null or unit_group_key ~ '^[0-9]+-[0-9]+(\.[0-9]+)?$'
    );

-- A Listing-wide rating was previously rendered on every Unit Group row. Copy
-- it to every currently present Unit Group before making scope mandatory.
create temporary table ratings_per_unit_group on commit drop as
select distinct
    r.hunt_listing_id,
    private.unit_group_key(fp.beds, fp.baths) as unit_group_key,
    r.user_id,
    r.rating
from ratings r
join hunt_listings hl on hl.id = r.hunt_listing_id
join floor_plans fp on fp.property_id = hl.property_id;

delete from ratings;
alter table ratings drop constraint ratings_pkey;
alter table ratings add column unit_group_key text not null;
alter table ratings add constraint ratings_unit_group_key_format check (
    unit_group_key ~ '^[0-9]+-[0-9]+(\.[0-9]+)?$'
);
alter table ratings add primary key (hunt_listing_id, unit_group_key, user_id);

insert into ratings (hunt_listing_id, unit_group_key, user_id, rating)
select hunt_listing_id, unit_group_key, user_id, rating
from ratings_per_unit_group;

create index comments_hunt_listing_unit_group_idx
    on comments (hunt_listing_id, unit_group_key)
    where deleted_at is null;

drop policy comments_member_insert on comments;
create policy comments_member_insert
    on comments for insert to authenticated
    with check (
        user_id = auth.uid()
        and (unit_group_key is null or private.listing_has_unit_group(
            hunt_listing_id, unit_group_key
        ))
        and exists (
            select 1 from hunt_listings hl
            where hl.id = comments.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );

drop policy comments_author_update on comments;
create policy comments_author_update
    on comments for update to authenticated
    using (user_id = auth.uid())
    with check (
        user_id = auth.uid()
        and (unit_group_key is null or private.listing_has_unit_group(
            hunt_listing_id, unit_group_key
        ))
        and exists (
            select 1 from hunt_listings hl
            where hl.id = comments.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );

drop policy ratings_self_insert on ratings;
create policy ratings_self_insert
    on ratings for insert to authenticated
    with check (
        user_id = auth.uid()
        and private.listing_has_unit_group(hunt_listing_id, unit_group_key)
        and exists (
            select 1 from hunt_listings hl
            where hl.id = ratings.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );

drop policy ratings_self_update on ratings;
create policy ratings_self_update
    on ratings for update to authenticated
    using (user_id = auth.uid())
    with check (
        user_id = auth.uid()
        and private.listing_has_unit_group(hunt_listing_id, unit_group_key)
        and exists (
            select 1 from hunt_listings hl
            where hl.id = ratings.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );

alter publication supabase_realtime add table ratings;
