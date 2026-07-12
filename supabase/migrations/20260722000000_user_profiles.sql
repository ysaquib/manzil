-- Account-level identity inherited by Hunt memberships unless they carry an override.
create table user_profiles (
    user_id uuid primary key references auth.users (id) on delete cascade,
    default_display_name text not null check (
        char_length(btrim(default_display_name)) between 1 and 80
        and default_display_name = btrim(default_display_name)
    ),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table user_profiles enable row level security;

create policy user_profiles_self_select
    on user_profiles for select to authenticated
    using (user_id = auth.uid());
create policy user_profiles_shared_hunt_select
    on user_profiles for select to authenticated
    using (exists (
        select 1
        from hunt_members mine
        join hunt_members theirs on theirs.hunt_id = mine.hunt_id
        where mine.user_id = auth.uid() and theirs.user_id = user_profiles.user_id
    ));
create policy user_profiles_self_insert
    on user_profiles for insert to authenticated
    with check (user_id = auth.uid());
create policy user_profiles_self_update
    on user_profiles for update to authenticated
    using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Existing membership names retain their meaning as explicit Hunt overrides.
comment on column hunt_members.display_name is
    'Nullable Hunt-specific display-name override; null inherits user_profiles.default_display_name';

create or replace function private.inherit_default_member_name()
returns trigger language plpgsql security definer set search_path = public
as $$
begin
    -- Onboarding runs before any protected join/create flow. Membership INSERTs
    -- inherit the account default; only a later explicit UPDATE creates an override.
    if exists (select 1 from user_profiles where user_id = new.user_id) then
        new.display_name := null;
    end if;
    return new;
end;
$$;
create trigger hunt_members_inherit_default_name
before insert on hunt_members for each row execute function private.inherit_default_member_name();

create or replace function private.snapshot_invitation_join_name()
returns trigger language plpgsql security definer set search_path = public
as $$
begin
    select default_display_name into new.display_name
    from user_profiles where user_id = new.user_id;
    new.display_name := coalesce(new.display_name, 'Member');
    return new;
end;
$$;
create trigger invitation_link_joins_snapshot_default_name
before insert on invitation_link_joins for each row
execute function private.snapshot_invitation_join_name();

create or replace function private.touch_user_profile()
returns trigger language plpgsql as $$
begin new.updated_at := now(); return new; end;
$$;
create trigger user_profiles_touch_updated_at
before update on user_profiles for each row execute function private.touch_user_profile();
