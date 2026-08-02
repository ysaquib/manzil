-- The SELECT-only admin read predicate (AD-4, DESIGN §20 v3.43).
--
-- This is the "narrow A" half of the access model ruled in v3.39. Admin
-- *writes* stay in the service-role router where they can be audited; only
-- *reads* widen, and only here, so the existing Hunt screens serve a Site Admin
-- unmodified instead of needing a parallel implementation.
--
-- **SELECT ONLY.** Not one INSERT, UPDATE or DELETE policy is touched by this
-- migration, and none should ever be. A Site Admin who could write through
-- PostgREST would be a Site Admin whose writes never reach `admin_audit_log` —
-- which is the entire reason the router exists.
--
-- Two helpers rather than 31 hand-edited quals: the predicate has to read
-- identically everywhere, and a copy-pasted boolean is exactly the kind of
-- thing that ends up subtly different on the one table nobody re-reads.
-- `member_role()` is deliberately NOT changed — an admin must not start
-- *looking* like a member, or they would appear in the member list and satisfy
-- the write policies too.

create or replace function private.can_read_hunt(h uuid)
returns boolean language sql stable
as $$
    select private.member_role(h) is not null or private.is_site_admin();
$$;

comment on function private.can_read_hunt(uuid) is
    'SELECT-side membership test that also admits Site Admins (AD-4). Never use '
    'in a write policy: admin writes go through the audited admin router.';

-- Owner-level reads: invitations and governance history. A Site Admin needs
-- these for support (re-sending a broken invite is the canonical case).
create or replace function private.can_read_hunt_governance(h uuid)
returns boolean language sql stable
as $$
    select private.member_role(h) = 'owner' or private.is_site_admin();
$$;

comment on function private.can_read_hunt_governance(uuid) is
    'Owner-level SELECT test that also admits Site Admins (AD-4). SELECT only.';

-- ── Hunt spine ───────────────────────────────────────────────────────────────
drop policy hunts_member_select on hunts;
create policy hunts_member_select on hunts for select to authenticated
    using (private.can_read_hunt(id) or owner_id = auth.uid());

drop policy hunt_members_member_select on hunt_members;
create policy hunt_members_member_select on hunt_members for select to authenticated
    using (private.can_read_hunt(hunt_id));

drop policy hunt_listings_member_select on hunt_listings;
create policy hunt_listings_member_select on hunt_listings for select to authenticated
    using (private.can_read_hunt(hunt_id));

drop policy hunt_shared_filters_member_select on hunt_shared_filters;
create policy hunt_shared_filters_member_select on hunt_shared_filters
    for select to authenticated using (private.can_read_hunt(hunt_id));

drop policy rubric_criteria_member_select on rubric_criteria;
create policy rubric_criteria_member_select on rubric_criteria
    for select to authenticated using (private.can_read_hunt(hunt_id));

-- ── Listing-scoped opinion and derived data ──────────────────────────────────
drop policy scores_member_select on scores;
create policy scores_member_select on scores for select to authenticated
    using (exists (select 1 from hunt_listings hl
                   where hl.id = scores.hunt_listing_id
                     and private.can_read_hunt(hl.hunt_id)));

drop policy overrides_member_select on overrides;
create policy overrides_member_select on overrides for select to authenticated
    using (exists (select 1 from hunt_listings hl
                   where hl.id = overrides.hunt_listing_id
                     and private.can_read_hunt(hl.hunt_id)));

drop policy comments_member_select on comments;
create policy comments_member_select on comments for select to authenticated
    using (exists (select 1 from hunt_listings hl
                   where hl.id = comments.hunt_listing_id
                     and private.can_read_hunt(hl.hunt_id)));

drop policy ratings_member_select on ratings;
create policy ratings_member_select on ratings for select to authenticated
    using (exists (select 1 from hunt_listings hl
                   where hl.id = ratings.hunt_listing_id
                     and private.can_read_hunt(hl.hunt_id)));

drop policy fee_checklist_member_select on fee_checklist;
create policy fee_checklist_member_select on fee_checklist for select to authenticated
    using (exists (select 1 from hunt_listings hl
                   where hl.id = fee_checklist.hunt_listing_id
                     and private.can_read_hunt(hl.hunt_id)));

drop policy utility_overrides_member_select on utility_overrides;
create policy utility_overrides_member_select on utility_overrides
    for select to authenticated
    using (exists (select 1 from hunt_listings hl
                   where hl.id = utility_overrides.hunt_listing_id
                     and private.can_read_hunt(hl.hunt_id)));

drop policy listing_unit_group_states_member_select on listing_unit_group_states;
create policy listing_unit_group_states_member_select on listing_unit_group_states
    for select to authenticated
    using (exists (select 1 from hunt_listings hl
                   where hl.id = listing_unit_group_states.hunt_listing_id
                     and private.can_read_hunt(hl.hunt_id)));

drop policy hunt_listing_refresh_status_member_select on hunt_listing_refresh_status;
create policy hunt_listing_refresh_status_member_select on hunt_listing_refresh_status
    for select to authenticated
    using (exists (select 1 from hunt_listings hl
                   where hl.id = hunt_listing_refresh_status.hunt_listing_id
                     and private.can_read_hunt(hl.hunt_id)));

-- ── AD-G provenance ──────────────────────────────────────────────────────────
drop policy fee_checklist_history_member_select on fee_checklist_history;
create policy fee_checklist_history_member_select on fee_checklist_history
    for select to authenticated
    using (exists (select 1 from hunt_listings hl
                   where hl.id = fee_checklist_history.hunt_listing_id
                     and private.can_read_hunt(hl.hunt_id)));

