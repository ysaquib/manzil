# Phase 1 Completion Plan — Manzil

## Context

Phase 0's spine is done and its tail (P0-11 bench labeling, P0-12/13 real runs, P0-14 decisions) is human-blocked but blocks nothing in Phase 1. Phase 1 ("replace the spreadsheet") was entered on 2026-07-07 with a settled task table (IMPLEMENTATION.md §7) — this plan executes what remains of it, plus the user-requested additions: dark-mode toggle + theme polish, README refresh, decision-log updates, and an L1 write-up.

**Current state (verified by exploration):**

| Area | State |
|---|---|
| Frontend (P1-9..P1-13) | **Built.** All pages (Overview, detail drawer, rubric wizard, Tasks Active, settings, hunt switcher, magic-link auth) wired to real contracts with vitest coverage. Blocked end-to-end only by the missing backend. |
| API (P1-4) | Skeleton done. **All 16 route handlers raise `NotImplementedYet`.** Auth chain (`get_current_user`, `get_user_client`, `require_owner`) is wired. |
| Migration 0002 (P1-1) | **Missing.** No `hunts`/`hunt_listings`/`jobs`/`scores`/etc. tables; frontend Supabase reads have nothing to read. |
| Queue + worker loop (P1-2/3) | **Missing.** `worker/queue.py` and `postgres_persistence.py` don't exist; the API lifespan glue import-fails defensively. |
| Rescore job (P1-6) | **Missing.** |
| Dark mode | **Missing** (no `useMantineColorScheme` anywhere). Custom theme exists (indigo, semantic roles). |
| Known contract conflicts | `frontend/API_ASSUMPTIONS.md` records two, decided by Yusuf 2026-07-08: (1) API `RubricOption` schema must be corrected to the DESIGN §8.2 pinned shape `{match:{op,value}, delta, dealbreaker_set_score}`; (2) `JobResponse` must carry the parked checkpoint prompt. Frontend already follows DESIGN. |

Critical path: **P1-1 → P1-2/P1-3 → P1-5..P1-8 (incl. P1-6) → frontend reconciliation → exit review.** Design polish + docs run alongside.

## Orchestration (agents & models)

Per the global orchestration policy: main session (Fable) keeps sequencing, review of agent output, and doc-authority judgment; volume work is delegated. Every non-trivial step gets a fresh-context `verifier` pass before being reported done.

| Step | Agent | Model |
|---|---|---|
| 1, 2, 3, 4 (backend build) | `executor` | opus (pinned in agent def) |
| Authz review of API handlers | `security-executor` | opus |
| 5 (frontend reconciliation) | `executor` | opus |
| 6 (dark mode + polish) | `executor` + frontend-design skill | opus |
| 7 (docs: README, changelog, API_ASSUMPTIONS) | `mech-executor` | sonnet |
| Verification gates after steps 2, 4, 5, 6 | `verifier` | opus |
| Spot lookups during review | `scout` | haiku |

## Steps

### Step 1 — P1-1: Migration `0002_hunt_and_pipeline_tables.sql` + dev-seed
Exactly per the settled IMPLEMENTATION §7 row: 4 enums (`hunt_role`, `job_type`, `job_state`, `value_state`), every §8.2 per-hunt/pipeline table **verbatim** (hunts, hunt_members, hunt_listings, rubric_criteria, overrides, fee_checklist, scores, jobs, job_events, comments, ratings), indexes (latest-extraction, jobs claim/heartbeat, job_events), `extractions.hunt_id` FK, **no RLS** (deliberate, P2-1). `scripts/dev_seed.py` runs the ingest path against the 3 committed synthetic `fixtures/pages/` in `MANZIL_LLM_MODE=replay`.
**Done when:** `supabase db reset && uv run --package manzil-worker python scripts/dev_seed.py` leaves 1 hunt / 3 listings / non-zero scores, asserted by a small asyncpg pytest.
*Note: dev_seed initially writes via FilePersistence→direct inserts or lands after Step 2's persistence — executor sequences P1-1 table DDL first, seed script finalized against Step 2's `PostgresPersistence`.*

