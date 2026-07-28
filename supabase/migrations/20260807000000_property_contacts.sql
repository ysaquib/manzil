-- Migration (P3-21): property-level contact info — DESIGN §8.2, §16, §20 2026-07-27.
--
-- Append-only candidate store plus a precedence-resolved current view. This is
-- deliberately NOT a criteria_catalog entry: catalog rows carry default_options
-- and deltas and surface in the rubric editor, and a phone number has no rubric
-- semantics. Contact values never enter the scoring path.
--
-- Resolution is strict provenance precedence, not the §10.6 conflict ladder.
-- That ladder is built for numeric agreement (tolerance collapse, supermajority,
-- family-deduped votes); none of it transfers to a phone number, where several
-- aggregators carrying the same digits usually means one call-tracking proxy
-- line echoed through a feed rather than genuine corroboration.
--
-- PII posture (§16, as amended): there is deliberately NO column for a person's
-- name or role. Property-level business contact only — a leasing office line or
-- a generic contact URL. Even if a model emits a named agent's identity there is
-- nowhere to store it: a structural control, not merely a prompt instruction.

create table property_contacts (
    id          uuid primary key default gen_random_uuid(),
    property_id uuid not null references properties (id) on delete cascade,
    kind        text not null check (kind in ('phone', 'contact_url')),
    value       text not null,
    provenance  text not null check (
        provenance in ('official_site', 'google_places', 'listing')
    ),
    -- Null for google_places: the value came from the Places API, not a Source.
    source_id   uuid references property_sources (id) on delete set null,
    observed_at timestamptz not null default now()
);

-- Append-only, but a re-ingest of the same page must not grow the table: the
-- writer upserts on this key and refreshes observed_at instead of inserting.
create unique index property_contacts_identity_idx
    on property_contacts (property_id, kind, value, provenance);
create index property_contacts_property_id_idx on property_contacts (property_id);

-- property_contacts_current (§8.2): one winning row per (property, kind).
-- Precedence rank official_site → google_places → listing, ties broken by the
-- freshest observation. `provenance` rides along so the UI can label where the
-- number came from.
create view property_contacts_current
with (security_invoker = true)
as
select distinct on (property_id, kind)
    property_id,
    kind,
    value,
    provenance,
    source_id,
    observed_at
from property_contacts
order by
    property_id,
    kind,
    case provenance
        when 'official_site' then 1
        when 'google_places' then 2
        when 'listing' then 3
    end,
    observed_at desc;

-- Global fact table: readable to authenticated users, no client write path.
-- The worker's service-role connection bypasses RLS and remains the only writer.
alter table property_contacts enable row level security;
create policy property_contacts_authenticated_select
    on property_contacts for select to authenticated using (true);

grant select on property_contacts_current to authenticated;
