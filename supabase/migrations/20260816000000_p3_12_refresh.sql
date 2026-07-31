-- P3-12: durable Listing refresh identity and per-class freshness.
--
-- Freshness is Listing-scoped because the same Property can appear in Hunts
-- with different Source Policies. Global facts remain shared; this table only
-- records when one Listing's requested assurance level was checked.

alter table hunt_listings
    add column submitted_source_id uuid;

alter table hunt_listings
    add constraint hunt_listings_submitted_source_property_fkey
        foreign key (submitted_source_id, property_id)
        references property_sources (id, property_id)
        on delete set null (submitted_source_id)
        deferrable initially deferred;

create index hunt_listings_submitted_source_idx
    on hunt_listings (submitted_source_id)
    where submitted_source_id is not null;

-- Existing completed ingests retain their submitted URL in the immutable Job
-- history. Backfill only exact same-Property matches; ambiguous/missing legacy
-- rows remain null and cannot be refreshed until a later successful ingest.
with submitted as (
    select distinct on (j.hunt_listing_id)
           j.hunt_listing_id,
           ps.id as source_id
    from jobs j
    join hunt_listings hl on hl.id = j.hunt_listing_id
    join property_sources ps
      on ps.property_id = hl.property_id
     and ps.url = j.payload ->> 'url'
    where j.type = 'ingest'
      and j.payload ? 'url'
    order by j.hunt_listing_id, j.created_at asc, j.id asc
)
update hunt_listings hl
set submitted_source_id = submitted.source_id
from submitted
where submitted.hunt_listing_id = hl.id;

create table hunt_listing_refresh_status (
    hunt_listing_id uuid not null references hunt_listings (id) on delete cascade,
    refresh_class text not null check (
        refresh_class in ('pricing', 'listing_details', 'images', 'reviews', 'location')
    ),
    last_success_at timestamptz not null,
    producer_job_id uuid references jobs (id) on delete set null,
    primary key (hunt_listing_id, refresh_class)
);

create index hunt_listing_refresh_status_due_idx
    on hunt_listing_refresh_status (refresh_class, last_success_at);

-- Treat the oldest successfully fetched contributing Source as the initial
-- text freshness boundary. A later P3-12 refresh advances both text classes
-- after checking the complete contributing Slate.
with text_freshness as (
    select hl.id as hunt_listing_id, min(ps.last_success_at) as refreshed_at
    from hunt_listings hl
    join property_sources ps on ps.property_id = hl.property_id
    where ps.last_success_at is not null
      and (
        ps.id = hl.submitted_source_id
        or exists (
            select 1
            from current_extraction_candidates c
            where c.property_id = hl.property_id
              and c.source_id = ps.id
        )
        or exists (
            select 1
            from floor_plans fp
            where fp.property_id = hl.property_id
              and fp.source_id = ps.id
              and fp.is_current
        )
      )
    group by hl.id
)
insert into hunt_listing_refresh_status
    (hunt_listing_id, refresh_class, last_success_at)
select hunt_listing_id, refresh_class, refreshed_at
from text_freshness
cross join (values ('pricing'), ('listing_details')) classes(refresh_class);

with image_freshness as (
    select hl.id as hunt_listing_id, max(pi.created_at) as refreshed_at
    from hunt_listings hl
    join property_images pi on pi.property_id = hl.property_id
    where pi.is_current
    group by hl.id
)
insert into hunt_listing_refresh_status
    (hunt_listing_id, refresh_class, last_success_at)
select hunt_listing_id, 'images', refreshed_at
from image_freshness;

with review_freshness as (
    select hl.id as hunt_listing_id, max(e.extracted_at) as refreshed_at
    from hunt_listings hl
    join current_extractions e on e.property_id = hl.property_id
    join criteria_catalog cc
      on cc.key = e.criterion_key
     and cc.refresh_class = 'reviews'
    group by hl.id
)
insert into hunt_listing_refresh_status
    (hunt_listing_id, refresh_class, last_success_at)
select hunt_listing_id, 'reviews', refreshed_at
from review_freshness;

alter table hunt_listing_refresh_status enable row level security;

create policy hunt_listing_refresh_status_member_select
    on hunt_listing_refresh_status for select to authenticated
    using (
        exists (
            select 1
            from hunt_listings hl
            where hl.id = hunt_listing_refresh_status.hunt_listing_id
              and private.member_role(hl.hunt_id) is not null
        )
    );

alter publication supabase_realtime add table hunt_listing_refresh_status;

-- Worker/service-role only writes. The API creates Jobs; it never declares a
-- refresh successful.
comment on table hunt_listing_refresh_status is
    'P3-12 Listing-scoped refresh-class success markers; service-role writes only.';

-- Keep the generic Job enqueue path for existing workflows, but make refresh
-- authorization true at the RLS boundary: Curators can refresh the Hunt,
-- Owners can refresh any Listing, and Members can refresh only Listings they
-- submitted. The API applies the narrower direct-Listing UX rule for Curators.
drop policy jobs_member_insert on jobs;
create policy jobs_member_insert
    on jobs for insert to authenticated
    with check (
        private.member_role(hunt_id) is not null
        and (
            type <> 'refresh'
            or private.member_role(hunt_id) in ('owner', 'curator')
            or exists (
                select 1
                from hunt_listings hl
                where hl.id = jobs.hunt_listing_id
                  and hl.hunt_id = jobs.hunt_id
                  and hl.added_by = auth.uid()
            )
        )
    );
