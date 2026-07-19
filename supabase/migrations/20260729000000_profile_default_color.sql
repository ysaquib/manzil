-- Account-level default member color, propagated exactly like
-- default_display_name (migration 20260722000000): hunt_members.color null
-- inherits user_profiles.default_color; a non-null membership color is a
-- Hunt-specific override. Collaboration palette is the six theme-backed
-- tokens (moss…plum); dusk/clay were never registered after the theme rename.
-- Onboarding omits default_color; a BEFORE INSERT trigger assigns the first
-- globally unused token, wrapping from the start when all six are taken.

alter table user_profiles add column default_color text;

comment on column hunt_members.color is
    'Nullable Hunt-specific color override; null inherits user_profiles.default_color';

-- Backfill existing profiles in creation order before the NOT NULL / check.
do $$
declare
    v_palette text[] := array['moss','ochre','brick','olive','stone','plum'];
    r record;
    i integer := 0;
begin
    for r in
        select user_id from user_profiles order by created_at, user_id
    loop
        update user_profiles
        set default_color = v_palette[(i % array_length(v_palette, 1)) + 1]
        where user_id = r.user_id;
        i := i + 1;
    end loop;
end;
$$;

alter table user_profiles
    alter column default_color set not null,
    add constraint user_profiles_default_color_check check (
        default_color in ('moss', 'ochre', 'brick', 'olive', 'stone', 'plum')
        or default_color ~ '^#[0-9A-F]{6}$'
    );

-- Atomic global assignment for new profiles (advisory lock serializes concurrent
-- onboarding). Callers may still pass an explicit token or custom hex.
create or replace function private.assign_default_profile_color()
returns trigger language plpgsql security definer set search_path = public
as $$
declare
    v_palette text[] := array['moss','ochre','brick','olive','stone','plum'];
    v_color text;
    v_count integer;
begin
    if new.default_color is not null then
        return new;
    end if;
    perform pg_advisory_xact_lock(hashtext('user_profiles.default_color'));
    select candidate into v_color
    from unnest(v_palette) with ordinality as p(candidate, position)
    where not exists (
        select 1 from user_profiles up where up.default_color = candidate
    )
    order by position
    limit 1;
    if v_color is null then
        select count(*) into v_count from user_profiles;
        v_color := v_palette[(v_count % array_length(v_palette, 1)) + 1];
    end if;
    new.default_color := v_color;
    return new;
end;
$$;

create trigger user_profiles_assign_default_color
before insert on user_profiles
for each row execute function private.assign_default_profile_color();

-- Membership INSERTs inherit account defaults (name always; color when a
-- default exists — always, once default_color is required).
create or replace function private.inherit_default_member_name()
returns trigger language plpgsql security definer set search_path = public
as $$
begin
    -- Onboarding runs before any protected join/create flow. Membership INSERTs
    -- inherit the account default; only a later explicit UPDATE creates an override.
    if exists (select 1 from user_profiles where user_id = new.user_id) then
        new.display_name := null;
        new.color := null;
    end if;
    return new;
end;
$$;

-- Email-invite acceptance: six-token palette, first unused in the Hunt, wrap.
create or replace function public.accept_hunt_invite(p_token text, p_user_id uuid)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
    v_invite invites;
    v_color text;
    v_count integer;
    v_palette text[] := array['moss','ochre','brick','olive','stone','plum'];
begin
    select * into v_invite from invites where token = p_token for update;
    if not found then return jsonb_build_object('status', 'gone'); end if;
    if exists (select 1 from hunt_members where hunt_id = v_invite.hunt_id and user_id = p_user_id) then
        return jsonb_build_object('status', 'member', 'hunt_id', v_invite.hunt_id);
    end if;
    if v_invite.accepted_by is not null then
        return jsonb_build_object('status', 'accepted');
    end if;
    if v_invite.expires_at <= now() then
        return jsonb_build_object('status', 'expired');
    end if;
    select candidate into v_color
    from unnest(v_palette) with ordinality as p(candidate, position)
    where not exists (
        select 1 from hunt_members hm
        where hm.hunt_id = v_invite.hunt_id and hm.color = candidate
    ) order by position limit 1;
    if v_color is null then
        select count(*) into v_count
        from hunt_members where hunt_id = v_invite.hunt_id;
        v_color := v_palette[(v_count % array_length(v_palette, 1)) + 1];
    end if;
    insert into hunt_members (hunt_id, user_id, role, color, display_name)
    values (
        v_invite.hunt_id, p_user_id, v_invite.role_granted, v_color,
        coalesce(nullif(split_part(v_invite.email, '@', 1), ''), 'Member')
    );
    update invites set accepted_by = p_user_id where id = v_invite.id;
    return jsonb_build_object('status', 'ok', 'hunt_id', v_invite.hunt_id);
end;
$$;
revoke all on function public.accept_hunt_invite(text, uuid) from public, anon, authenticated;
grant execute on function public.accept_hunt_invite(text, uuid) to service_role;

-- Invitation Link join: same six-token order and wrap within the Hunt.
create or replace function public.join_hunt_invitation_link(p_token text, p_user_id uuid)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
    v_link invitation_links;
    v_color text;
    v_display_name text := 'Member';
    v_use_count integer;
    v_member_count integer;
    v_inserted integer;
    v_palette text[] := array['moss','ochre','brick','olive','stone','plum'];
begin
    select * into v_link
    from invitation_links
    where token = p_token
    for update;

    if not found then
        return jsonb_build_object('status', 'not_found');
    end if;
    if v_link.deleted_at is not null then
        return jsonb_build_object('status', 'deleted');
    end if;
    if v_link.expires_at <= now() then
        return jsonb_build_object('status', 'expired');
    end if;

    select count(*) into v_use_count
    from invitation_link_joins
    where invitation_link_id = v_link.id;
    if v_link.max_uses is not null and v_use_count >= v_link.max_uses then
        return jsonb_build_object('status', 'exhausted');
    end if;

    if exists (
        select 1 from hunt_members
        where hunt_id = v_link.hunt_id and user_id = p_user_id
    ) then
        return jsonb_build_object('status', 'member', 'hunt_id', v_link.hunt_id);
    end if;

    select candidate into v_color
    from unnest(v_palette) with ordinality as p(candidate, position)
    where not exists (
        select 1 from hunt_members hm
        where hm.hunt_id = v_link.hunt_id and hm.color = candidate
    ) order by position limit 1;
    if v_color is null then
        select count(*) into v_member_count
        from hunt_members where hunt_id = v_link.hunt_id;
        v_color := v_palette[(v_member_count % array_length(v_palette, 1)) + 1];
    end if;

    insert into hunt_members (hunt_id, user_id, role, color, display_name)
    values (v_link.hunt_id, p_user_id, 'member', v_color, v_display_name)
    on conflict (hunt_id, user_id) do nothing;
    get diagnostics v_inserted = row_count;
    if v_inserted = 0 then
        return jsonb_build_object('status', 'member', 'hunt_id', v_link.hunt_id);
    end if;
    insert into invitation_link_joins
        (invitation_link_id, user_id, display_name)
    values (v_link.id, p_user_id, v_display_name);

    return jsonb_build_object('status', 'ok', 'hunt_id', v_link.hunt_id);
end;
$$;

revoke all on function public.join_hunt_invitation_link(text, uuid)
    from public, anon, authenticated;
grant execute on function public.join_hunt_invitation_link(text, uuid) to service_role;
