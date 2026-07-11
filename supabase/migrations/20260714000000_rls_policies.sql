-- P2-1: row-level security is the authorization boundary (DESIGN §4.2, §8.3).
-- User-initiated API writes run with the caller's JWT. The worker's service-role
-- connection bypasses RLS and remains the only writer of global facts.

create schema if not exists private;

create or replace function private.member_role(h uuid)
returns hunt_role
language sql
stable
security definer
set search_path = public
as $$
    select role
    from hunt_members
    where hunt_id = h and user_id = auth.uid()
$$;

revoke all on function private.member_role(uuid) from public, anon;
grant usage on schema private to authenticated;
grant execute on function private.member_role(uuid) to authenticated;

-- Existing Phase 1 Hunts must gain their canonical Owner membership before RLS
-- is enabled, or their owners would be locked out immediately.
insert into hunt_members (hunt_id, user_id, role)
select id, owner_id, 'owner'
from hunts
on conflict (hunt_id, user_id) do nothing;

-- A Hunt always has exactly one Owner. Ownership transfer uses a privileged,
-- transactional path added in P2-4.
create unique index one_owner_per_hunt
    on hunt_members (hunt_id)
    where role = 'owner';

alter table criteria_catalog enable row level security;
alter table properties enable row level security;
alter table property_sources enable row level security;
alter table floor_plans enable row level security;
alter table extractions enable row level security;
alter table property_images enable row level security;
alter table utility_baselines enable row level security;
alter table fetch_adapter_registry enable row level security;
alter table hunts enable row level security;
alter table hunt_members enable row level security;
alter table invites enable row level security;
alter table hunt_listings enable row level security;
alter table rubric_criteria enable row level security;
alter table overrides enable row level security;
alter table fee_checklist enable row level security;
alter table scores enable row level security;
alter table comments enable row level security;
alter table ratings enable row level security;
alter table jobs enable row level security;
alter table job_events enable row level security;

-- Global facts are readable to authenticated users and have no client write
-- policies. Hunt-scoped custom Extractions are visible only to Hunt members.
create policy criteria_catalog_authenticated_select
    on criteria_catalog for select to authenticated using (true);
create policy properties_authenticated_select
    on properties for select to authenticated using (true);
create policy property_sources_authenticated_select
    on property_sources for select to authenticated using (true);
create policy floor_plans_authenticated_select
    on floor_plans for select to authenticated using (true);
create policy extractions_authenticated_select
    on extractions for select to authenticated
    using (hunt_id is null or private.member_role(hunt_id) is not null);
create policy property_images_authenticated_select
    on property_images for select to authenticated using (true);
create policy utility_baselines_authenticated_select
    on utility_baselines for select to authenticated using (true);
create policy fetch_adapter_registry_authenticated_select
    on fetch_adapter_registry for select to authenticated using (true);

create policy hunts_member_select
    on hunts for select to authenticated
    using (private.member_role(id) is not null or owner_id = auth.uid());
create policy hunts_authenticated_insert
    on hunts for insert to authenticated
    with check (owner_id = auth.uid());
create policy hunts_owner_update
    on hunts for update to authenticated
    using (private.member_role(id) = 'owner')
    with check (private.member_role(id) = 'owner');
create policy hunts_owner_delete
    on hunts for delete to authenticated
    using (private.member_role(id) = 'owner');

create policy hunt_members_member_select
    on hunt_members for select to authenticated
    using (private.member_role(hunt_id) is not null);
create policy hunt_members_owner_bootstrap_insert
    on hunt_members for insert to authenticated
    with check (
        user_id = auth.uid()
        and role = 'owner'
        and hunt_id in (
            select id from hunts where owner_id = auth.uid()
        )
    );
create policy hunt_members_self_color_update
    on hunt_members for update to authenticated
    using (user_id = auth.uid())
    with check (
        user_id = auth.uid()
        and role = private.member_role(hunt_id)
    );
