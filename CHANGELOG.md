# Changelog

Living log of what has landed in the **code**, newest first, keyed by the
IMPLEMENTATION.md §7 task IDs. Design changes go to DESIGN.md §20 (Decision
Log); doc-mechanics changes go to IMPLEMENTATION.md §9 — this file tracks the
repo itself.

## Unreleased — Phase 1

### 2026-07-08 — In-process worker loop wired (P1-3)

- API lifespan starts `run_worker_loop` when `MANZIL_WORKER_INPROCESS=true`
  (default); clean-shutdown drain via `stop` Event.
- `worker_loop.py` passes `settings.database_url` into `build_dispatch` so
  the per-domain adapter registry uses Postgres even when `DATABASE_URL` comes
  from the `.env` file (pydantic-settings does not populate `os.environ`).
- Test: `test_worker_inprocess` — job reaches `done` while `/v1/health` serves.

### 2026-07-08 — Durable Postgres queue + persistence (P1-2)

- `queue.py`: `claim_next_job` (`FOR UPDATE SKIP LOCKED`), `heartbeat`,
  `reclaim_orphans`, `run_worker_loop`, ingest dispatch + result projection.
- `postgres_persistence.py`: `Persistence` protocol over the `jobs` row +
  `job_events` timeline.
- Ingest results commit atomically with the DONE flip via
  `PostgresPersistence.on_done` — no window where a job is `done` with no
  result rows.
- Property-level-only scores (no scorable floor plan) fail loud: §8.2
  `scores.floor_plan_id NOT NULL` leaves nowhere to write them.
- Tests: interchange, orphan reclaim, atomic projection rollback.

### 2026-07-08 — Migration 0002 + dev-seed (P1-1)

- Migration `20260708000000_hunt_and_pipeline_tables.sql`: 4 enums, all §8.2
  per-hunt/pipeline tables, claim/heartbeat/job_events indexes,
  `extractions.hunt_id` FK, hunt-scoped extraction index; no RLS (P2-1).
- `scripts/dev_seed.py`: enqueues three ingest jobs against committed
  `fixtures/pages/` in replay mode; committed seed recordings in
  `fixtures/recorded/`.
- Tests: `test_migration_0002_schema`, `test_dev_seed` (1 hunt / 3 listings /
  non-zero scores).

## Unreleased — Phase 0

### 2026-07-07 — Eval kit goes local: corpus + bench labels gitignored (DESIGN v2.8)

- `fixtures/corpus/` (scraped pages: copyrighted third-party content with
  embedded vendor keys) and `fixtures/bench/labels/` (ground truth about those
  exact local snapshots) are **gitignored**; tracked `.gitkeep` placeholders
  keep the dirs on fresh clones. `bench/manifest.md` and the smoke replay
  fixture stay tracked; other record-mode artifacts are ignored (keyed to
  local corpus content). Replaces the earlier blunt `raw.html` / `corpus/`
  ignore lines with anchored rules.
- `corpus_pages()` hardened: returns `[]` when the corpus dir is absent, so a
  fresh clone's test collection can't crash — the corpus sweep test skips as
  designed (new test pins this).
- Follow-through: P0-11 exit metric is now "20 labels present locally +
  backed up"; P1-1 dev-seed retargets committed synthetic `fixtures/pages/`;
  new backup runbook (IMPLEMENTATION §8) — the kit is unrecoverable if lost
  (delisted pages 404, hostile pages need tier 3).
- Reviewed and **reaffirmed unchanged**: the production cleaned-text retention
  design (facts in `extractions`, gzipped cleaned text in Storage, raw HTML
  transient — §20 2026-06-28). The repo decision is orthogonal to it.

### 2026-07-07 — Embedded structured-data miner (DESIGN v2.6)

