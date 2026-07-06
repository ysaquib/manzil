# Changelog

Living log of what has landed in the **code**, newest first, keyed by the
IMPLEMENTATION.md §7 task IDs. Design changes go to DESIGN.md §20 (Decision
Log); doc-mechanics changes go to IMPLEMENTATION.md §9 — this file tracks the
repo itself.

## Unreleased — Phase 0

### 2026-07-05 — P0-6: fetch tiers 1-2 + outcome classifier + adapter registry + census

- `fetching/tiers.py`: Tier 1 (httpx, sane headers) and Tier 2 (Playwright
  Chromium, realistic fingerprint, per-domain politeness delay, opportunistic
  screenshot); tier 3 stays gated behind the census verdict.
- `fetching/classifier.py`: §10.7 layered outcome classification
  (success/shell/blocked/not_listing/error) — HTTP signals, challenge
  fingerprints and cookies, JS-shell script-ratio signature, size floors,
  JSON-LD short-circuit, currency/bed-bath/address positive tokens.
- `fetching/registry.py` + `ladder.py`: per-domain adapter registry
  (`InMemoryRegistry` + asyncpg `PostgresRegistry` over migration 0001's
  table); ladder climbs once per domain and self-tunes — second fetch of a
  shell domain starts straight at tier 2 (test-pinned).
- `fetching/census.py` + `manzil census`: probes `infra/census_urls.txt`,
  emits `docs/hostile-domain-census.csv`. **First live census run committed:**
  rent.com, apartmentguide.com, apartmentlist.com tier-1 ok; zumper,
  padmapper, hotpads tier-2 ok; apartments.com, zillow, realtor.com,
  trulia, forrent.com hostile at tier 2 (P0-14 gate input).
- Tests: 12 classifier cases over committed synthetic fixture pages
  (fixtures/pages/), ladder escalation + registry self-tuning, plus a corpus
  sweep asserting every saved real page classifies success.

### 2026-07-05 — P0-5: HTML cleaner + corpus tooling

- `fetching/cleaner.py`: trafilatura primary (tables + recall favored),
  readability-lxml fallback, and the fee-table preserver — tables mentioning
  fees/deposits/pet charges are re-rendered as `cell | cell` lines and
  appended under a `[FEE TABLES]` marker only when the extractor dropped them
  (no duplication). Output carries a sha256 content hash (the §14 hash-gating
  input).
- `fetching/corpus.py` + CLI: `manzil save-page <url> <slug>` (fetch through
  the ladder → corpus fixture dir with raw.html/cleaned.txt/meta.json) and
  `manzil clean-corpus` (the cleaner-change runbook step).
- Corpus seeded with 3 real Detroit listings from rent.com (~535 KB raw →
  ~4.7 KB cleaned, >100x reduction; beds/baths/sqft/fee language verified
  present). New tunables: `CLEANED_TEXT_MIN_CHARS`, `SHELL_SCRIPT_RATIO`,
  `TIER2_MIN_DELAY_SECONDS`.

### 2026-07-05 — P0-4: migration 0001 — global tables + enums

- `supabase/migrations/20260705000000_global_tables.sql`: the eight §8.2
  global tables (criteria_catalog, properties, property_sources, floor_plans,
  extractions, property_images, utility_baselines, fetch_adapter_registry)
  with basic FK indexes, plus the two enums they use (`confidence`,
  `fetch_outcome`) — remaining enums ship with migration 0002 (P1-1).