create policy hunt_members_owner_update_others
    on hunt_members for update to authenticated
    using (
        private.member_role(hunt_id) = 'owner'
        and user_id <> auth.uid()
    )
    with check (
        private.member_role(hunt_id) = 'owner'
        and user_id <> auth.uid()
    );
create policy hunt_members_owner_delete_others
    on hunt_members for delete to authenticated
    using (
        private.member_role(hunt_id) = 'owner'
        and role <> 'owner'
    );

create policy invites_owner_select
    on invites for select to authenticated
    using (private.member_role(hunt_id) = 'owner');
create policy invites_owner_insert
    on invites for insert to authenticated
    with check (
        private.member_role(hunt_id) = 'owner'
        and created_by = auth.uid()
    );
create policy invites_owner_delete
    on invites for delete to authenticated
    using (private.member_role(hunt_id) = 'owner');

create policy hunt_listings_member_select
    on hunt_listings for select to authenticated
    using (private.member_role(hunt_id) is not null);
create policy hunt_listings_member_insert
    on hunt_listings for insert to authenticated
    with check (
        private.member_role(hunt_id) is not null
        and added_by = auth.uid()
    );
create policy hunt_listings_curator_update
    on hunt_listings for update to authenticated
    using (private.member_role(hunt_id) in ('owner', 'curator'))
    with check (private.member_role(hunt_id) in ('owner', 'curator'));
create policy hunt_listings_member_update_own
    on hunt_listings for update to authenticated
    using (
        private.member_role(hunt_id) = 'member'
        and added_by = auth.uid()
    )
    with check (
        private.member_role(hunt_id) = 'member'
        and added_by = auth.uid()
    );
create policy hunt_listings_owner_delete
    on hunt_listings for delete to authenticated
    using (private.member_role(hunt_id) = 'owner');

create policy rubric_criteria_member_select
    on rubric_criteria for select to authenticated
    using (private.member_role(hunt_id) is not null);
create policy rubric_criteria_owner_insert
    on rubric_criteria for insert to authenticated
    with check (private.member_role(hunt_id) = 'owner');
create policy rubric_criteria_owner_update
    on rubric_criteria for update to authenticated
    using (private.member_role(hunt_id) = 'owner')
    with check (private.member_role(hunt_id) = 'owner');
create policy rubric_criteria_owner_delete
    on rubric_criteria for delete to authenticated
    using (private.member_role(hunt_id) = 'owner');

