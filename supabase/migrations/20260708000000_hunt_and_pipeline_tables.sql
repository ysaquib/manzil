-- Migration 0002 (P1-1): per-hunt + pipeline tables, remaining enums, indexes.
-- DESIGN §8.1–§8.2, Phase 1 scope. Builds on 0001 (global tables + `confidence`,
-- `fetch_outcome`). RLS is deliberately NOT here — policies land in P2-1 (§8.3).
-- All timestamps are UTC timestamptz (§8). User-id columns (owner_id, user_id,
-- added_by, …) are plain uuid with no FK to auth.users: auth/RLS is P2-1, and
-- the dev-seed (later P1-1 half) must insert without provisioning auth users.

-- Remaining enums (§8.1): created by the first migration whose tables need them.
-- Catalog/vocabulary columns that §8.1 keeps as text+check (hunts.domain,
-- hunt_listings.status/source_policy, job_events.event) stay text+check — no
-- enum type, since those vocabularies live in shared/models.py.
create type hunt_role as enum ('owner', 'curator', 'member');
create type job_type as enum ('ingest', 'refresh', 'rescore', 'investigate');
create type job_state as enum (
    'queued', 'running', 'waiting_user', 'done', 'failed', 'cancelled'
);
create type value_state as enum ('extracted', 'manual', 'estimated', 'unknown');

-- extractions.hunt_id FK, deferred from 0001 until `hunts` exists (DESIGN v2.1).
-- Cascade: hard-deleting a hunt removes its hunt-scoped custom-criterion facts.
-- hunt_id stays NULL for global catalog facts (no FK impact).

-- hunts (§8.2): per-hunt root. `settings` is the pinned hunt-settings object
-- (§8.2) — Owner-edited, API-validated, every key defaulted so `{}` is valid.
-- `domain` is text+check (rent | buy; v1 supports rent only), not an enum type.
create table hunts (
    id             uuid primary key default gen_random_uuid(),
    name           text not null,
    owner_id       uuid not null,
    domain         text not null default 'rent' check (domain in ('rent', 'buy')),
    rubric_version integer not null default 0,
    settings       jsonb not null default '{}',
    archived_at    timestamptz
);

-- hunt_members (§8.2): every per-hunt RLS policy (P2-1) keys off this table.
-- One role per user per hunt.
create table hunt_members (
    hunt_id uuid not null references hunts (id) on delete cascade,
    user_id uuid not null,
    role    hunt_role not null,
    color   text,
    primary key (hunt_id, user_id)
);

-- invites (§8.2): email or copy-link token; acceptance inserts a hunt_members
-- row (§9.1). `token` is the copy-link key. The invite feature ships in P2-3;
-- the table is part of the §8.2 schema foundation and created now.
create table invites (
    id           uuid primary key default gen_random_uuid(),
    hunt_id      uuid not null references hunts (id) on delete cascade,
    email        text,
    token        text not null unique,
    role_granted hunt_role not null default 'member',
    created_by   uuid not null,
    expires_at   timestamptz not null,
    accepted_by  uuid
);
create index invites_hunt_id_idx on invites (hunt_id);

-- hunt_listings (§8.2): §3 "Listing" — a Property associated with a Hunt.
-- Scores, overrides, fees, comments, ratings and jobs reference this row's id.
-- `source_policy` (DESIGN v2.2, §10.7): per-submission fetch-scope control,
-- text+check, defaulted from hunts.settings.default_source_policy. `pins` maps a
-- Unit Group key ("{beds}-{baths}") to a floor_plan_id (§9.4).
create table hunt_listings (
    id            uuid primary key default gen_random_uuid(),
    hunt_id       uuid not null references hunts (id) on delete cascade,
    property_id   uuid not null references properties (id) on delete cascade,
    added_by      uuid not null,
    status        text not null default 'active' check (status in ('active', 'archived')),
    source_policy text not null default 'tiers_1_2_3' check (
        source_policy in (
            'trust_link', 'tier_1', 'tiers_1_2', 'tiers_1_2_3', 'tier_1_plus_official'
        )
    ),
    pins          jsonb not null default '{}',
    created_at    timestamptz not null default now(),
    unique (hunt_id, property_id)
);

-- rubric_criteria (§8.2): a criterion is EITHER a catalog reference (catalog_key
-- set) OR a custom definition (custom_def set) — enforced by the xor check.
-- `options` holds the pinned rubric-option shape (§8.2); `is_bonus` is derived
-- (all deltas >= 0, §9.2). No enum type here — none of these columns are enums.
create table rubric_criteria (
    id             uuid primary key default gen_random_uuid(),
    hunt_id        uuid not null references hunts (id) on delete cascade,
    catalog_key    text references criteria_catalog (key),
    custom_def     jsonb,
    enabled        boolean not null default true,
    options        jsonb not null default '[]',
    unknown_delta  numeric not null default 0,
    non_negotiable jsonb,
    is_bonus       boolean not null default false,
    position       integer not null default 0,
    check ((catalog_key is not null) <> (custom_def is not null))
);
-- A catalog criterion appears at most once per hunt rubric.
create unique index rubric_criteria_hunt_catalog_idx
    on rubric_criteria (hunt_id, catalog_key)
    where catalog_key is not null;