- Deliberate choices: catalog category/domain/requires_tool/refresh_class are
  text + check (adding a category must not take a migration); extractions is
  append-only with no FK on `criterion_key` (custom keys aren't catalog rows)
  and `hunt_id` unconstrained until hunts exists in 0002; `property_sources.url`
  unique.
- Verified: `supabase db reset` clean — migration applies, seed loads, all 19
  catalog rows queryable with intact jsonb (closing P0-2's "loaded" leg for real).

### 2026-07-05 — P0-3: scoring engine + golden tests

- `manzil_shared.scoring.engine`: pure `score(rubric, effective_values,
  floor_plan) -> ScoreBreakdown` per §9.3 — gate pass (min of fired
  set-scores, criteria empty), delta pass (first match wins, unknown ->
  unknown_delta), clamp [0, 15]. Plus `select_display_score` (§9.4: best plan
  unless pinned) and `ScoreBreakdown.to_contract()` emitting the exact pinned
  §9.3 JSON shape.
- Semantics settled in code (proposal status, flagged for DESIGN):
  a non-negotiable is satisfied only by a known value whose first-matching
  option has delta >= 0 and is not a dealbreaker option; object values compare
  on `"rating"`; lt/gt/range work on numbers and ISO-date strings; plan
  overlay uses conservative `sqft_min`.
- 14 golden tests in `shared/tests/golden/test_engine.py` covering gates,
  unknowns, bonus, clamp (both ends), first-match-wins, disabled criteria,
  object values, inclusive ranges, and multi-plan groups with pin override.

### 2026-07-05 — P0-2 follow-up: catalog 15 → 19 criteria (DESIGN v2.0)

- Added the four seed-set criteria from DESIGN v2.0 §8.2 (the climate/logistics
  blind spot): `parking` (enum garage/carport/dedicated_lot/street_only/none),
  `cooling` (enum central/window_units/none), `dishwasher` (bool) — all
  unit/listing_details — and `min_lease_months` (int, policy/pricing).
- Inserted in §8.2 table order (after `flooring_quality`); default option
  deltas and extraction hints authored here, same review caveat as the rest.
- `supabase/seed.sql` regenerated (19 rows); key-list test updated.

### 2026-07-04 — P0-2: shared domain models + catalog seed + seed.sql generator

- `manzil_shared.models`: Pydantic models for every DESIGN §3 term (Hunt,
  Property, Listing, Source, Floor Plan, Unit Group, Criterion, Rubric, Gate,
  Extraction, Override, Job, Checkpoint …), all §8.1 enums, and the pinned
  contract shapes: rubric option + catalog entry (§8.2), score breakdown
  (§9.3), checkpoint prompt (§10.10).
- `manzil_shared.catalog`: the 15 v1 criteria from §8.2 (the pinned `beds`
  entry verbatim), all tagged `domain=rent`. Default option deltas and
  extraction hints for the other 14 are seed data authored here — review
  welcome; owners edit options in the rubric anyway.
- seed generator: `uv run --package manzil-shared python -m manzil_shared.catalog`
  writes `supabase/seed.sql` (idempotent upsert on `key`; never hand-edited).
- Tests: SQL-literal round-trip (python → SQL → parsed → equal), committed-seed
  drift guard, pinned-contract check for `beds`. Live-Postgres load is exercised
  by `supabase db reset` once P0-4's migration creates `criteria_catalog`.
- Open for P0-3: match semantics for object values (`management_reviews`
  numeric ops apply to its `rating` field).

### 2026-07-04 — P0-1: monorepo scaffold + CI

- uv workspace per DESIGN §6: `manzil-shared` / `manzil-api` / `manzil-worker`
  (`src/manzil_shared` …), api and worker depend on shared via workspace
  sources, single root lockfile, Python pinned to 3.12.
- Worker skeleton: `manzil` CLI entry point (`manzil ingest <url>` stub until
  P0-10), `stages/`, `fetching/`, `llm/prompts/`, `agents/` subpackages,
  `tests/fixtures/{corpus,bench/labels,recorded}`, `evals/`.
- Shared scaffolding beyond P0-2: `errors.py` (exception taxonomy),
  `config.py` (tunables single home), `scoring/` stubs for P0-3.
- Tooling: ruff (line length 100) + `mypy --strict` on `shared/` configured at
  root; `supabase init`; `infra/.env.example`; `.gitignore`; `docs/adr/`.
- CI (`.github/workflows/ci.yml`): ruff check/format · mypy strict on shared ·
  per-package pytest with `MANZIL_LLM_MODE=replay`. Frontend job joins in
  Phase 1 (Vite scaffold deferred — pnpm not installed).
- Docs aligned: AGENTS.md / IMPLEMENTATION.md commands now use the
  `--package manzil-*` names (IMPLEMENTATION changelog v2.1).
