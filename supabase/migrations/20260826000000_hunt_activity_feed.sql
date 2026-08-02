-- Hunt activity feed (AD-F, DESIGN §20 v3.40) + the Site Admin identity
-- primitive it depends on.
--
-- A **pure derived read**. There is no new write path and no new event table:
-- every row here already exists in a domain table that was append-only before
-- this migration, so the feed cannot drift from the truth it reports. That is
-- the whole reason it is a view — a materialized "activity" table would be a
-- second copy of history, and once the copy disagrees you have to decide which
-- to believe.
--
-- `site_admins` lands here rather than in AD-1 because the feed's stated
-- visibility (Owners and Site Admins) cannot be expressed without it. AD-1
-- builds the router, the JWT claim and the audit log on top.

-- ─────────────────────────────────────────────────────────────────────────────
-- Site Admin identity
-- ─────────────────────────────────────────────────────────────────────────────
-- A dedicated table, never a column on `user_profiles`: that table is readable
-- by anyone sharing a Hunt, so a flag there would publish the admin roster to
-- every collaborator. This one has no SELECT policy at all — the same posture
-- as `feedback`.
create table site_admins (
    user_id    uuid primary key references auth.users (id) on delete cascade,
    -- The first admin is the system owner and has no grantor.
    granted_by uuid references auth.users (id) on delete set null,
    granted_at timestamptz not null default now(),
    note       text,
    -- The primordial row: the owner of the Manzil application itself. Exactly
    -- one may exist, and no path may revoke it. This — not the "don't revoke
    -- yourself" rule — is what makes locking everyone out of the panel
    -- impossible, because self-revocation guards still fall to two admins
    -- removing each other.
    is_primordial boolean not null default false
);

create unique index site_admins_one_primordial_idx
    on site_admins (is_primordial) where is_primordial;

comment on table site_admins is
    'Account-level operators (AD-1), orthogonal to hunt_role. No SELECT policy: '
    'read it with service_role. The primordial row is immutable by trigger.';

alter table site_admins enable row level security;
-- No policies whatsoever: authenticated clients can neither read nor write this
-- table. Granting admin is an admin-router operation running as service_role.

create or replace function private.is_site_admin(u uuid default auth.uid())
returns boolean language sql stable security definer set search_path = public
as $$
    select exists (select 1 from site_admins where user_id = u);
$$;

comment on function private.is_site_admin(uuid) is
    'True when the user is a Site Admin. SECURITY DEFINER because the caller has '
    'no SELECT privilege on site_admins.';

-- The immutability guard. A BEFORE trigger rather than a policy, because
-- service_role bypasses RLS entirely — and service_role is precisely what the
-- admin router runs as, so a policy would guard everyone except the one caller
-- that can actually do the damage.
create or replace function private.protect_primordial_admin()
returns trigger language plpgsql
as $$
begin
    if tg_op = 'DELETE' then
        if old.is_primordial then
            raise exception 'the primordial site admin cannot be revoked'
                using errcode = '42501';
        end if;
        return old;
    end if;
    -- UPDATE: the flag itself may never move, in either direction. Clearing it
    -- would otherwise be a two-step delete.
    if old.is_primordial is distinct from new.is_primordial then
        raise exception 'site_admins.is_primordial is immutable'
            using errcode = '42501';
    end if;
    return new;
end;
$$;

create trigger site_admins_protect_primordial
before update or delete on site_admins
for each row execute function private.protect_primordial_admin();

