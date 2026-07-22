-- P3-SC2: unified append-only scoped Extraction foundation.
--
-- Pre-live reset migration: old Extraction/Override rows are intentionally
-- discarded. The application is not live; deterministic fixtures/dev seed are
-- the recovery path. Earlier migrations remain immutable.

drop view if exists current_overrides;
drop view if exists current_extractions;
drop view if exists current_extraction_candidates;
drop table if exists extraction_resolution_candidates cascade;
drop table extractions cascade;
drop table overrides cascade;

-- Source-local Floor Plan identity and authoritative-refresh lifecycle.
alter table property_sources
    add constraint property_sources_id_property_key unique (id, property_id);

alter table floor_plans drop constraint if exists floor_plans_source_plan_key;
alter table floor_plans
    add column source_native_id text,
    add column detail_url text,
    add column unit_types jsonb not null default '[]'::jsonb,
    add column pricing_observed_at timestamptz,
    add column lease_terms jsonb,
    add column accessibility_features jsonb,
    add column plan_fees jsonb,
    add column concessions jsonb,
    add column first_seen_at timestamptz not null default now(),
    add column last_seen_at timestamptz not null default now(),
    add column is_current boolean not null default true,
    add column field_provenance jsonb not null default '{}'::jsonb,
    add constraint floor_plans_id_property_key unique (id, property_id),
    add constraint floor_plans_source_property_fkey
        foreign key (source_id, property_id)
        references property_sources (id, property_id)
        on delete cascade
        deferrable initially deferred;

create unique index floor_plans_source_native_key
    on floor_plans (source_id, source_native_id)
    where source_native_id is not null;
create unique index floor_plans_source_fallback_key
    on floor_plans (source_id, plan_name, beds, baths)
    where source_native_id is null;
create index floor_plans_current_property_idx
    on floor_plans (property_id, is_current, beds, baths);

-- Catalog truth vocabulary is independent from Rubric behavior.
alter table criteria_catalog
    add column fact_scope text not null default 'property'
        check (fact_scope in ('property', 'floor_plan', 'mixed', 'composed')),
    add column claim_value_schema jsonb,
    add column escalation_policy text not null default 'decision_relevant'
        check (escalation_policy in ('decision_relevant', 'available_sources_only')),
    add column conflict_policy text not null default 'standard_ladder'
        check (conflict_policy in ('standard_ladder', 'verified_positive_preferred'));

update criteria_catalog set fact_scope = 'composed' where key = 'all_in_monthly';
update criteria_catalog set fact_scope = 'floor_plan' where key in (
    'beds', 'baths', 'sqft', 'patio_balcony', 'private_entry', 'security_deposit',
    'availability_date', 'kitchen_quality', 'flooring_quality', 'cooling', 'dishwasher'
);
update criteria_catalog set fact_scope = 'mixed'
where key in ('in_unit_laundry', 'parking', 'min_lease_months');

create table extractions (
    id              uuid primary key default gen_random_uuid(),
    property_id     uuid not null references properties (id) on delete cascade,
    hunt_id         uuid references hunts (id) on delete cascade,
    criterion_key   text not null,
    record_kind     text not null check (record_kind in ('candidate', 'resolved')),
    origin_key      text not null check (length(btrim(origin_key)) > 0),
    source_id       uuid,
    target_scope    text not null check (target_scope in ('property', 'floor_plan')),
    floor_plan_id   uuid,
    applicability   text check (applicability in (
        'specific_floor_plans', 'all_units', 'select_units', 'unit_scope_unspecified'
    )),
    claim_group_id  uuid not null default gen_random_uuid(),
    value           jsonb,
    confidence      confidence not null,
    evidence_quote  text,
    model           text not null,
    resolution_rule text,
    disputed        boolean not null default false,
    job_id          uuid references jobs (id) on delete set null,
    -- clock_timestamp(), unlike now(), advances within one projection
    -- transaction; current-view ordering therefore reflects append order.
    extracted_at    timestamptz not null default clock_timestamp(),
    constraint extractions_target_shape check (
        (target_scope = 'floor_plan' and floor_plan_id is not null
            and applicability = 'specific_floor_plans')
        or
        (target_scope = 'property' and floor_plan_id is null
            and (applicability is null or applicability in (
                'all_units', 'select_units', 'unit_scope_unspecified'
            )))
    ),
    constraint extractions_source_property_fkey
        foreign key (source_id, property_id)
        references property_sources (id, property_id)
        on delete set null (source_id)
        deferrable initially deferred,
    constraint extractions_floor_plan_property_fkey
        foreign key (floor_plan_id, property_id)
        references floor_plans (id, property_id)
        on delete cascade
        deferrable initially deferred,
    constraint extractions_record_shape check (
        (record_kind = 'candidate' and resolution_rule is null)
        or record_kind = 'resolved'
    )
);

-- Candidate lineage and resolved truth have different current identities.
create index extractions_current_candidate_global_idx
    on extractions (
        property_id, criterion_key, origin_key, target_scope, floor_plan_id,
        extracted_at desc, id desc
    ) where record_kind = 'candidate' and hunt_id is null;
create index extractions_current_candidate_hunt_idx
    on extractions (
        property_id, hunt_id, criterion_key, origin_key, target_scope, floor_plan_id,
        extracted_at desc, id desc
    ) where record_kind = 'candidate' and hunt_id is not null;
