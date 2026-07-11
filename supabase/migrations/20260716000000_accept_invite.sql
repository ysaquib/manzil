-- Service-role-only atomic invite acceptance. The API validates the caller JWT,
-- then passes that verified user id through privileged.py.
create or replace function public.accept_hunt_invite(p_token text, p_user_id uuid)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
    v_invite invites;
    v_color text;
    v_palette text[] := array['dusk','clay','moss','ochre','brick','olive','stone','plum'];
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
    v_color := coalesce(v_color, v_palette[1]);
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
