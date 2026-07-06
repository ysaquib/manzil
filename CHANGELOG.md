# Changelog

Living log of what has landed in the **code**, newest first, keyed by the
IMPLEMENTATION.md §7 task IDs. Design changes go to DESIGN.md §20 (Decision
Log); doc-mechanics changes go to IMPLEMENTATION.md §9 — this file tracks the
repo itself.

## Unreleased — Phase 0

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