-- ─────────────────────────────────────────────────────────────────────────────
-- The feed
-- ─────────────────────────────────────────────────────────────────────────────
-- ACCESS CONTROL LIVES IN THIS VIEW'S WHERE CLAUSE. It is deliberately NOT a
-- `security_invoker` view: a non-member Site Admin would be filtered out by the
-- base tables' member-scoped policies and see an empty feed, which is the exact
-- opposite of the requirement. The gate below is therefore load-bearing —
-- **removing or weakening the final WHERE turns this into a full cross-tenant
-- leak.** It is one predicate in one place, which is why the whole feed is a
-- single view rather than eight endpoints.
--
-- Individual Visit Entries are deliberately absent. They are append-only and
-- attributed, so they *could* be listed — but a tour is 248 questions answered
-- by named people, and replaying "who rated the kitchen 2/5, then changed it"
-- turns a collaboration record into a behavioural log. §9.7 averages per member
-- precisely so no one's volume dominates; the feed reports that a tour happened
-- and what red flags came out of it, not how each person filled it in.
create view hunt_activity as
with events as (
    -- Money: a fee moving is the single most score-relevant manual act.
    select
        hl.hunt_id,
        h.recorded_at                                    as occurred_at,
        h.entered_by                                     as actor_id,
        'fee_set'                                        as kind,
        'hunt_listing'                                   as subject_type,
        h.hunt_listing_id                                as subject_id,
        p.name                                           as subject_label,
        jsonb_build_object('fee_slot', h.fee_slot, 'amount', h.amount,
                           'value_state', h.value_state) as detail
    from fee_checklist_history h
    join hunt_listings hl on hl.id = h.hunt_listing_id
    join properties p on p.id = hl.property_id

    union all

    -- Manual value corrections. Already append-only with an author since P1.
    select
        hl.hunt_id, o.created_at, o.user_id,
        'override_set', 'hunt_listing', o.hunt_listing_id, p.name,
        jsonb_build_object('criterion_key', o.criterion_key, 'value', o.value,
                           'target_scope', o.target_scope, 'note', o.note)
    from overrides o
    join hunt_listings hl on hl.id = o.hunt_listing_id
    join properties p on p.id = hl.property_id

    union all

    -- Governance.
    select
        m.hunt_id, m.recorded_at, m.actor_id,
        'member_' || m.action, 'user', m.user_id,
        up.default_display_name,
        jsonb_build_object('role', m.role, 'user_id', m.user_id)
    from hunt_member_history m
    left join user_profiles up on up.user_id = m.user_id

    union all

    -- Curation: archive/restore, Source Policy, pins.
    select
        hl.hunt_id, lh.recorded_at, lh.actor_id,
        'listing_curated', 'hunt_listing', lh.hunt_listing_id, p.name,
        jsonb_build_object('status', lh.status, 'source_policy', lh.source_policy)
    from hunt_listing_history lh
    join hunt_listings hl on hl.id = lh.hunt_listing_id
    join properties p on p.id = hl.property_id

    union all

    -- What stopped existing. Cascaded children are included but flagged, so a
    -- reader can collapse one Hunt deletion instead of scrolling 200 lines.
    select
        t.hunt_id, t.deleted_at, t.deleted_by,
        'deleted', t.entity_type, t.entity_id, t.label,
        t.detail || jsonb_build_object('via_cascade', t.via_cascade)
    from deletion_tombstones t
    where t.hunt_id is not null

    union all

    -- Tours. The Visit itself, not its 248 answers (see the note above).
    select
        v.hunt_id, v.created_at, v.created_by,
        'visit_created', 'visit', v.id, p.name,
        jsonb_build_object('scheduled_for', v.scheduled_for)
    from visits v
    join properties p on p.id = v.property_id

    union all

    select
        v.hunt_id, v.ended_at, v.created_by,
        'visit_ended', 'visit', v.id, p.name, '{}'::jsonb
    from visits v
    join properties p on p.id = v.property_id
    where v.ended_at is not null

    union all

    -- A red flag is the output of a tour that someone will act on.
    select
        v.hunt_id, d.created_at, d.created_by,
        'defect_logged', 'visit', d.visit_id, d.title,
        jsonb_build_object('severity', d.severity, 'from_item_key', d.from_item_key)
    from visit_defects d
    join visits v on v.id = d.visit_id
    where d.deleted_at is null

    union all

    -- Pipeline outcomes only. Per-stage chatter stays in `job_events`, which is
    -- already the right place to read it.
    select
        j.hunt_id, j.finished_at, null::uuid,
        'job_' || j.state::text, 'job', j.id, p.name,
        jsonb_build_object('type', j.type, 'cost_usd', j.cost_actual_usd,
                           'error', j.error)
    from jobs j
    left join hunt_listings hl on hl.id = j.hunt_listing_id
    left join properties p on p.id = hl.property_id
    where j.finished_at is not null and j.state in ('done', 'failed')
)
select *
from events
-- ↓↓↓ THE GATE. See the note above before touching this. ↓↓↓
where occurred_at is not null
  and (private.member_role(hunt_id) = 'owner' or private.is_site_admin());

comment on view hunt_activity is
    'Derived hunt-scoped activity timeline (AD-F). No backing table: every row is '
    'read live from an append-only domain table. Visible to the Hunt Owner and to '
    'Site Admins ONLY — the gate is the view''s own WHERE clause, because a '
    'security_invoker view would hide everything from a non-member admin.';

-- Owners read their own Hunt's feed constantly; admins scan across Hunts.
create index if not exists overrides_created_idx on overrides (created_at desc);
create index if not exists jobs_finished_idx on jobs (finished_at desc)
    where finished_at is not null;
