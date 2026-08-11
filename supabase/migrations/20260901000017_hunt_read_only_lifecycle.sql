-- Archived and Site-Admin-locked Hunt lifecycle.
--
-- The write guard is a trigger rather than another permissive RLS policy: a
-- restrictive policy would still miss SECURITY DEFINER RPCs, while this seam
-- catches every authenticated write no matter which API route issued it.
-- Service-role/Postgres writes are admitted for the worker and the audited
-- Site Admin routers; those callers separately enforce the lifecycle before
-- mutating Hunt-local state.

alter table public.hunts
    add column locked_at timestamptz,
    add column locked_by uuid references auth.users (id) on delete restrict,
    add constraint hunts_lock_shape check (
        (locked_at is null and locked_by is null)
        or (locked_at is not null and locked_by is not null)
    );

comment on column public.hunts.locked_at is
    'Site Admin lock. Non-null makes the Hunt read-only for every principal until an audited unlock.';
comment on column public.hunts.locked_by is
    'Site Admin who most recently locked the Hunt; cleared with locked_at on unlock.';

create or replace function private.hunt_accepts_member_writes(p_hunt_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select coalesce(
        (select h.archived_at is null and h.locked_at is null
         from public.hunts h where h.id = p_hunt_id),
        false
    );
$$;

revoke all on function private.hunt_accepts_member_writes(uuid) from public;
grant execute on function private.hunt_accepts_member_writes(uuid) to authenticated, service_role;

create or replace function private.hunt_write_state(p_hunt_id uuid)
returns text
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select case
        when h.id is null then 'missing'
        when h.locked_at is not null then 'locked'
        when h.archived_at is not null then 'archived'
        else 'active'
    end
    from (select p_hunt_id as id) requested
    left join public.hunts h on h.id = requested.id;
$$;

revoke all on function private.hunt_write_state(uuid) from public;
grant execute on function private.hunt_write_state(uuid) to authenticated, service_role;

create or replace function private.guarded_row_hunt_id(
    p_table text,
    p_row jsonb
) returns uuid
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
    v_id uuid;
begin
    if p_table = 'hunts' then
        return nullif(p_row ->> 'id', '')::uuid;
    end if;
    if p_row ? 'hunt_id' and nullif(p_row ->> 'hunt_id', '') is not null then
        return (p_row ->> 'hunt_id')::uuid;
    end if;
    if p_row ? 'hunt_listing_id' and nullif(p_row ->> 'hunt_listing_id', '') is not null then
        select hl.hunt_id into v_id
        from public.hunt_listings hl
        where hl.id = (p_row ->> 'hunt_listing_id')::uuid;
        return v_id;
    end if;
    if p_row ? 'job_id' and nullif(p_row ->> 'job_id', '') is not null then
        select j.hunt_id into v_id
        from public.jobs j
        where j.id = (p_row ->> 'job_id')::uuid;
        return v_id;
    end if;
    if p_row ? 'visit_id' and nullif(p_row ->> 'visit_id', '') is not null then
        select v.hunt_id into v_id
        from public.visits v
        where v.id = (p_row ->> 'visit_id')::uuid;
        return v_id;
    end if;
    if p_row ? 'invitation_link_id'
       and nullif(p_row ->> 'invitation_link_id', '') is not null then
        select il.hunt_id into v_id
        from public.invitation_links il
        where il.id = (p_row ->> 'invitation_link_id')::uuid;
        return v_id;
    end if;
    if p_row ? 'extraction_id' and nullif(p_row ->> 'extraction_id', '') is not null then
        select e.hunt_id into v_id
        from public.extractions e
        where e.id = (p_row ->> 'extraction_id')::uuid;
        return v_id;
    end if;
    if p_row ? 'resolution_extraction_id'
       and nullif(p_row ->> 'resolution_extraction_id', '') is not null then
        select e.hunt_id into v_id
        from public.extractions e
        where e.id = (p_row ->> 'resolution_extraction_id')::uuid;
        return v_id;
    end if;
    return null;
end;
$$;

revoke all on function private.guarded_row_hunt_id(text, jsonb) from public;

create or replace function private.enforce_hunt_read_only()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_row jsonb := case when tg_op = 'DELETE' then to_jsonb(old) else to_jsonb(new) end;
    v_hunt_id uuid;
    v_state text;
    v_old jsonb;
    v_new jsonb;
begin
    -- Worker and audited Site Admin writes use privileged database roles. The
    -- user-facing boundary below still applies to every authenticated RPC,
    -- including SECURITY DEFINER functions.
    if coalesce(auth.role(), '') = 'service_role' or session_user = 'postgres' then
        return case when tg_op = 'DELETE' then old else new end;
    end if;
    -- Cascades from an already-authorized parent deletion must not be blocked
    -- by the archived state of the row that is being removed.
    if tg_op = 'DELETE' and pg_trigger_depth() > 1 then
        return old;
    end if;

    v_hunt_id := private.guarded_row_hunt_id(tg_table_name, v_row);
    -- Global Catalog Extractions have hunt_id NULL and remain global truth.
    if v_hunt_id is null then
        return case when tg_op = 'DELETE' then old else new end;
    end if;
    v_state := private.hunt_write_state(v_hunt_id);

    if tg_table_name = 'hunts' and tg_op = 'DELETE'
       and current_setting('manzil.lifecycle_delete', true) is distinct from 'on' then
        raise exception using
            errcode = '55000',
            message = 'hunt_delete_rpc_required',
            detail = 'Permanently delete an archived Hunt through the confirmation endpoint.';
    end if;

    if tg_table_name = 'hunts' and tg_op = 'UPDATE' then
        v_old := to_jsonb(old) - 'archived_at';
        v_new := to_jsonb(new) - 'archived_at';
        -- The Owner archive/restore RPC changes exactly archived_at and sets a
        -- transaction-local bypass while cancelling Jobs.
        if current_setting('manzil.lifecycle_transition', true) = 'on'
           and v_old = v_new then
            return new;
        end if;
        if old.archived_at is distinct from new.archived_at then
            raise exception using
                errcode = '55000',
                message = 'hunt_lifecycle_rpc_required',
                detail = 'Archive and restore a Hunt through the lifecycle endpoint.';
        end if;
    end if;
    if current_setting('manzil.lifecycle_transition', true) = 'on'
       and tg_table_name = 'jobs' then
        return case when tg_op = 'DELETE' then old else new end;
    end if;
    if current_setting('manzil.lifecycle_delete', true) = 'on' then
        return case when tg_op = 'DELETE' then old else new end;
    end if;

    if v_state = 'locked' then
        raise exception using
            errcode = '55000',
            message = 'hunt_locked',
            detail = 'This Hunt is locked by a Site Admin and is read-only.';
    elsif v_state = 'archived' then
        raise exception using
            errcode = '55000',
            message = 'hunt_archived_read_only',
            detail = 'This Hunt is archived and is read-only.';
    end if;
    return case when tg_op = 'DELETE' then old else new end;
end;
$$;

revoke all on function private.enforce_hunt_read_only() from public;

-- Every user- or RPC-writable Hunt-owned relation. History/tombstone tables
-- are intentionally absent: their internal audit triggers must still append.
do $$
declare
    v_table text;
begin
    foreach v_table in array array[
        'hunts', 'hunt_members', 'invites', 'invitation_links',
        'invitation_link_joins', 'hunt_listings', 'rubric_criteria',
        'hunt_shared_filters', 'overrides', 'fee_checklist', 'scores',
        'comments', 'ratings', 'jobs', 'job_events', 'job_stage_costs',
        'utility_overrides', 'listing_unit_group_states',
        'hunt_listing_refresh_status', 'visits', 'visit_units',
        'visit_custom_items', 'visit_entries', 'visit_defects',
        'visit_fee_proposals', 'extractions', 'extraction_images',
        'extraction_resolution_candidates', 'hunt_notification_prefs'
    ] loop
        if to_regclass('public.' || v_table) is not null then
            execute format('drop trigger if exists hunt_read_only_guard on public.%I', v_table);
            execute format(
                'create trigger hunt_read_only_guard before insert or update or delete on public.%I '
                'for each row execute function private.enforce_hunt_read_only()',
                v_table
            );
        end if;
    end loop;
end;
$$;

create or replace function public.set_hunt_archived(
    p_hunt_id uuid,
    p_archived boolean
) returns public.hunts
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_hunt public.hunts;
begin
    perform private.assert_not_demo('set_hunt_archived');
    select * into v_hunt from public.hunts where id = p_hunt_id for update;
    if not found or v_hunt.owner_id <> auth.uid() then
        raise exception using errcode = '42501', message = 'hunt_not_found';
    end if;
    if v_hunt.locked_at is not null then
        raise exception using errcode = '55000', message = 'hunt_locked';
    end if;

    perform set_config('manzil.lifecycle_transition', 'on', true);
    update public.hunts
    set archived_at = case when p_archived then coalesce(archived_at, now()) else null end
    where id = p_hunt_id
    returning * into v_hunt;

    if p_archived then
        update public.jobs
        set state = 'cancelled',
            finished_at = coalesce(finished_at, now()),
            locked_by = null,
            locked_at = null,
            error = coalesce(error, 'Cancelled because the Hunt was archived')
        where hunt_id = p_hunt_id
          and state in ('queued', 'running', 'waiting_user');
    end if;
    return v_hunt;
end;
$$;

revoke all on function public.set_hunt_archived(uuid, boolean) from public;
grant execute on function public.set_hunt_archived(uuid, boolean) to authenticated;

create or replace function private.hunt_deletion_impact(p_hunt_id uuid)
returns jsonb
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select jsonb_build_object(
        'hunt_id', h.id,
        'name', h.name,
        'members', (select count(*) from public.hunt_members where hunt_id = h.id),
        'listings', (select count(*) from public.hunt_listings where hunt_id = h.id),
        'jobs', (select count(*) from public.jobs where hunt_id = h.id),
        'visits', (select count(*) from public.visits where hunt_id = h.id)
    )
    from public.hunts h where h.id = p_hunt_id;
$$;

revoke all on function private.hunt_deletion_impact(uuid) from public;

create or replace function public.get_hunt_deletion_impact(p_hunt_id uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
    v_hunt public.hunts;
begin
    select * into v_hunt from public.hunts where id = p_hunt_id;
    if not found or v_hunt.owner_id <> auth.uid() then
        raise exception using errcode = '42501', message = 'hunt_not_found';
    end if;
    if v_hunt.locked_at is not null then
        raise exception using errcode = '55000', message = 'hunt_locked';
    end if;
    if v_hunt.archived_at is null then
        raise exception using errcode = '55000', message = 'hunt_not_archived';
    end if;
    return private.hunt_deletion_impact(p_hunt_id);
end;
$$;

revoke all on function public.get_hunt_deletion_impact(uuid) from public;
grant execute on function public.get_hunt_deletion_impact(uuid) to authenticated;

create or replace function public.delete_hunt_permanently(
    p_hunt_id uuid,
    p_confirmation_name text
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_hunt public.hunts;
    v_impact jsonb;
begin
    perform private.assert_not_demo('delete_hunt_permanently');
    select * into v_hunt from public.hunts where id = p_hunt_id for update;
    if not found or v_hunt.owner_id <> auth.uid() then
        raise exception using errcode = '42501', message = 'hunt_not_found';
    end if;
    if v_hunt.locked_at is not null then
        raise exception using errcode = '55000', message = 'hunt_locked';
    end if;
    if v_hunt.archived_at is null then
        raise exception using errcode = '55000', message = 'hunt_not_archived';
    end if;
    if p_confirmation_name is distinct from v_hunt.name then
        raise exception using errcode = '22023', message = 'hunt_confirmation_mismatch';
    end if;
    if exists (select 1 from public.site_settings where demo_hunt_id = p_hunt_id) then
        raise exception using errcode = '55000', message = 'hunt_deletion_blocked',
            detail = 'The selected Demo Hunt cannot be deleted.';
    end if;
    perform 1 from public.jobs where hunt_id = p_hunt_id
        and state in ('queued', 'running', 'waiting_user') for update;
    if found then
        raise exception using errcode = '55000', message = 'hunt_deletion_blocked',
            detail = 'Active Jobs must finish or be cancelled first.';
    end if;

    v_impact := private.hunt_deletion_impact(p_hunt_id);
    perform set_config('manzil.lifecycle_delete', 'on', true);
    delete from public.hunts where id = p_hunt_id;
    return v_impact;
end;
$$;

revoke all on function public.delete_hunt_permanently(uuid, text) from public;
grant execute on function public.delete_hunt_permanently(uuid, text) to authenticated;

-- Hunt state has to invalidate every open Hunt shell immediately. Development
-- resets recreate the publication, while deployed databases may already have
-- the relation because it was added manually during a preview rollout.
do $$
begin
    if not exists (
        select 1
        from pg_publication_tables
        where pubname = 'supabase_realtime'
          and schemaname = 'public'
          and tablename = 'hunts'
    ) then
        alter publication supabase_realtime add table public.hunts;
    end if;
end;
$$;
