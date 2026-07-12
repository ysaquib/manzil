-- Managed, reusable Invitation Links (DESIGN v3.0, §9.1).
-- Email invites remain in `invites`; legacy link-only invites are migrated below.
create table invitation_links (
    id          uuid primary key default gen_random_uuid(),
    hunt_id     uuid not null references hunts (id) on delete cascade,
    token       text not null unique,
    created_by  uuid not null,
    created_at  timestamptz not null default now(),
    name        text,
    max_uses    integer check (max_uses is null or max_uses >= 1),
    expires_at  timestamptz not null,
    deleted_at  timestamptz,
    deleted_by  uuid,
    check ((deleted_at is null) = (deleted_by is null)),
    check (name is null or (char_length(name) between 1 and 80 and name = btrim(name)))
);

create index invitation_links_hunt_id_idx on invitation_links (hunt_id);
create index invitation_links_token_active_idx
    on invitation_links (token) where deleted_at is null;

create table invitation_link_joins (
    invitation_link_id uuid not null references invitation_links (id) on delete cascade,
    user_id            uuid not null,
    display_name       text not null,
    joined_at          timestamptz not null default now(),
    primary key (invitation_link_id, user_id)
);

create index invitation_link_joins_link_joined_idx
    on invitation_link_joins (invitation_link_id, joined_at);

alter table invitation_links enable row level security;
alter table invitation_link_joins enable row level security;

create policy invitation_links_owner_select
    on invitation_links for select to authenticated
    using (private.member_role(hunt_id) = 'owner');
create policy invitation_links_owner_insert
    on invitation_links for insert to authenticated
    with check (
        private.member_role(hunt_id) = 'owner'
        and created_by = auth.uid()
        and deleted_at is null
        and deleted_by is null
    );
create policy invitation_links_owner_update
    on invitation_links for update to authenticated
    using (private.member_role(hunt_id) = 'owner')
    with check (
        private.member_role(hunt_id) = 'owner'
        and (deleted_by is null or deleted_by = auth.uid())
    );
create policy invitation_link_joins_owner_select
    on invitation_link_joins for select to authenticated
    using (
        exists (
            select 1 from invitation_links il
            where il.id = invitation_link_id
              and private.member_role(il.hunt_id) = 'owner'
        )
    );

-- RLS controls rows, not columns. Keep direct user-JWT updates constrained to
-- the same mutable surface as the API, and make soft deletion irreversible.
create function private.guard_invitation_link_update()
returns trigger
language plpgsql
as $$
begin
    if new.id <> old.id
       or new.hunt_id <> old.hunt_id
       or new.token <> old.token
       or new.created_by <> old.created_by
       or new.created_at <> old.created_at then
        raise exception 'immutable Invitation Link field';
    end if;
    if old.deleted_at is not null
       and (new.deleted_at is distinct from old.deleted_at
            or new.deleted_by is distinct from old.deleted_by) then
        raise exception 'deleted Invitation Link is immutable';
    end if;
    return new;
end;
$$;

create trigger invitation_links_guard_update
before update on invitation_links
for each row execute function private.guard_invitation_link_update();

-- Old link-only invites had no creation/join timestamps. Preserve their tokens,
-- expiry and single-use behavior; migration time is the explicit compatibility
-- fallback for those unavailable historical timestamps.
insert into invitation_links
    (id, hunt_id, token, created_by, created_at, max_uses, expires_at)
select id, hunt_id, token, created_by, now(), 1, expires_at
from invites
where email is null;

insert into invitation_link_joins
    (invitation_link_id, user_id, display_name, joined_at)
select i.id, i.accepted_by, coalesce(hm.display_name, 'Member'), now()
from invites i
left join hunt_members hm
  on hm.hunt_id = i.hunt_id and hm.user_id = i.accepted_by
where i.email is null and i.accepted_by is not null;

delete from invites where email is null;
alter table invites alter column email set not null;

-- Service-role-only atomic Invitation Link join. The API authenticates the
-- caller, then passes the verified user id through privileged.py.
create or replace function public.join_hunt_invitation_link(p_token text, p_user_id uuid)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
    v_link invitation_links;
    v_color text;
    v_display_name text := 'Member';
    v_use_count integer;
    v_inserted integer;
    v_palette text[] := array['dusk','clay','moss','ochre','brick','olive','stone','plum'];
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
    v_color := coalesce(v_color, v_palette[1]);

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
