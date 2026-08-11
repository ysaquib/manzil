-- Former-member attribution (DESIGN v3.76).
--
-- Removing a Hunt membership ends access immediately, but it does not erase
-- collaboration history.  Capture the effective Hunt-visible name at removal
-- time and expose only the small attribution projection that remaining members
-- need to render that history honestly.  The governance tables themselves stay
-- Owner-only.

create or replace function private.record_hunt_member_tombstone()
returns trigger language plpgsql security definer set search_path = public
as $$
declare
    v_default_name text;
    v_default_color text;
begin
    select default_display_name, default_color
    into v_default_name, v_default_color
    from user_profiles
    where user_id = old.user_id;

    insert into deletion_tombstones (
        entity_type, entity_id, hunt_id, label, via_cascade, deleted_by, detail
    )
    values (
        'hunt_member', old.user_id, old.hunt_id,
        coalesce(
            nullif(btrim(old.display_name), ''),
            nullif(btrim(v_default_name), ''),
            'Unknown'
        ),
        not exists (select 1 from hunts where id = old.hunt_id),
        auth.uid(),
        jsonb_build_object(
            'role', old.role,
            'color', coalesce(old.color, v_default_color)
        )
    );
    return old;
end;
$$;

-- Current members and former contributors are deliberately different concepts:
-- callers still read hunt_members for the roster and use this function only for
-- bylines, rating dots, Visit answers, and other retained attribution.
create or replace function public.get_hunt_contributor_identities(p_hunt_id uuid)
returns table (
    user_id uuid,
    display_name text,
    color text,
    is_former boolean
)
language plpgsql
stable
security definer
set search_path = public, private, pg_temp
as $$
begin
    if private.member_role(p_hunt_id) is null and not private.is_site_admin() then
        raise exception 'Hunt membership required'
            using errcode = '42501';
    end if;

    return query
    select
        hm.user_id,
        coalesce(hm.display_name, up.default_display_name, 'Member') as display_name,
        coalesce(hm.color, up.default_color) as color,
        false as is_former
    from hunt_members hm
    left join user_profiles up on up.user_id = hm.user_id
    where hm.hunt_id = p_hunt_id

    union all

    select
        departed.entity_id as user_id,
        coalesce(
            nullif(
                btrim(
                    case
                        when departed.label in ('Member', 'Unknown') then null
                        else departed.label
                    end
                ),
                ''
            ),
            nullif(btrim(up.default_display_name), ''),
            'Unknown'
        ) as display_name,
        null::text as color,
        true as is_former
    from (
        select distinct on (entity_id) entity_id, label
        from deletion_tombstones
        where hunt_id = p_hunt_id and entity_type = 'hunt_member'
        order by entity_id, deleted_at desc, id desc
    ) departed
    left join user_profiles up on up.user_id = departed.entity_id
    where not exists (
        select 1
        from hunt_members current_member
        where current_member.hunt_id = p_hunt_id
          and current_member.user_id = departed.entity_id
    );
end;
$$;

revoke all on function public.get_hunt_contributor_identities(uuid)
    from public, anon, authenticated;
grant execute on function public.get_hunt_contributor_identities(uuid)
    to authenticated;

-- Remaining members must replace the departed person's current identity with
-- the tombstoned one without a reload.  RLS still decides which subscribers
-- receive each row event.
alter publication supabase_realtime add table hunt_members;