create index extractions_current_resolved_global_idx
    on extractions (
        property_id, criterion_key, target_scope, floor_plan_id,
        extracted_at desc, id desc
    ) where record_kind = 'resolved' and hunt_id is null;
create index extractions_current_resolved_hunt_idx
    on extractions (
        property_id, hunt_id, criterion_key, target_scope, floor_plan_id,
        extracted_at desc, id desc
    ) where record_kind = 'resolved' and hunt_id is not null;
create index extractions_source_idx on extractions (source_id) where source_id is not null;
create index extractions_claim_group_idx on extractions (claim_group_id);

create view current_extraction_candidates
with (security_invoker = true)
as
select distinct on (
    property_id, hunt_id, criterion_key, origin_key, target_scope, floor_plan_id
)
    *
from extractions
where record_kind = 'candidate'
order by
    property_id, hunt_id, criterion_key, origin_key, target_scope, floor_plan_id,
    extracted_at desc, id desc;

create view current_extractions
with (security_invoker = true)
as
select distinct on (
    property_id, hunt_id, criterion_key, target_scope, floor_plan_id
)
    *
from extractions
where record_kind = 'resolved'
order by
    property_id, hunt_id, criterion_key, target_scope, floor_plan_id,
    extracted_at desc, id desc;

create table extraction_resolution_candidates (
    resolution_extraction_id uuid not null references extractions (id) on delete cascade,
    candidate_extraction_id  uuid not null references extractions (id) on delete cascade,
    selected                 boolean not null default false,
    primary key (resolution_extraction_id, candidate_extraction_id)
);
create index extraction_resolution_candidate_idx
    on extraction_resolution_candidates (candidate_extraction_id);

create or replace function private.validate_extraction_resolution_candidate()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
    resolution_row extractions%rowtype;
    candidate_row extractions%rowtype;
begin
    select * into resolution_row from extractions where id = new.resolution_extraction_id;
    select * into candidate_row from extractions where id = new.candidate_extraction_id;
    if resolution_row.record_kind <> 'resolved' or candidate_row.record_kind <> 'candidate' then
        raise exception 'resolution provenance must link resolved -> candidate rows';
    end if;
    if resolution_row.property_id <> candidate_row.property_id
       or resolution_row.hunt_id is distinct from candidate_row.hunt_id
       or resolution_row.criterion_key <> candidate_row.criterion_key
       or resolution_row.target_scope <> candidate_row.target_scope
       or resolution_row.floor_plan_id is distinct from candidate_row.floor_plan_id then
        raise exception 'resolution and candidate scoped identities differ';
    end if;
    return new;
end
$$;

create constraint trigger extraction_resolution_candidate_identity
after insert or update on extraction_resolution_candidates
deferrable initially deferred
for each row execute function private.validate_extraction_resolution_candidate();

create table overrides (
    id              uuid primary key default gen_random_uuid(),
    hunt_listing_id uuid not null references hunt_listings (id) on delete cascade,
    criterion_key   text not null,
    target_scope    text not null check (target_scope in ('property', 'floor_plan')),
    floor_plan_id   uuid references floor_plans (id) on delete cascade,
    applicability   text check (applicability in ('specific_floor_plans', 'all_units')),
    value           jsonb,
    user_id         uuid not null,
    note            text,
    created_at      timestamptz not null default clock_timestamp(),
    constraint overrides_target_shape check (
        (target_scope = 'floor_plan' and floor_plan_id is not null
            and applicability = 'specific_floor_plans')
        or
        (target_scope = 'property' and floor_plan_id is null
            and (applicability is null or applicability = 'all_units'))
    )
);
create index overrides_current_property_idx
    on overrides (hunt_listing_id, criterion_key, created_at desc, id desc)
    where target_scope = 'property';
create index overrides_current_floor_plan_idx
    on overrides (hunt_listing_id, criterion_key, floor_plan_id, created_at desc, id desc)
    where target_scope = 'floor_plan';

create view current_overrides
with (security_invoker = true)
as
select distinct on (hunt_listing_id, criterion_key, target_scope, floor_plan_id)
    *
from overrides
order by hunt_listing_id, criterion_key, target_scope, floor_plan_id, created_at desc, id desc;

-- Re-establish the P2 authorization boundary dropped with the old tables.
alter table extractions enable row level security;
alter table extraction_resolution_candidates enable row level security;
alter table overrides enable row level security;

create policy extractions_authenticated_select
    on extractions for select to authenticated
    using (hunt_id is null or private.member_role(hunt_id) is not null);
create policy extraction_resolution_candidates_authenticated_select
    on extraction_resolution_candidates for select to authenticated
    using (
        exists (
            select 1 from extractions e
            where e.id = extraction_resolution_candidates.resolution_extraction_id
              and (e.hunt_id is null or private.member_role(e.hunt_id) is not null)
        )
    );
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
        and (
            floor_plan_id is null or exists (
                select 1 from hunt_listings hl
                join floor_plans fp on fp.property_id = hl.property_id
                where hl.id = overrides.hunt_listing_id and fp.id = overrides.floor_plan_id
            )
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
        and (
            floor_plan_id is null or exists (
                select 1 from hunt_listings hl
                join floor_plans fp on fp.property_id = hl.property_id
                where hl.id = overrides.hunt_listing_id and fp.id = overrides.floor_plan_id
            )
        )
    );

grant select on current_extraction_candidates, current_extractions, current_overrides
    to authenticated;
grant select on extraction_resolution_candidates to authenticated;