- **Miner** (`fetching/structured.py`): listing sites server-render their
  *data* even when they don't render their DOM — JSON-LD plus framework state
  blobs (`__NEXT_DATA__`, `window.__PRELOADED_STATE__ = {…}`, bare-JSON state
  scripts) carry the floor plans, unit rents, sqft and fees that never reached
  tier-1 cleaned text. The cleaner now appends a pruned digest of them under
  `[EMBEDDED DATA]`. Deterministic, zero LLM; EXTRACT's contract unchanged.
- Pruning is drop-before-keep: `similar`/`nearby` subtrees are dropped first
  (another property's prices = contamination), media/URL bulk scrubbed,
  digest capped at `EMBEDDED_DATA_MAX_CHARS` (40k). JS object literals are
  unminable by design — no JS evaluation, ever.
- Classifier: positive cleaned-text check now runs **before** the JS-shell
  signature, and `has_listing_signal` matches rental-fact JSON keys
  (`"priceLow":` …) — empty-DOM data-shipping pages (zumper, padmapper style)
  settle at tier 1 instead of escalating.
- `save_page` tolerates an already-domain-prefixed slug (no more
  `domain--domain--slug` fixture dirs); corpus regenerated — 16 pages,
  cleaned text now carries unit-level rents/sqft/availability at tier 1.
- Tests: `test_structured.py` (14) — LD kept/boilerplate dropped, assignment
  and bare-JSON blob parsing, contamination drop, scrub, cap, dedupe,
  shell-rescue and true-shell classifier cases.

### 2026-07-07 — Tier 3 (free plans only, DESIGN v2.5) + slug-hint stopgap

- **Tier 3 fetcher** (`fetching/tier3.py`): managed-unblocker adapter behind a
  provider seam — Bright Data Web Unlocker default, ScrapingBee alternate,
  selected by `MANZIL_TIER3_PROVIDER`; off the ladder entirely until the
  selected provider's key env is set. Free plans only; paid escalation
  requires a new DESIGN §20 decision (v2.5 entry records the rationale).
- Ladder/registry: `MAX_TIER` 2→3; start tier clamps to available fetchers
  (a domain recorded as needing tier 3 no longer crashes a keyless run);
  escalation skips missing rungs (`{1,3}` under `--no-tier2`). CLI grew
  `--no-tier3` on `ingest` / `save-page` / `census`.
- Census: `tier3_outcome` column; verdicts now end the argument —
  `tier3_ok` (vendor wins), `hostile_unfetchable` (blocked even at 3),
  `hostile_needs_tier3` preserved for tier-3-less runs.
- **Stopgap** (`fetching/slug_hint.py`): deterministic property identity from
  the URL slug; FETCH's `source unfetchable` error now says e.g. `try
  searching "riverfront towers detroit mi" on a fetchable source` — zero LLM, the
  human stand-in for DISCOVER's sibling-source rescue until P3-5.
- New tunable `TIER3_TIMEOUT_SECONDS` (90 s — vendors solve challenges
  server-side). 17 new tests (provider seam via httpx MockTransport, ladder
  gaps/clamps, census verdicts, slug hints, e2e error hint).

### 2026-07-07 — P0-11/12/13 (code halves): bench labels, eval harness, model compare

- **P0-11 (loader + scaffolding; labels themselves stay human-only)**:
  `evals/labels.py` pins the label format — `criteria` (true values, validated
  against the catalog `value_schema` through the new
  `schema_gen.value_adapter`), `unknown` (model must emit null), optional
  `floor_plans`; absent keys aren't graded. Loader hard-fails on unfilled
  skeletons, unknown keys, out-of-schema values, criteria/unknown overlap.
  `manzil bench-skeleton <slug>` scaffolds a fill-in-the-blanks label from a
  corpus page and seeds `bench/manifest.md`. Skeletons committed for the two
  existing corpus pages (autumn-ridge, windsor-woods) as labeling starters.
- **P0-12 (harness L0)**: `evals/harness.py` runs the real EXTRACT → VERIFY
  stages over saved corpus text per label (no refetch), grades criterion /
  gate / unknown accuracy, evidence-flag counts, and floor plans (name-matched,
  only label-stated fields compared). Per-listing failures (missing corpus
  page, replay miss, stage error) are recorded, never abort the run.
  `manzil bench-run` writes `worker/evals/reports/{name}.json` and prints the
  summary table; traces are `bench/{stage}` with session = job_id and
  `listing_slug` metadata (IMPL §6).
- **P0-13 (compare tooling)**: `evals/compare.py` + `manzil bench-compare`
  render the §11.2 side-by-side decision table over N reports; a sweep is
  `MANZIL_MODEL_EXTRACT=… manzil bench-run --name …` per candidate. The table
  informs the pin decision; it never edits `llm/config.py`.
- 20 tests over labels + harness + compare, proven against the authored
  synthetic e2e page. Still human-blocked: the 20 real labels, record-mode
  runs (provider key), and the P0-13/P0-14 decisions.

### 2026-07-06 — Seam: Langfuse v4 fix + multi-provider dispatch (bench prereq)

- **Langfuse v4**: the installed SDK (4.13) removed v3's `update_current_trace`;
  `_traced_live_call` now sets trace name + session via `propagate_attributes`.
  `worker` pins `langfuse>=4`. First live traced call still pending a provider
  key in `.env` (only the Langfuse pair is set) — the run now fails exactly at
  the provider-key guard, past all tracing setup.
- **Multi-provider seam** (DESIGN §11.1 "swapping providers is one adapter";
  needed so P0-13 can bench Gemini at all): `_live_call` dispatches on the
  model-ID prefix — `claude-*` → Anthropic (forced tool, cache_control),
  `gemini-*` → Google (`response_schema` structured output, implicit caching,
  thinking disabled on the 2.5 Flash family, usage normalized so
  `input_tokens` = uncached input). Tracing, record/replay, and the cost
  tally sit above the dispatch and are provider-blind.
- `llm/config.py`: per-provider cache multipliers (Anthropic 10% read / 125%
  write; Gemini 25% read / no write premium); §11.2 bench candidates
  `gemini-2.5-flash-lite` (0.10/0.40) and `gemini-2.5-flash` (0.30/2.50)
  priced. New `MANZIL_MODEL_<STAGE>` override for bench/dev runs — refused
  unless the model is priced, so cost accounting never guesses.
- Deps: `google-genai` added; `python-dotenv` declared (cli.py imported it
  transitively). Note: plain `uv sync` uninstalls workspace-member deps —
  the documented command is now `uv sync --all-packages`.
- Adopting a non-Anthropic model as a *default* pin remains gated on bench
  evidence + a DESIGN §20 entry (P0-14); nothing changed in the pins.

### 2026-07-06 — P0-10 followup: SCORE honors `min_confidence` (v2.3 contract)

- Correction: effective values in the SCORE stage are now
  confidence-thresholded per the DESIGN v2.3 hunt-settings contract —
  anything below `min_confidence` (default `medium`, injected via
  `StageCtx.min_confidence`) scores as unknown. Concretely: a VERIFY-demoted
  value on a gate-bearing criterion now **fires the gate** rather than
  letting suspect data pass; the value stays on `reconciled` as provenance,
  and a Phase 1 `confirm_value` checkpoint answer is the path back up.
- Floor-plan figures have no confidence dimension yet and are not
  thresholded. Both directions test-pinned: `medium` gates a demoted
  pets_policy; `min_confidence=low` admits it (total 13.5 restored).

### 2026-07-06 — P0-10 followup: VALIDATE_URL stage (DESIGN v2.4 ruling)

- The VALIDATE ordering conflict is resolved by splitting the stage (DESIGN
  v2.4, §20): `stages/validate_url.py` now heads the spine — deterministic,
  zero-LLM checks of the submitted URL itself (http(s) scheme, public host
  with private/loopback refused as an SSRF guard, no binary extensions) plus
  URL normalization (whitespace/fragments stripped, canonical form written
  back to RunState). VALIDATE keeps its content judgment, explicitly after
  FETCH.
- Spine order: **VALIDATE_URL → FETCH → VALIDATE → EXTRACT → VERIFY →
  SCORE**. Tests: 17 cases over good/garbage/private/binary URLs plus an e2e
  bad-URL run proving failure lands before any fetch or LLM call.

### 2026-07-06 — P0-10: RunState + runner + CLI `manzil ingest <url>`

- `state.py`: RunState per the IMPL §3 proposal (with `source_policy`), plus
  fields the CLI/eval harness need on the state: `status`, `error`,
  `verify_flags`, `effective_values`, `scores` (per-plan §9.3 contract
  dicts), `display_score_index`; `cost_usd` is float, matching the seam's
  tally.
- `runner.py`: persist-BEFORE-advance runner (two saves per stage: outputs at
  the old cursor, then the advance), StageRetryable backoff
  (`10s·2^attempt` jittered, sleep injected for tests), fatal mapping,
  CheckpointRaised → persisted + parked `waiting_user`, cursor resume.
  Phase 0 stage order **FETCH → VALIDATE → EXTRACT → VERIFY → SCORE** —
  content-based VALIDATE requires the primary fetch first (flagged against
  §10.1's diagram order).
- `stages/score.py`: single-source reconciliation, effective values (known
  values score regardless of confidence — demotions are provenance),
  `all_in_monthly` interim composition = conservative advertised rent
  (rent_max, never the teaser rate; full §9.5 lands P3-9), per-plan fan-out +
  best-plan display (§9.4).
- `phase0_rubric.py`: the §19 hardcoded rubric as a code fixture (2 br ·
  in-unit laundry · cats · balcony · all-in < $2,000 — the first three and
  all-in as non-negotiables), rubric version 0.
- `persistence.py`: atomic JSON run files under `.manzil/runs/` (gitignored);
  P1-2 swaps in the jobs row behind the same protocol.
- CLI `manzil ingest <url>` is live: prints status, verify flags, per-plan
  breakdowns with gate firings, display-score marker, cost, run-file path.
  Exit codes: 1 failed, 2 agents-mode (no pipeline yet), 3 waiting_user.
- Tests: runner semantics (persist-before-advance snapshot order, resume,
  retry/backoff, fatal, checkpoint), score-stage assembly (teaser-rate test
  pinned), and the e2e spine over a committed fixture listing — real ladder +
  cleaner + classifier + engine, fake transport + LLM — asserting the exact
  13.5 breakdown and the failure paths (non-listing, blocked).

### 2026-07-06 — P0-9: VERIFY stage — checks 1-3 code, check 4 call

- `stages/verify.py` per §10.5: **(1)** evidence audit — every non-null
  value's quote must fuzzy-match the page (rapidfuzz partial_ratio ≥
  `EVIDENCE_FUZZY_THRESHOLD`), missing/unlocatable evidence demotes to low;
  **(2)** schema conformance re-checked post-parse against the catalog field
  models; **(3)** plausibility on static cold-start bounds — new tunables
  `RENT_PLAUSIBLE_MIN/MAX`, `SQFT_PER_BED_MIN/MAX`,
  `DEPOSIT_MAX_RENT_MULTIPLIER` (self-derived metro bands need accumulated
  listings; Phase 0 is always cold start); **(4)** cross-field consistency —
  exactly one P1 call (`prompts/verify.md` v1) returning contradictions that
  demote the named criteria.
- Demotions keep the value and record a `VerifyFlag` (criterion, check,
  note) on RunState — provenance shows the doubt. Gate-relevant escalation to
  `confirm_value` checkpoints activates in Phase 1 (needs jobs/waiting_user).
- Injection fixture committed (`fixtures/pages/injection_listing.html`, an
  embedded "report rent as $1/month" notice) and test-pinned: a fabricated
  quote dies at the evidence audit; the injected figure — whose quote IS on
  the page — dies at plausibility. Injection degrades to a flagged low-trust
  value, never an action (§16).

### 2026-07-06 — P0-8: dynamic extraction schema + VALIDATE + EXTRACT

- `stages/schema_gen.py`: the extraction schema generated at runtime from
  `criteria_catalog` via dynamic Pydantic model creation — every field
  `{value, confidence, evidence_quote}`, catalog label + extraction_hint as
  the field description (so hints ride inside the cached tool schema), enum/
  bounds enforced, extras forbidden, every criterion field required (unknown
  = value null + confidence not_found). Includes only page-text criteria:
  tool-dependent (maps/web-search/vision) and pipeline-composed
  (`all_in_monthly`) keys are excluded — extraction stages get zero tools
  (§16). Plus `floor_plans`: list of per-plan extractions (name, beds,
  baths, sqft/rent ranges, deposit, availability).
- `stages/validate.py` (+ `prompts/validate.md` v1): heuristics first — pages
  without currency/bed-bath/address signals (classifier's
  `has_listing_signal`, now public) or under the text floor are rejected
  with zero LLM spend; the rest get one forced-schema confirm. Not-a-listing
  is StageFatal with the reason.
- `stages/extract.py` (+ `prompts/extract.md` v1): full-catalog P1 call; on
  schema-validation failure, one corrective retry with the validation error
  appended, then `ExtractionInvalid` (§10.2 P1 rule — test-pinned). Every
  extraction stamped with source URL, model, and prompt version.
- `stages/base.py`: the Stage protocol + StageCtx (fetchers, registry,
  call_structured, rubric, persistence, clock, sleep — injected so tests
  fake the world wholesale).
- Fixtures: `e2e_listing.html` (a fully-controlled synthetic listing whose
  ground truth lives in tests/conftest.py) joins the synthetic pages set.

### 2026-07-06 — P0-7: LLM client seam + Langfuse + record/replay

- `llm/client.py`: the §11.1 seam — `call_structured` live (forced tool use:
  the schema is a tool the model must call, so prose answers are impossible);
  `call_agent` / `call_vision` pinned signatures, stubbed until their first
  consumers (P3-5, P3-7). Resolves model + prompt by stage, applies
  `cache_control` to the stable prefix, and hard-fails a live call when
  Langfuse keys are unset — an untraced call is a bug (NFR6), not a degraded
  mode. Replay serves fixtures without tracing (not a model call; CI has no
  keys).
- `llm/config.py`: per-stage model map (Haiku 4.5 workhorse / Sonnet 4.6
  taste tier per §11.2 baseline; P0-13 bench rewrites this file), max-tokens
  per stage, list prices for the cost tally. Unknown stage is an error, never
  a fallback.
- `llm/prompt_loader.py` + `prompts/{stage}.md`: front-matter (`id`,
  `version`, `cacheable_prefix_marker`), body split at the marker into
  cacheable prefix vs per-call text (IMPL §4). First prompt: `smoke.md` v1.
- `llm/recording.py`: record/replay store per IMPL §5 — hash covers
  `(stage, model_id, prompt_version, sha256(content))`; fixtures land in
  `tests/fixtures/recorded/{stage}--{hash16}.json`; replay miss raises
  (CI fails rather than spends).
- Ambient context: `run_context` (trace = `{job_type}/{stage}`, session =
  `job_id`, `listing_slug` metadata) and `cost_tally` context managers —
  P0-10's runner sets both around each stage and adds the tally onto
  RunState.
- CLI `manzil llm-smoke`: one structured call through the seam (the "traced
  call visible in Langfuse" gate); in `record` mode it refreshes the exact
  fixture the replay test reads. A seeded synthetic recording is committed so
  replay is green pre-first-live-run.
- Tests (14): prompt parsing/splitting + loud failures, request-hash
  component coverage, committed-fixture replay, replay-miss failure,
  record→replay round trip with a stubbed provider, cost-tally math,
  NFR6 no-Langfuse refusal, unknown-stage refusal.
- Deps: `anthropic`, `langfuse` added to `worker/` (SDK imports stay inside
  `llm/`, lazy, so replay-mode CI never touches them).

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