drop policy hunt_listing_history_member_select on hunt_listing_history;
create policy hunt_listing_history_member_select on hunt_listing_history
    for select to authenticated
    using (exists (select 1 from hunt_listings hl
                   where hl.id = hunt_listing_history.hunt_listing_id
                     and private.can_read_hunt(hl.hunt_id)));

drop policy hunt_member_history_owner_select on hunt_member_history;
create policy hunt_member_history_owner_select on hunt_member_history
    for select to authenticated using (private.can_read_hunt_governance(hunt_id));

drop policy deletion_tombstones_owner_select on deletion_tombstones;
create policy deletion_tombstones_owner_select on deletion_tombstones
    for select to authenticated
    using (hunt_id is not null and private.can_read_hunt_governance(hunt_id));

-- ── Extraction facts (global rows stay world-readable) ───────────────────────
drop policy extractions_authenticated_select on extractions;
create policy extractions_authenticated_select on extractions
    for select to authenticated
    using (hunt_id is null or private.can_read_hunt(hunt_id));

drop policy extraction_resolution_candidates_authenticated_select
    on extraction_resolution_candidates;
create policy extraction_resolution_candidates_authenticated_select
    on extraction_resolution_candidates for select to authenticated
    using (exists (select 1 from extractions e
                   where e.id = extraction_resolution_candidates.resolution_extraction_id
                     and (e.hunt_id is null or private.can_read_hunt(e.hunt_id))));

-- ── Pipeline ─────────────────────────────────────────────────────────────────
drop policy jobs_member_select on jobs;
create policy jobs_member_select on jobs for select to authenticated
    using (private.can_read_hunt(hunt_id));

drop policy job_events_member_select on job_events;
create policy job_events_member_select on job_events for select to authenticated
    using (exists (select 1 from jobs j
                   where j.id = job_events.job_id and private.can_read_hunt(j.hunt_id)));

drop policy job_stage_costs_member_select on job_stage_costs;
create policy job_stage_costs_member_select on job_stage_costs
    for select to authenticated
    using (exists (select 1 from jobs j
                   where j.id = job_stage_costs.job_id and private.can_read_hunt(j.hunt_id)));

-- ── Invitations (owner-level) ────────────────────────────────────────────────
drop policy invites_owner_select on invites;
create policy invites_owner_select on invites for select to authenticated
    using (private.can_read_hunt_governance(hunt_id));

drop policy invitation_links_owner_select on invitation_links;
create policy invitation_links_owner_select on invitation_links
    for select to authenticated using (private.can_read_hunt_governance(hunt_id));

drop policy invitation_link_joins_owner_select on invitation_link_joins;
create policy invitation_link_joins_owner_select on invitation_link_joins
    for select to authenticated
    using (exists (select 1 from invitation_links il
                   where il.id = invitation_link_joins.invitation_link_id
                     and private.can_read_hunt_governance(il.hunt_id)));

-- ── Visits (READ only — §4.2 keeps a ghost out of every write path) ──────────
drop policy visits_member_read on visits;
create policy visits_member_read on visits for select to authenticated
    using (private.can_read_hunt(hunt_id));

drop policy visit_units_member_read on visit_units;
create policy visit_units_member_read on visit_units for select to authenticated
    using (private.can_read_hunt(private.visit_hunt_id(visit_id)));

drop policy visit_entries_member_read on visit_entries;
create policy visit_entries_member_read on visit_entries for select to authenticated
    using (private.can_read_hunt(private.visit_hunt_id(visit_id)));

drop policy visit_custom_items_member_read on visit_custom_items;
create policy visit_custom_items_member_read on visit_custom_items
    for select to authenticated
    using (private.can_read_hunt(private.visit_hunt_id(visit_id)));

drop policy visit_defects_member_read on visit_defects;
create policy visit_defects_member_read on visit_defects for select to authenticated
    using (private.can_read_hunt(private.visit_hunt_id(visit_id)));

drop policy visit_fee_proposals_member_read on visit_fee_proposals;
create policy visit_fee_proposals_member_read on visit_fee_proposals
    for select to authenticated
    using (private.can_read_hunt(private.visit_hunt_id(visit_id)));

-- ── Self-checks ──────────────────────────────────────────────────────────────
-- The failure mode this guards is a future table that adds a Hunt-scoped SELECT
-- policy and forgets the predicate: the admin panel then shows a Hunt with one
-- silently empty section, which nobody notices until support needs it.
do $$
declare
    v_missing text;
begin
    select string_agg(tablename || '.' || policyname, ', ')
      into v_missing
      from pg_policies
     where schemaname = 'public' and cmd = 'SELECT'
       and qual like '%member_role%'
       and qual not like '%is_site_admin%'
       and qual not like '%can_read_hunt%';

    if v_missing is not null then
        raise exception
            'Hunt-scoped SELECT policies without the admin predicate: %', v_missing;
    end if;
end $$;

-- And the inverse, which is the dangerous direction: no WRITE policy may admit
-- a Site Admin. An admin write that bypasses the router bypasses the audit log.
do $$
declare
    v_leaked text;
begin
    select string_agg(tablename || '.' || policyname, ', ')
      into v_leaked
      from pg_policies
     where schemaname = 'public' and cmd <> 'SELECT'
       and (coalesce(qual, '') || coalesce(with_check, '')) like '%is_site_admin%';

    if v_leaked is not null then
        raise exception
            'Write policies must never admit a Site Admin: %', v_leaked;
    end if;
end $$;