create policy overrides_member_select
    on overrides for select to authenticated
    using (
        exists (
            select 1 from hunt_listings hl
            where hl.id = overrides.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );
create policy overrides_curator_insert
    on overrides for insert to authenticated
    with check (
        user_id = auth.uid()
        and exists (
            select 1 from hunt_listings hl
            where hl.id = overrides.hunt_listing_id
              and private.member_role(hl.hunt_id) in ('owner', 'curator')
        )
    );
create policy overrides_member_insert_own
    on overrides for insert to authenticated
    with check (
        user_id = auth.uid()
        and exists (
            select 1 from hunt_listings hl
            where hl.id = overrides.hunt_listing_id
              and private.member_role(hl.hunt_id) = 'member'
              and hl.added_by = auth.uid()
        )
    );

create policy fee_checklist_member_select
    on fee_checklist for select to authenticated
    using (
        exists (
            select 1 from hunt_listings hl
            where hl.id = fee_checklist.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );
create policy fee_checklist_curator_insert
    on fee_checklist for insert to authenticated
    with check (
        exists (
            select 1 from hunt_listings hl
            where hl.id = fee_checklist.hunt_listing_id
              and private.member_role(hl.hunt_id) in ('owner', 'curator')
        )
    );
create policy fee_checklist_member_insert_own
    on fee_checklist for insert to authenticated
    with check (
        exists (
            select 1 from hunt_listings hl
            where hl.id = fee_checklist.hunt_listing_id
              and private.member_role(hl.hunt_id) = 'member'
              and hl.added_by = auth.uid()
        )
    );
create policy fee_checklist_curator_update
    on fee_checklist for update to authenticated
    using (
        exists (
            select 1 from hunt_listings hl
            where hl.id = fee_checklist.hunt_listing_id
              and private.member_role(hl.hunt_id) in ('owner', 'curator')
        )
    )
    with check (
        exists (
            select 1 from hunt_listings hl
            where hl.id = fee_checklist.hunt_listing_id
              and private.member_role(hl.hunt_id) in ('owner', 'curator')
        )
    );
create policy fee_checklist_member_update_own
    on fee_checklist for update to authenticated
    using (
        exists (
            select 1 from hunt_listings hl
            where hl.id = fee_checklist.hunt_listing_id
              and private.member_role(hl.hunt_id) = 'member'
              and hl.added_by = auth.uid()
        )
    )
    with check (
        exists (
            select 1 from hunt_listings hl
            where hl.id = fee_checklist.hunt_listing_id
              and private.member_role(hl.hunt_id) = 'member'
              and hl.added_by = auth.uid()
        )
    );

create policy scores_member_select
    on scores for select to authenticated
    using (
        exists (
            select 1 from hunt_listings hl
            where hl.id = scores.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );

create policy comments_member_select
    on comments for select to authenticated
    using (
        exists (
            select 1 from hunt_listings hl
            where hl.id = comments.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );
create policy comments_member_insert
    on comments for insert to authenticated
    with check (
        user_id = auth.uid()
        and exists (
            select 1 from hunt_listings hl
            where hl.id = comments.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );
create policy comments_author_update
    on comments for update to authenticated
    using (user_id = auth.uid())
    with check (
        user_id = auth.uid()
        and exists (
            select 1 from hunt_listings hl
            where hl.id = comments.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );

create policy ratings_member_select
    on ratings for select to authenticated
    using (
        exists (
            select 1 from hunt_listings hl
            where hl.id = ratings.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );
create policy ratings_self_insert
    on ratings for insert to authenticated
    with check (
        user_id = auth.uid()
        and exists (
            select 1 from hunt_listings hl
            where hl.id = ratings.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );
create policy ratings_self_update
    on ratings for update to authenticated
    using (user_id = auth.uid())
    with check (
        user_id = auth.uid()
        and exists (
            select 1 from hunt_listings hl
            where hl.id = ratings.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );
create policy ratings_self_delete
    on ratings for delete to authenticated
    using (user_id = auth.uid());

create policy jobs_member_select
    on jobs for select to authenticated
    using (private.member_role(hunt_id) is not null);
create policy jobs_member_insert
    on jobs for insert to authenticated
    with check (private.member_role(hunt_id) is not null);
create policy jobs_owner_update
    on jobs for update to authenticated
    using (private.member_role(hunt_id) = 'owner')
    with check (private.member_role(hunt_id) = 'owner');
create policy jobs_member_update_own
    on jobs for update to authenticated
    using (
        private.member_role(hunt_id) in ('member', 'curator')
        and exists (
            select 1 from hunt_listings hl
            where hl.id = jobs.hunt_listing_id
              and hl.added_by = auth.uid()
        )
    )
    with check (
        private.member_role(hunt_id) in ('member', 'curator')
        and exists (
            select 1 from hunt_listings hl
            where hl.id = jobs.hunt_listing_id
              and hl.added_by = auth.uid()
        )
    );
create policy jobs_curator_checkpoint_update
    on jobs for update to authenticated
    using (
        private.member_role(hunt_id) = 'curator'
        and state = 'waiting_user'
    )
    with check (state <> 'cancelled');

create policy job_events_member_select
    on job_events for select to authenticated
    using (
        exists (
            select 1 from jobs j
            where j.id = job_events.job_id
              and private.member_role(j.hunt_id) is not null
        )
    );