### Step 2 — P1-2 + P1-3: Queue mechanics, Postgres persistence, in-process loop
`worker/src/manzil_worker/queue.py`: `claim_next_job` (`FOR UPDATE SKIP LOCKED`), `heartbeat`, `reclaim_orphans` (every tick), `run_worker_loop` (dispatch by `job_type`, clean-shutdown drain via `stop: asyncio.Event`). `worker/src/manzil_worker/postgres_persistence.py` implements the existing `Persistence` protocol (same as `FilePersistence`, parametrized-fixture tested for interchangeability). The existing `api/worker_loop.py` import then resolves — verify jobs process while the API serves.
**Done when:** simulated kill mid-job → a second loop resumes from `current_stage` within `JOB_ORPHAN_AFTER`; clean shutdown loses no work.

### Step 3 — P1-5..P1-8 + P1-6: Implement the 16 stub handlers + rescore job
- **First, fix the two pinned-contract conflicts** (API_ASSUMPTIONS.md): correct `api/rubric/schemas.py` `RubricOption` to the §8.2 shape; add the parked checkpoint prompt to `JobResponse`.
- P1-5: Hunts CRUD, rubric GET/PUT (validate options vs `value_schema` via `jsonschema`, bump `rubric_version`, enqueue rescore), settings PATCH.
- P1-6: `worker/stages/rescore.py` + minimal rescore state — resolve effective values (latest extraction, `min_confidence`-thresholded, then latest override per §9.6), score each floor plan via `shared.scoring.engine.score`, upsert `scores`.
- P1-7: listings POST/GET/DELETE (+ `PATCH /pins`), jobs GET/cancel/retry/checkpoint. CLI and API paths must produce identical job rows.
- P1-8: overrides (append-only, attributed) + fee upsert, both ending in one rescore-job INSERT (**rescore-on-mutation**, never direct recompute).
- **Then a `security-executor` pass** over the finished routers: every route enforces the ownership stand-in (`require_owner`/`valid_listing_id` chains), no service-role leakage into user-facing paths, checkpoint-answer input validation.
**Done when:** the settled table's per-row criteria pass (invalid option rejected field-level; rubric edit rescores 3 seeded listings with breakdowns matching goldens; `min_confidence` flip rescores; override displays over extraction with original retrievable).

### Step 4 — Verifier gate on the backend
Fresh-context `verifier`: run `supabase db reset` + dev_seed + full pytest, exercise the API with real HTTP calls (authed round-trip, rescore flow, orphan-reclaim simulation). CONFIRMED required before Step 5.

### Step 5 — Frontend reconciliation
`pnpm gen:api-types` against the now-real `/openapi.json` (commit output); drop the two hand-typed conflict workarounds where the generated types now match DESIGN; update `frontend/API_ASSUMPTIONS.md` statuses (stub→implemented, no table→exists); fix any type drift; `pnpm -C frontend test && build`. Then drive the real flow end-to-end (login → create hunt → build rubric → submit listing URL → watch Tasks → see score in Overview → override → fee edit) via the `run`/Playwright flow against local Supabase + API.

