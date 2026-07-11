-- P2-8: service-role-only atomic ownership transfer. No user-JWT policy can move
-- the 'owner' role (RLS + one_owner_per_hunt), so transfer runs here, privileged.
-- The API validates the caller is the current Owner, then passes the verified ids.
create or replace function public.transfer_hunt_ownership(p_hunt_id uuid, p_new_owner_id uuid)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
    v_current_owner uuid;
begin
    -- Lock the current Owner membership row. Under READ COMMITTED a racing
    -- transfer may still see no qualifying row after this commits; the
    -- one_owner_per_hunt unique index, not this lock, guarantees the invariant.
    select user_id into v_current_owner
    from hunt_members
    where hunt_id = p_hunt_id and role = 'owner'
    for update;

    -- Target is already the Owner → idempotent no-op.
    if v_current_owner = p_new_owner_id then
        return jsonb_build_object('status', 'ok');
    end if;

    -- Target must already be a member of the Hunt.
    if not exists (
        select 1 from hunt_members
        where hunt_id = p_hunt_id and user_id = p_new_owner_id
    ) then
        return jsonb_build_object('status', 'not_member');
    end if;

    -- Demote first, then promote — one_owner_per_hunt never sees two Owners.
    update hunt_members set role = 'curator'
    where hunt_id = p_hunt_id and user_id = v_current_owner;
    update hunt_members set role = 'owner'
    where hunt_id = p_hunt_id and user_id = p_new_owner_id;
    update hunts set owner_id = p_new_owner_id where id = p_hunt_id;

    return jsonb_build_object('status', 'ok');
end;
$$;
revoke all on function public.transfer_hunt_ownership(uuid, uuid) from public, anon, authenticated;
grant execute on function public.transfer_hunt_ownership(uuid, uuid) to service_role;
