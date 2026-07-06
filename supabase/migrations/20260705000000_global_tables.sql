-- Migration 0001 (P0-4): global tables + enums — DESIGN §8.1–§8.2, Phase 0 scope.
-- Global facts shared across hunts; per-hunt tables, pipeline tables, indexes
-- beyond basic FKs, and RLS arrive in later migrations (P1-1, P2-1).
-- Only the enums these tables use are created here; the rest ship with the
-- tables that need them ("remaining enums", IMPLEMENTATION §7 P1-1).
-- All timestamps are UTC timestamptz (§8).

create type confidence as enum ('high', 'medium', 'low', 'not_found');
create type fetch_outcome as enum ('success', 'shell', 'blocked', 'not_listing', 'error');

-- criteria_catalog (§8.2): seeded from shared/catalog.py via supabase/seed.sql.
-- value_schema is the single source of truth for extraction schema generation,
-- option validation, and widget rendering. No enum types for category/domain/
-- requires_tool/refresh_class: their vocabularies live in shared/models.py and
-- adding a catalog category must not take a migration — checks keep rows honest.
create table criteria_catalog (
    key            text primary key,
    label          text not null,
    category       text not null,
    domain         text not null check (domain in ('rent', 'buy', 'both')),
    value_schema   jsonb not null,
    default_options jsonb not null default '[]',
    extraction_hint text not null default '',
    requires_tool  text check (requires_tool in ('maps', 'vision', 'web_search')),
    refresh_class  text not null check (
        refresh_class in ('pricing', 'listing_details', 'images', 'reviews', 'location')
    )
);

-- properties (§8.2): canonical, globally shared complexes/buildings.
-- Dedup identity: geocode proximity AND name similarity (DEDUPE, §10.3).
create table properties (
    id                uuid primary key default gen_random_uuid(),
    name              text not null,
    canonical_address text not null,
    place_id          text,
    lat               double precision,
    lng               double precision,
    official_url      text,
    first_seen_at     timestamptz not null default now()
);

-- property_sources (§8.2): one known listing page (URL) per property per site.
-- Stored artifact is gzipped cleaned text (KB, not MB); raw HTML is transient.
create table property_sources (
    id                uuid primary key default gen_random_uuid(),
    property_id       uuid not null references properties (id) on delete cascade,
    url               text not null unique,
    site_domain       text not null,
    is_official       boolean not null default false,
    last_fetched_at   timestamptz,
    last_success_at   timestamptz,
    cleaned_text_path text,
    cleaned_text_hash text,
    image_urls        jsonb not null default '[]',
    screenshot_path   text
);
create index property_sources_property_id_idx on property_sources (property_id);

-- floor_plans (§8.2): one distinct unit layout at a property, from one source.
create table floor_plans (
    id                uuid primary key default gen_random_uuid(),
    property_id       uuid not null references properties (id) on delete cascade,
    source_id         uuid not null references property_sources (id) on delete cascade,
    plan_name         text not null,
    beds              integer not null,
    baths             numeric(2, 1) not null,
    sqft_min          integer,
    sqft_max          integer,
    rent_min          numeric(10, 2),
    rent_max          numeric(10, 2),
    deposit           numeric(10, 2),
    availability_date date,
    available_units   integer,
    raw               jsonb not null default '{}'
);
create index floor_plans_property_id_idx on floor_plans (property_id);

-- extractions (§8.2): APPEND-ONLY — current value = latest row per
-- (property, hunt_id, criterion); the latest-row partial index ships with
-- migration 0002 (P1-1). hunt_id is NULL for catalog criteria and set for
-- custom criteria (hunt-scoped keys); its FK to hunts is added in 0002 when
-- that table exists. criterion_key has no FK by design: custom-criterion keys
-- are not catalog rows.
create table extractions (
    id              uuid primary key default gen_random_uuid(),
    property_id     uuid not null references properties (id) on delete cascade,
    hunt_id         uuid,
    criterion_key   text not null,
    value           jsonb,
    confidence      confidence not null,
    evidence_quote  text,
    source_id       uuid references property_sources (id) on delete set null,
    model           text not null,
    resolution_rule text,
    extracted_at    timestamptz not null default now()
);
create index extractions_property_criterion_idx
    on extractions (property_id, criterion_key, extracted_at desc);

-- property_images (§8.2): WebP, <=10 per property (tunable MAX_IMAGES).
create table property_images (
    id                uuid primary key default gen_random_uuid(),
    property_id       uuid not null references properties (id) on delete cascade,
    storage_path      text not null,
    kind              text,
    vision_assessment jsonb
);
create index property_images_property_id_idx on property_images (property_id);

-- utility_baselines (§8.2, §9.5): metro-level, 120-day TTL;
-- monthly_high is the winter-weighted peak-month figure.
create table utility_baselines (
    metro          text not null,
    beds_bucket    integer not null,
    utility        text not null,
    monthly_high   numeric(8, 2) not null,
    monthly_median numeric(8, 2) not null,
    sources        jsonb not null default '[]',
    refreshed_at   timestamptz not null default now(),
    primary key (metro, beds_bucket, utility)
);

-- fetch_adapter_registry (§8.2, §10.7): per-domain fetch tier + settings.
-- The ladder is climbed once per domain, not once per fetch.
create table fetch_adapter_registry (
    site_domain       text primary key,
    required_tier     integer not null default 1 check (required_tier between 1 and 3),
    adapter_config    jsonb not null default '{}',
    last_success_tier integer check (last_success_tier between 1 and 3),
    last_outcome      fetch_outcome,
    updated_at        timestamptz not null default now()
);
