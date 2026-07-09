-- Migration 0003 (P1-5 fix): hunts.created_at.
-- The hunts row (DESIGN §8.2) needs a creation timestamp: the API already
-- exposes it (HuntResponse.created_at, in the generated OpenAPI types) and the
-- hunt switcher orders the list newest-first by it (frontend useHunts). It was
-- omitted from 0002; added here as a forward migration. UTC timestamptz (§8);
-- default now() backfills any rows created before this migration.
alter table hunts
    add column created_at timestamptz not null default now();