-- overrides (§8.2): per-listing human value displayed over an extraction
-- (override > extraction). Append-only; no UPDATE path. Current value = latest
-- row per (hunt_listing_id, criterion_key), served by the index below.
create table overrides (
    id              uuid primary key default gen_random_uuid(),
    hunt_listing_id uuid not null references hunt_listings (id) on delete cascade,
    criterion_key   text not null,
    value           jsonb,
    user_id         uuid not null,
    note            text,
    created_at      timestamptz not null default now()
);
create index overrides_latest_idx
    on overrides (hunt_listing_id, criterion_key, created_at desc);

-- fee_checklist (§8.2): one row per (listing, fee slot); upserted in place.
create table fee_checklist (
    hunt_listing_id uuid not null references hunt_listings (id) on delete cascade,
    fee_slot        text not null,
    amount          numeric(10, 2),
    value_state     value_state not null default 'unknown',
    entered_by      uuid,
    evidence_ref    text,
    updated_at      timestamptz not null default now(),
    primary key (hunt_listing_id, fee_slot)
);

-- scores (§8.2): one score per (listing, floor plan), upserted per rescore.
-- `breakdown` is the pinned §9.3 score-breakdown contract.
create table scores (
    hunt_listing_id uuid not null references hunt_listings (id) on delete cascade,
    floor_plan_id   uuid not null references floor_plans (id) on delete cascade,
    total           numeric not null,
    breakdown       jsonb not null,
    rubric_version  integer not null,
    computed_at     timestamptz not null default now(),
    primary key (hunt_listing_id, floor_plan_id)
);

-- comments (§8.2): soft-deleted via deleted_at.
create table comments (
    id              uuid primary key default gen_random_uuid(),
    hunt_listing_id uuid not null references hunt_listings (id) on delete cascade,
    user_id         uuid not null,
    body            text not null,
    created_at      timestamptz not null default now(),
    deleted_at      timestamptz
);
create index comments_hunt_listing_id_idx on comments (hunt_listing_id);

-- ratings (§8.2): one rating per user per listing.
create table ratings (
    hunt_listing_id uuid not null references hunt_listings (id) on delete cascade,
    user_id         uuid not null,
    rating          smallint not null,
    primary key (hunt_listing_id, user_id)
);

-- jobs (§8.2): the durable queue (claimed via FOR UPDATE SKIP LOCKED, P1-2),
-- the live task state, and — since rows are never deleted — the task history
-- (FR10). Crash recovery: the claiming worker heartbeats `locked_at`; a
-- `running` job whose `locked_at` is older than JOB_ORPHAN_AFTER (5 min) is
-- reclaimable and resumes from `current_stage` (NFR3). `type`/`state` are enums.
create table jobs (
    id              uuid primary key default gen_random_uuid(),
    hunt_listing_id uuid references hunt_listings (id) on delete cascade,
    type            job_type not null,
    state           job_state not null default 'queued',
    current_stage   text,
    plan            jsonb,
    payload         jsonb not null default '{}',
    attempts        integer not null default 0,
    error           text,
    cost_actual_usd numeric(12, 4) not null default 0,
    locked_by       text,
    locked_at       timestamptz,
    created_at      timestamptz not null default now(),
    finished_at     timestamptz
);
-- Claim scan: oldest queued job first (`state`, ordered pickup).
create index jobs_claim_idx on jobs (state, created_at);
-- Orphan scan: running jobs whose heartbeat has gone stale.
create index jobs_heartbeat_idx on jobs (locked_at) where state = 'running';

-- job_events (§8.2): per-job timeline (History tab + realtime Tasks view).
-- `event` is text+check, not an enum type (not in the §8.1 enum set).
create table job_events (
    id     uuid primary key default gen_random_uuid(),
    job_id uuid not null references jobs (id) on delete cascade,
    stage  text not null,
    event  text not null check (
        event in (
            'started', 'completed', 'failed', 'checkpoint_asked',
            'checkpoint_answered', 'checkpoint_auto_resolved', 'escalated_tier'
        )
    ),
    detail jsonb not null default '{}',
    at     timestamptz not null default now()
);
create index job_events_job_id_idx on job_events (job_id, at);

-- extractions.hunt_id FK now that `hunts` exists (deferred from 0001, DESIGN v2.1).
alter table extractions
    add constraint extractions_hunt_id_fkey
    foreign key (hunt_id) references hunts (id) on delete cascade;

-- Hunt-scoped latest-extraction lookup for custom criteria: current value =
-- latest row per (property, hunt_id, criterion). Partial (hunt_id not null)
-- because catalog facts (hunt_id null) are served by the 0001 index. This is
-- the "latest-row partial index" 0001 promised for P1-1.
create index extractions_hunt_criterion_idx
    on extractions (property_id, hunt_id, criterion_key, extracted_at desc)
    where hunt_id is not null;
