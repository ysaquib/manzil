-- AD-F hardening: keep the raw cross-Hunt union outside the exposed schema.
--
-- The original public view had to run with its owner's privileges so a
-- non-member Site Admin could see through the source tables' RLS. That made a
-- single view predicate the entire cross-tenant boundary and left SELECT on
-- the raw relation available to every PostgREST role. The union now has no
-- caller-aware gate and is therefore private and grantless. Each public access
-- path supplies its own, narrower authorization boundary.

create or replace view private.hunt_activity_all
with (security_barrier = true) as
with events as (
    select
        hl.hunt_id,
        h.recorded_at                                    as occurred_at,
        h.entered_by                                     as actor_id,
        'fee_set'::text                                  as kind,
        'hunt_listing'::text                             as subject_type,
        h.hunt_listing_id                                as subject_id,
        p.name                                           as subject_label,
        jsonb_build_object('fee_slot', h.fee_slot, 'amount', h.amount,
                           'value_state', h.value_state) as detail
    from public.fee_checklist_history h
    join public.hunt_listings hl on hl.id = h.hunt_listing_id
    join public.properties p on p.id = hl.property_id

    union all

    select
        hl.hunt_id, o.created_at, o.user_id,
        'override_set', 'hunt_listing', o.hunt_listing_id, p.name,
        jsonb_build_object('criterion_key', o.criterion_key, 'value', o.value,
                           'target_scope', o.target_scope, 'note', o.note)
    from public.overrides o
    join public.hunt_listings hl on hl.id = o.hunt_listing_id
    join public.properties p on p.id = hl.property_id

    union all

    select
        m.hunt_id, m.recorded_at, m.actor_id,
        'member_' || m.action, 'user', m.user_id,
        up.default_display_name,
        jsonb_build_object('role', m.role, 'user_id', m.user_id)
    from public.hunt_member_history m
    left join public.user_profiles up on up.user_id = m.user_id

    union all

    select
        hl.hunt_id, lh.recorded_at, lh.actor_id,
        'listing_curated', 'hunt_listing', lh.hunt_listing_id, p.name,
        jsonb_build_object('status', lh.status, 'source_policy', lh.source_policy)
    from public.hunt_listing_history lh
    join public.hunt_listings hl on hl.id = lh.hunt_listing_id
    join public.properties p on p.id = hl.property_id

    union all

    select
        t.hunt_id, t.deleted_at, t.deleted_by,
        'deleted', t.entity_type, t.entity_id, t.label,
        t.detail || jsonb_build_object('via_cascade', t.via_cascade)
    from public.deletion_tombstones t
    where t.hunt_id is not null

    union all

    select
        v.hunt_id, v.created_at, v.created_by,
        'visit_created', 'visit', v.id, p.name,
        jsonb_build_object('scheduled_for', v.scheduled_for)
    from public.visits v
    join public.properties p on p.id = v.property_id

    union all

    select
        v.hunt_id, v.ended_at, v.created_by,
        'visit_ended', 'visit', v.id, p.name, '{}'::jsonb
    from public.visits v
    join public.properties p on p.id = v.property_id
    where v.ended_at is not null

    union all

    select
        v.hunt_id, d.created_at, d.created_by,
        'defect_logged', 'visit', d.visit_id, d.title,
        jsonb_build_object('severity', d.severity, 'from_item_key', d.from_item_key)
    from public.visit_defects d
    join public.visits v on v.id = d.visit_id
    where d.deleted_at is null

    union all

    select
        j.hunt_id, j.finished_at, null::uuid,
        'job_' || j.state::text, 'job', j.id, p.name,
        jsonb_build_object('type', j.type, 'cost_usd', j.cost_actual_usd,
                           'error', j.error)
    from public.jobs j
    left join public.hunt_listings hl on hl.id = j.hunt_listing_id
    left join public.properties p on p.id = hl.property_id
    where j.finished_at is not null and j.state in ('done', 'failed')
)
select *
from events
where occurred_at is not null;

comment on view private.hunt_activity_all is
    'Internal, derived activity union. No client role has SELECT. Owners use '
    'public.get_hunt_activity; Site Admins use the admin API after its live '
    'AdminUser check.';

revoke all on private.hunt_activity_all from public, anon, authenticated;

-- Remove the raw public relation entirely. Keeping it as a compatibility view
-- would preserve the broad SELECT surface this migration is intended to close.
drop view if exists public.hunt_activity;

create or replace function public.get_hunt_activity(
    p_hunt_id uuid,
    p_limit integer default 100,
    p_before timestamptz default null
)
returns table (
    hunt_id uuid,
    occurred_at timestamptz,
    actor_id uuid,
    kind text,
    subject_type text,
    subject_id uuid,
    subject_label text,
    detail jsonb
)
language plpgsql
stable
security definer
set search_path = public, private, pg_temp
as $$
begin
    if private.member_role(p_hunt_id) is distinct from 'owner'::public.hunt_role then
        raise exception 'only the Hunt Owner may read its activity feed'
            using errcode = '42501';
    end if;

    return query
    select
        a.hunt_id,
        a.occurred_at,
        a.actor_id,
        a.kind,
        a.subject_type,
        a.subject_id,
        a.subject_label,
        a.detail
    from private.hunt_activity_all a
    where a.hunt_id = p_hunt_id
      and (p_before is null or a.occurred_at < p_before)
    order by a.occurred_at desc
    limit least(greatest(coalesce(p_limit, 100), 1), 500);
end;
$$;

comment on function public.get_hunt_activity(uuid, integer, timestamptz) is
    'Bounded Owner-only activity feed. Site Admin access intentionally stays '
    'behind the audited admin API instead of sharing this public RPC.';

revoke all on function public.get_hunt_activity(uuid, integer, timestamptz)
    from public, anon;
grant execute on function public.get_hunt_activity(uuid, integer, timestamptz)
    to authenticated;

-- Migration-time assertions make a later default-grant or ownership surprise
-- fail closed instead of shipping a public raw relation again.
do $$
begin
    if to_regclass('public.hunt_activity') is not null then
        raise exception 'public.hunt_activity must not exist';
    end if;
    if has_table_privilege('anon', 'private.hunt_activity_all', 'select')
       or has_table_privilege('authenticated', 'private.hunt_activity_all', 'select') then
        raise exception 'client role can read private.hunt_activity_all';
    end if;
end;
$$;