### Step 6 — Dark mode + design polish (user-selected scope: "Polish + dark mode")
`executor` loads the **frontend-design skill** first. Keep Mantine structure and the existing semantic color roles; work only in `theme.ts` + targeted component props:
- Color-scheme toggle in the `AppLayout` header (`useMantineColorScheme`, persisted via Mantine's default localStorage `colorSchemeManager`, respect `prefers-color-scheme` on first load).
- Audit every view in dark mode: semantic roles (`estimated`/`manual`/`danger`/`active`/`waiting`), score color scale in `ScoreCell`, table row hover, drawer overlays, badge contrast — fix via theme tokens, not hardcoded hex (per frontend AGENTS.md rule).
- Light polish: typography scale, table density, spacing rhythm, empty states. No framework or layout changes.
**Done when:** every route renders correctly in both schemes; toggle persists; vitest still green (add a small toggle test).

### Step 7 — Docs & decision logs (`mech-executor`)
- **IMPLEMENTATION.md §9 changelog** (next entries, 2.0.17+): (a) P1-1/P1-2/P1-3 landed; (b) P1-5..P1-8 landed **including the RubricOption schema correction and JobResponse checkpoint field** (records Yusuf's 2026-07-08 conflict rulings from API_ASSUMPTIONS.md); (c) dark-mode toggle + theme polish (mechanics-level; DESIGN §7 already names dark mode as a Mantine capability — not a material design change, so **no DESIGN §20 entry needed**). If implementation surfaces any material deviation from DESIGN, stop and add a §20 entry per the hard rule.
- **DESIGN.md:** no §20 entries planned — nothing here changes design intent. (Phase 0 exit is *not* recorded: only 1/20 bench labels exist; P0-14's census + model-pin §20 entries stay pending.)
- **README.md:** update "Current phase" to Phase 0 tail ∥ Phase 1; add the essential Phase 1 commands — `supabase db reset` + dev_seed, running the API (`uv run --package manzil-api uvicorn manzil_api.main:app --reload` or equivalent), `MANZIL_WORKER_INPROCESS`, frontend `pnpm dev` / `test` / `build` / `gen:api-types`, the two-terminal local dev loop, and the eval-kit backup runbook pointer.
- Housekeeping: gitignore `worker/evals/reports/` (currently untracked; bench reports are local artifacts per §20 v2.8).

### Step 8 — P1-15 exit review (human + assisted)
Yusuf's real hunt through the UI, spreadsheet listings ingested, rubric via wizard, scores hand-checked; manual `kill -9` orphan-recovery verification; retire spreadsheet; revise the Phase 2 table. The agent side prepares a checklist; the week-of-real-use exit is human.

## L1 — what it is and what completing it takes

L1 (**extractor + critic A/B on the bench**) stays **gated on Phase 0 exit** — specifically P0-11's 20 hand labels and P0-13/14's model-pin decisions, since the A/B needs both a graded bench and a settled baseline. Nothing in this plan implements it. To complete L1 once the gate opens:

1. **Unlock ritual:** add the L-task table to IMPLEMENTATION §7 (the docs say it gets written when L1 unlocks, not before).
2. **Build (all inside `worker/src/manzil_worker/agents/`, LangGraph):** an extractor+critic pair that imports — never modifies — the deterministic truth layer (VERIFY checks 1–3, RECONCILE ladder, SCORE) and the RunState/persistence contract; runnable via `--mode=agents` against the bench only; Langfuse-traced from the first call (NFR6).
3. **Extend the L0 harness** to run both modes over the same labels and emit a comparison report: what the critic catches beyond deterministic VERIFY, at what token/latency cost.
4. **Decide on data:** keep-or-kill eval report in `docs/`; adoption into the default path only with bench evidence **and** a DESIGN §20 entry (§10.11 rule).

Prerequisite work already done: harness code (P0-12), record/replay seam, OpenRouter key, Langfuse verified. The only true blockers are the remaining ~19 labels and the P0-13/14 decisions.

## Verification (end-to-end)

```bash
supabase db reset && uv run --package manzil-worker python scripts/dev_seed.py   # P1-1 gate
uv run --package manzil-shared pytest shared/tests && \
uv run --package manzil-api pytest api/tests && \
uv run --package manzil-worker pytest worker/tests                              # all suites
uv run ruff check .                                                              # lint
pnpm -C frontend test && pnpm -C frontend build                                  # frontend
# manual/verifier: run API+worker in-process, submit a fixtures/pages URL via UI,
# watch Tasks tab, confirm score in Overview; kill -9 mid-job → restart → resumes;
# toggle dark mode on every route.
```

## Key files

- `supabase/migrations/0002_hunt_and_pipeline_tables.sql` (new), `scripts/dev_seed.py` (new)
- `worker/src/manzil_worker/queue.py`, `postgres_persistence.py`, `stages/rescore.py` (new)
- `api/src/manzil_api/{hunts,rubric,listings,jobs,overrides,fees}/service.py` + `rubric/schemas.py`, `jobs/schemas.py` (conflict fixes)
- `frontend/src/theme.ts`, `components/AppLayout.tsx`, `lib/generated/api.d.ts` (regen), `API_ASSUMPTIONS.md`
- `IMPLEMENTATION.md` §9, `README.md`, `.gitignore`

Reuse, don't rebuild: `Persistence` protocol (`worker/persistence.py`), stage runner (`worker/runner.py`), `shared.scoring.engine.score`, auth dependency chain (`api/dependencies.py`, `api/hunts/dependencies.py`), existing frontend hooks in `features/*/api.ts`.
