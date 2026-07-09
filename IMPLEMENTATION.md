# Manzil — Implementation Notes

| | |
|---|---|
| **Version** | 2.0 |
| **Status** | Living — churns freely, no ceremony required. **v2.0 is the implementation-start baseline**: further changes should come from code reality, not further pre-code polishing |
| **Sibling** | `DESIGN.md` (intent + contracts; wins all conflicts about *what* and *why*) |
| **Repo location** | `/IMPLEMENTATION.md` |

**Division of authority:** DESIGN.md owns intent, requirements, and cross-component contracts. This document owns *current mechanics* — how things are actually built right now. Code and docstrings win on exact interfaces; this doc points at modules rather than duplicating signatures once they exist. If this doc and DESIGN.md disagree, stop and flag it (CLAUDE.md rule) — do not silently pick a side. Update protocol here is deliberately lightweight: edit in place, add a line to the [Changelog](#9-changelog). No decision-log ceremony; that lives in DESIGN.md §20 for *design* changes only.

**Status labels.** Every section below carries one, so nobody — human or agent — has to guess how binding a given detail is:

- **Settled** — follow as written. Changing it takes a changelog entry (and a DESIGN §20 entry if it touches intent).
- **Proposal** — seeds the first implementation, then *follows the code*. Divergence here is expected and is not a doc/code conflict; update the doc to match reality without ceremony.
- **Interim / Conditional** — deliberately temporary or outcome-dependent, with the removal point or gating condition named inline.

---

## Contents

1. [Environment and Setup](#1-environment-and-setup)
2. [Coding Conventions](#2-coding-conventions)
3. [Core Interfaces](#3-core-interfaces)
4. [Prompt Management](#4-prompt-management)
5. [Testing and Fixtures](#5-testing-and-fixtures)
6. [Observability](#6-observability)
7. [Phase Work Plans](#7-phase-work-plans)
8. [Runbooks](#8-runbooks)
9. [Changelog](#9-changelog)

---

## 1. Environment and Setup

*Status: settled.*

### Prerequisites
`uv` ≥ 0.5 · Node 20 + `pnpm` · Supabase CLI · Playwright (`uv run playwright install chromium` after worker sync).

### Bootstrap (once)
```bash
uv init --bare                              # root pyproject
# add [tool.uv.workspace] members = ["shared","api","worker"] to root pyproject.toml
uv init --lib shared && uv init --app api && uv init --app worker
# in api/ and worker/ pyproject: dependencies += ["manzil-shared"]
#   [tool.uv.sources] manzil-shared = { workspace = true }
uv sync --all-packages   # plain `uv sync` installs only the root package's deps

pnpm create vite frontend --template react-ts
supabase init && supabase start             # local stack
ln -s CLAUDE.md AGENTS.md
```

### Environment variables (`infra/.env.example`)

| Var | Used by | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | worker | sole LLM gateway (OpenRouter); replaces direct Anthropic/Google keys |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | worker | cloud free tier; wired before first LLM call (NFR6). The API makes no LLM calls and gets no Langfuse keys |
| `DATABASE_URL` | worker, api | direct Postgres (worker uses service-level access) |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` | frontend, api | anon key is RLS-safe by design |
| `SUPABASE_SERVICE_ROLE_KEY` | worker, api | worker always; api holds it from Phase 1 only for the in-process lifespan worker loop (P1-3) — still never in frontend env |
| `MANZIL_WORKER_INPROCESS` | api | `true` in Phase 1 (P1-3, budget option per DESIGN §5); flips to `false` at P3-1 (separate paid worker service) with no code change |
| `API_CORS_ORIGINS` | api | frontend dev origin(s), comma-separated |
| `API_ENVIRONMENT` | api | `local` \| `staging` \| `production` — gates OpenAPI docs exposure |
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` | frontend | public, RLS-safe by design |
| `VITE_API_BASE_URL` | frontend | e.g. `http://localhost:8000` locally |
| `MANZIL_TIER3_PROVIDER` | worker | `brightdata` (default) \| `scrapingbee` — tier-3 unblocker adapter (§10.7, free plans only) |
| `BRIGHTDATA_API_KEY` / `BRIGHTDATA_ZONE` | worker | Bright Data Web Unlocker; zone defaults to `web_unlocker1`. No key = tier 3 off the ladder |
| `SCRAPINGBEE_API_KEY` | worker | only when `MANZIL_TIER3_PROVIDER=scrapingbee` |
| `GOOGLE_MAPS_API_KEY` | worker | Phase 3 |
| `MANZIL_MODE` | worker | `workflow` (default) \| `agents` |
| `MANZIL_LLM_MODE` | worker, tests | `live` \| `record` \| `replay` (see §5) |
| `MANZIL_MODEL_<STAGE>` | worker, bench | per-stage model-pin override for bench/dev runs (e.g. `MANZIL_MODEL_EXTRACT=google/gemini-2.5-flash-lite`); must be priced in `llm/config.py` |

### Daily loop
```bash
supabase db reset                            # migrations + generated seed
uv run --package worker manzil ingest <url>  # Phase 0 entry point
#   (`manzil` is a [project.scripts] entry in worker/pyproject.toml → manzil_worker.cli:app)
uv run --package shared pytest               # engine goldens
uv run --package worker pytest               # stages vs fixtures (replay mode)
uv run ruff check --fix . && uv run ruff format .
```

---

## 2. Coding Conventions

*Status: settled — except the exception taxonomy below, which is a proposal (its names and granularity will follow what the runner actually needs).*

**Python.** 3.12, `ruff` for lint+format (line length 100), full type hints — `mypy --strict` on `shared/` (the engine must be airtight), standard on the rest. Worker is async end-to-end; no blocking I/O outside `asyncio.to_thread`. Logging via `structlog`, never `print`; every log line in the worker carries `job_id` and `stage`.

**Import direction (enforced by convention now, `ruff` isort sections + a lint script later):** `shared` imports nothing from `api`/`worker`. `api` and `worker` import `shared`. `worker/.../agents/` imports the truth layer and runner contracts; **nothing outside `agents/` imports from `agents/`**. Only `worker/.../llm/` imports provider SDKs.

**Exception taxonomy** (in `shared/errors.py` — stages raise these, the runner maps them to job outcomes):
`StageRetryable` (backoff + retry) · `StageFatal` (job → failed) · `FetchBlocked` / `FetchShell` (tier escalation signals) · `ExtractionInvalid` (one corrective retry, then fatal) · `AgentBudgetExceeded` (agents mode; stage decides fallback) · `CheckpointRaised(prompt)` (runner persists → `waiting_user`).

**Database access (the gap a developer hits in week one of Phase 1):** no ORM. The **worker** connects directly via `asyncpg` with the service role — plain SQL, Pydantic mapping at the boundary, `FOR UPDATE SKIP LOCKED` and the scheduler queries are hand-written and tested. The **API** performs user-context mutations through `supabase-py` with the caller's access token, so PostgREST evaluates RLS with the real JWT — the API never simulates permissions it can hand to the database. The narrow exception: API operations that legitimately need the service role (accepting an invite writes `hunt_members` before membership exists) go through an explicitly named `privileged.py` module — small on purpose, so privileged surface is greppable. **Frontend** reads table data straight from Supabase (RLS-guarded selects, per DESIGN §5.1) and mutates only via the API.

**CI (GitHub Actions):** four jobs on every PR — `ruff check` + `ruff format --check`; `mypy --strict` on `shared/`; `pytest` for all packages with `MANZIL_LLM_MODE=replay` (a replay miss fails the build — CI cannot spend tokens); frontend `eslint` + `vitest` from Phase 1. Branching: trunk-based, short-lived branches named by task ID (`p0-7-llm-seam`); merge = green CI, no other ceremony solo.

**Frontend** (fills in at Phase 1): TS strict; server state exclusively via TanStack Query keyed by table+hunt; no `useEffect` data fetching; Mantine components only (no bespoke CSS until something forces it). Component tests with `vitest` + Testing Library for anything with logic (score cell states, rubric widgets from `value_schema`); no snapshot tests.

---

## 3. Core Interfaces

*Status: proposal — every interface in this section.* Reviewed during the v1.1 critique and **deliberately left unhardened**: pinning `RunState` fields or client signatures before code exists would invert the authority order (code owns exact interfaces) and manufacture doc/code conflicts out of ordinary iteration. The critique's job was removing ambiguity a developer *must* resolve to proceed; these are ambiguities the code is supposed to resolve. When the real interfaces stabilize (expect: end of Phase 0), update this section to match them and note it in the changelog — or replace the bodies with pointers to the modules.

### RunState (`worker/src/manzil_worker/state.py`)
```python
class RunState(BaseModel):
    job_id: UUID
    job_type: JobType                     # ingest | refresh | rescore | investigate
    mode: Literal["workflow", "agents"] = "workflow"
    url: str
    source_policy: SourcePolicy = "tiers_1_2_3"   # §10.7; read by PLAN + DISCOVER
    hunt_listing_id: UUID | None = None   # None in Phase 0 CLI runs
    plan: PlanManifest | None = None      # §10.4 contract shape
    cursor: int = 0                       # index into the stage list
    property_id: UUID | None = None
    sources: list[SourceState] = []       # url, tier_used, outcome, cleaned_path, hash
    extractions: dict[str, list[FieldExtraction]] = {}   # criterion_key -> per-source
    reconciled: dict[str, FieldExtraction] = {}
    floor_plans: list[FloorPlanIn] = []
    checkpoint: CheckpointPrompt | None = None           # §10.10 contract shape
    cost_usd: Decimal = Decimal("0")
```
`FieldExtraction = {value, confidence, evidence_quote, source_id, model, prompt_version}`.

### Stage protocol and runner (`runner.py`)
```python
Stage = Callable[[RunState, StageCtx], Awaitable[RunState]]
# StageCtx: db, llm, fetcher, clock, tracer — injected, so tests fake them wholesale
```
Runner behavior (DESIGN §10.2): persist state → advance cursor → heartbeat `locked_at`; on `CheckpointRaised` persist prompt and park as `waiting_user`; on `StageRetryable` retry with backoff per the tunables table.

### LLM client seam (`llm/client.py`)
```python
async def call_structured(stage: str, schema: type[T], content: str | list[Block]) -> T: ...
async def call_agent(stage: str, task: str, tools: list[Tool], max_turns: int = 8) -> AgentResult: ...
async def call_vision(stage: str, schema: type[T], images: list[ImageRef]) -> T: ...
```
The seam resolves model + prompt from `llm/config.py` by `stage`, routes all live calls through OpenRouter's OpenAI-compatible API (forced-tool structured output, `cache_control` on stable prefixes, upstream provider pinning), emits the Langfuse trace, tallies cost onto the active `RunState`, and honors `MANZIL_LLM_MODE` (record/replay, §5). Nothing else imports the SDK.

### Tunables (`shared/config.py` — single home, no magic numbers in stage code)

The single-home rule itself is **settled**; every *value* in this table is a starting point expected to be tuned against Phase 0 reality (tune freely, changelog-note the change).

| Name | Initial value | Where used |
|---|---|---|
| `EVIDENCE_FUZZY_THRESHOLD` | 85 (rapidfuzz partial_ratio) | VERIFY check 1 |
| `RENT_AGREE_PCT` / `SQFT_AGREE_PCT` | 3% / 5% | RECONCILE rung 2 |
| `PLAUSIBILITY_COLD_START_N` | 8 listings per metro | VERIFY check 3 |
| `STAGE_RETRIES` / backoff | 3, `10s · 2^attempt` jittered | runner |
| `JOB_ORPHAN_AFTER` | 5 min without heartbeat | queue reclaim |
| `AGENT_MAX_TURNS` | 8 | P3 loops |
| `CHECKPOINT_TIMEOUT` | 24 h | scheduler sweep |
| `MAX_IMAGES` / `IMAGE_MAX_DIM` | 8 / 1024 px | VISION |
| `FETCH_MIN_BODY_BYTES` | 5 000 | outcome classifier |
| `RENT_PLAUSIBLE_MIN` / `RENT_PLAUSIBLE_MAX` | 400 / 10 000 | VERIFY check 3 cold-start static band |
| `SQFT_PER_BED_MIN` / `SQFT_PER_BED_MAX` | 250 / 2 500 | VERIFY check 3 sqft-per-bed ratio band |
| `DEPOSIT_MAX_RENT_MULTIPLIER` | 2.0 | VERIFY check 3 (deposit ≤ ~2× rent) |
| `CLEANED_TEXT_MIN_CHARS` | 800 | outcome classifier (positive-content floor) |
| `SHELL_SCRIPT_RATIO` | 0.7 | outcome classifier (JS-shell signature) |
| `TIER2_MIN_DELAY_SECONDS` | 3.0 | tier-2 per-domain politeness |
| `TIER3_TIMEOUT_SECONDS` | 90.0 | unblocker request timeout (vendor solves challenges server-side) |
| `EMBEDDED_SCRIPT_MIN_CHARS` | 500 | structured-data miner (candidate state-blob floor) |
| `EMBEDDED_DATA_MAX_CHARS` | 40 000 | structured-data miner (digest cap in cleaned text) |

---

## 4. Prompt Management

*Status: settled.*

Prompts live as markdown files in `worker/src/manzil_worker/llm/prompts/{stage}.md` with a tiny front-matter header (`id`, `version`, `cacheable_prefix_marker`). The client loads by stage, splits at the marker — everything above it is the stable prefix sent with `cache_control` (schema text, rules, few-shots); everything below is per-call. `prompt_version` is recorded on every extraction row and every Langfuse trace, which is what makes the §8 prompt-change runbook enforceable. Prompt files are code: reviewed in PRs, never edited in place without a version bump.

---

## 5. Testing and Fixtures

*Status: settled.*

**Corpus layout** — one directory per saved listing page:
```
worker/tests/fixtures/corpus/{domain}--{slug}/
    raw.html        # as saved from the browser
    cleaned.txt     # produced by the cleaner (regenerate when cleaner changes)
    meta.json       # url, saved_at, is_official, notes
```
**Bench** — `fixtures/bench/manifest.md` lists the ~20 chosen slugs and why; `fixtures/bench/labels/{slug}.json` holds hand-labeled ground truth for gate-bearing criteria + rent/fees (DESIGN §19 Phase 0).

**Local eval kit (DESIGN §20 v2.8)** — `corpus/` and `bench/labels/` are **gitignored** (scraped third-party pages with embedded vendor keys; labels are ground truth about those exact local snapshots). Only `.gitkeep` placeholders and `bench/manifest.md` are tracked. CI reads the committed synthetic `fixtures/pages/` only; the corpus sweep test skips when the corpus is empty. Back the kit up (§8) — delisted/hostile pages cannot be re-fetched.

**Record/replay** — `MANZIL_LLM_MODE=record` runs live and writes each call's request-hash → response to `fixtures/recorded/`. The hash covers `(stage, model_id, prompt_version, sha256(content))` — deliberately *not* the raw request object, so SDK upgrades and parameter reordering don't invalidate the cache, while any change that could alter model output does; `replay` (the CI default) serves from disk and **fails on any miss** — CI can never silently call a live model. Golden tests in `shared/tests/golden/` assert exact score breakdowns per the §9.3 contract; a change to the engine that alters any golden requires updating the golden *in the same PR with an explanation*.

---

## 6. Observability

*Status: settled.*

Langfuse initialized inside the client seam only. Trace naming: `{job_type}/{stage}`, session = `job_id`; metadata on every span: `mode`, `model`, `prompt_version`, `listing_slug` (bench) and token/cost figures. The eval harness reads its numbers *from Langfuse traces*, not from ad-hoc accounting — one source of truth for spend and latency in both modes.

---

## 7. Phase Work Plans

*Status: Phase 0 table settled · **Phase 1 table revised on entry** (2026-07-07, per `.claude/plans/phase-1-frontend-api.md`) — running in parallel with Phase 0's tail (P0-11..14), which blocks nothing here · Phase 2–3 tables provisional (revise on entry) · ⚠ items conditional on named gates.*

Granularity: each item ≈ one focused agent session, scoped to the DESIGN sections cited. Detail is deep for Phase 0 and deliberately coarse afterward — later phases get expanded here on entry, when reality has voted.

### Phase 0 (detailed)

| # | Task | DESIGN refs | Done when |
|---|---|---|---|
| P0-1 | Monorepo scaffold per §6 + CI (ruff, pytest-replay) | §6 | `uv sync` green; CI runs |
| P0-2 | `shared/`: domain models + catalog seed (19 criteria per DESIGN §8.2) + seed.sql generator | §3, §8.2 | catalog round-trips: python → SQL → loaded |
| P0-3 | Scoring engine + golden tests | §9.3, §9.4 | goldens cover gates, unknowns, bonus, clamp, multi-plan groups |
| P0-4 | Migration 0001: global tables + enums | §8.1–8.2 | `supabase db reset` clean |
| P0-5 | HTML cleaner (trafilatura + fee-table preservation) | §7 | cleaned.txt regenerated for full corpus; spot-check 5 |
| P0-6 | Fetch tiers 1–2 + outcome classifier + adapter registry | §10.7 | classifier fixture tests pass on corpus; census CSV emitted |
| P0-7 | LLM client seam + Langfuse + record/replay | §11.1, NFR6, §6 here | one traced call visible in Langfuse; replay test green |
| P0-8 | Dynamic extraction schema + VALIDATE + EXTRACT stages | §10.2 P1, §10.3, §8.2 | non-listing corpus page rejected by VALIDATE; extraction of 3 listing pages validates against schema |
| P0-9 | VERIFY stage (checks 1–3 code, check 4 call) | §10.5 | seeded-error fixtures caught; injection fixture demoted |
| P0-10 | RunState + runner + CLI `manzil ingest <url>` | §10.1–10.2 | end-to-end score breakdown prints for a live URL |
| P0-11 🧍 | Bench labeling (hand) + label loader — zero code dependencies, start alongside P0-1 | §19 | 20 labels present locally + backed up (labels are gitignored local assets, DESIGN §20 v2.8) |
| P0-12 | Eval harness (L0): workflow mode vs labels | FR11 | accuracy/tokens/latency report generated |
| P0-13 | Model bench across Haiku / 2.5 Flash-Lite / 2.5 Flash | §11.2 | per-stage model choices written to `llm/config.py` |
| P0-14 | Close the gates: census verdict + model decisions → DESIGN §20 | §19 | two decision-log entries merged |

These tables are written from DESIGN contracts, so the *breakdown* is stable — but items marked ⚠ depend on Phase 0/1 outcomes (census verdict, model choices, in-process-worker experience). **Entering a phase means revising its table first**, not obeying it blindly; that review replaces the old "expand on entry" rule.

**Sequencing:** row order is the default dependency order, not a mandate — tasks without a data dependency parallelize freely (frontend and API rows in Phase 1 are two independent tracks after P1-4). Human-only tasks are marked 🧍 and should start immediately regardless of position, since they block nothing and nothing blocks them.

### Phase 1 — replace the spreadsheet (single user)

Revised on entry against `.claude/plans/phase-1-frontend-api.md` (the Phase 1 plan document — read it for full directory trees, sketches, and sequencing; this table records the decisions it settled). Key cross-cutting calls the plan made, referenced by short names below: **API layout** — domain-oriented package layout + chain-of-dependencies adapted from fastapi-best-practices, *not* SQLAlchemy/ORM (IMPLEMENTATION §2's DB-access rule stands: `service.py` wraps `supabase-py`/PostgREST); **ownership stand-in** — `current_user.id == hunt.owner_id` in place of the Phase 2 role matrix, shaped so P2-1/P2-2 change only the dependency body; **rescore-on-mutation** — every scoring-input mutation (rubric PUT, settings PATCH, override POST, fee POST/PATCH) ends its service function with one `rescore` job INSERT, never a direct recompute; **two-client frontend** — `supabase-js` direct reads for continuously-rendered table data, a typed `apiClient` (codegen via `openapi-typescript`, committed output) for every mutation plus the one polled read (`GET /v1/hunts/{id}/jobs`).

| # | Task | DESIGN refs | Done when |
|---|---|---|---|
| P1-1 | Migration `0002_hunt_and_pipeline_tables.sql`: 4 new enums (`hunt_role`, `job_type`, `job_state`, `value_state`), every §8.2 per-hunt/pipeline table verbatim, indexes (latest-extraction, jobs claim/heartbeat, job_events), `extractions.hunt_id` FK now that `hunts` exists, hunt-scoped custom-criterion extraction index. No RLS statements (deliberate — P2-1). **Dev-seed as `scripts/dev_seed.py`** (Python, not hand SQL): calls `run_job` against 3 committed synthetic fixture pages (`fixtures/pages/` — the scraped corpus is a gitignored local asset, DESIGN §20 v2.8, so seed inputs must be repo content) in `MANZIL_LLM_MODE=replay`, so it both seeds data and smoke-tests the ingest path writes to Postgres correctly ahead of P1-2's persistence swap | §8.1–8.2 | `supabase db reset && uv run --package worker python scripts/dev_seed.py` leaves 1 hunt / 3 listings / non-zero scores, asserted by a small `asyncpg` pytest |
| P1-2 | Queue mechanics in `worker/src/manzil_worker/queue.py`: `claim_next_job` (`FOR UPDATE SKIP LOCKED`), `heartbeat`, `reclaim_orphans` (runs every loop tick, not just startup), `run_worker_loop` (dispatches `RunState` shape by `job_type`; clean-shutdown drain via `stop: asyncio.Event`). New `worker/src/manzil_worker/postgres_persistence.py` implementing the same `Persistence` protocol as `FilePersistence`, parametrized-fixture tested for interchangeability with it | §8.2, §10.1 | kill -9 mid-job (mocked task cancellation) → a second `run_worker_loop` resumes it from `current_stage` within `JOB_ORPHAN_AFTER` |
| P1-3 | Worker loop as FastAPI `lifespan` task, gated by new `MANZIL_WORKER_INPROCESS` (default `true`; `false` from P3-1 with no code change) — `api/pyproject.toml` gains `manzil-worker` as a workspace dependency, the first api→worker edge | §5 | jobs process while API serves; clean-shutdown drain (stop claiming, finish in-flight) loses no work |
| P1-4 | API skeleton (`api/src/manzil_api/`): **API layout** above; `get_current_user` (JWT via `supabase-py`'s `auth.get_user`) + `get_user_client` (request-scoped, user-token `supabase-py` client — what makes P2's RLS flip schema-only, not an API rewrite) dependencies; `ErrorResponse{detail, code}` + `ManzilAPIError` base + global exception handler; OpenAPI docs hidden outside `local`/`staging`; health route | §5.1, §2 here | authed request round-trips; RLS sees the real JWT (even though RLS enforcement itself is off until P2-1) |
| P1-5 | Hunts CRUD + rubric GET/PUT (validate options vs `value_schema` via `jsonschema`, bump version, enqueue hunt-level rescore) + hunt-settings PATCH (validate vs §8.2 contract; scoring-affecting keys reuse the bump-and-rescore path; every key defaulted). Auth per **ownership stand-in** above | §5.1, §8.2, §9.2 | invalid option/setting rejected with field-level error; rescore job lands; `min_confidence` flip rescores seeded listings |
| P1-6 | Rescore job type: new `worker/src/manzil_worker/stages/rescore.py` + a minimal rescore state (RunState sibling — interface stays proposal per §3's graduation rule). Per listing: resolve effective values (latest extraction — global for catalog keys, hunt-scoped for custom keys — confidence-thresholded by `min_confidence`, then overridden by the latest `overrides` row per §9.6), score each floor plan via `shared.scoring.engine.score`, upsert `scores` (unique on `hunt_listing_id, floor_plan_id`) | §9.3–9.4 | rubric edit re-scores 3 seeded listings; breakdowns match goldens |
| P1-7 | Listings + jobs endpoints: `POST /v1/hunts/{id}/listings` (URL + optional `source_policy`, defaulted from hunt settings) → listing + ingest job (Phase 1 always creates a fresh property — dedupe-by-property is a P3 concern); `GET`/`DELETE` listings; jobs router — `GET .../jobs?state=`, cancel (queued/running/waiting_user only), retry (failed/cancelled only), checkpoint answer | §5.1, §10.7 | CLI path and API path produce identical job rows; policy persisted on the listing (inert until DISCOVER exists in P3-5) |
| P1-8 | Overrides + fee-checklist endpoints, both following **rescore-on-mutation** above (append-only overrides with attribution; fee upsert unique on `(hunt_listing_id, fee_slot)`) | §9.5–9.6 | override displays over extraction; original retrievable |
| P1-9 | Frontend shell: Mantine app frame, `supabase-js` magic-link auth (Phase 1 is one user — no password-reset flow needed), routes subset (`/`, `/h/:huntId`, `/rubric`, `/tasks`, `/settings`, `/login` — **not** `/compare` or `/invite/:token`, those are Phase 2/3), hunt switcher, Query client, `openapi-typescript` codegen wired (`npm run gen:api-types` against local `/openapi.json`) | §13.1 | login → create hunt → land on empty Overview |
| P1-10 | Overview table: unit-group rows (direct-Supabase-read hooks — no RLS live yet, an accepted Phase 1 gap closed by P2-1's backfill), score cell (color scale, multi-score indicator, stale/auto-resolved/single-source badge slots rendered inert — their Phase 3 triggering logic doesn't exist yet, don't fake data), range columns, `hide score < N` filter | §9.4, §13.2 | seeded multi-plan property renders one row per group with indicator |
| P1-11 | Detail panel Drawer: criterion breakdown renders persisted `scores.breakdown` directly (no client-side re-derivation) + evidence quotes, override control (POST then invalidate `scores`/`overrides` query keys — brief staleness until the ~3s poll is accepted in Phase 1), fee checklist, floor plans + per-group pin via new mini-endpoint `PATCH /v1/listings/{id}/pins` (folded into `listings/router.py` — pins aren't in DESIGN §5.1's route table; this is the Phase 1 resolution, not a design conflict), sources + fetched-at + the listing's Source Policy (read-only display; the "relax it here" refresh-triggering edit needs DISCOVER, so it's Phase 3) | §13.2 | pin switches group score; override badge + provenance visible |
| P1-12 | Rubric builder: Stepper wizard, widgets generated from `value_schema` (`{integer,min,max}`→NumberWidget, `{boolean}`→BoolWidget, `{string,enum}`→EnumWidget — the same schema the API validates options against), gate toggles + set-score, unknown-delta row, bonus derivation (`is_bonus` display-only, all deltas ≥ 0) | §9.2, §13.2 | wizard output passes the same validation as the API path |
| P1-13 | Tasks Active tab — **polling via Query `refetchInterval: 3000` against `GET /v1/hunts/{id}/jobs?state=queued,running,waiting_user`, the Phase 1 interim; swapped to Realtime in P2-4, which also deletes this polling** | §13.2 | stage progress visible; cancel works |
| P1-14 | **`confirm_value` checkpoint:** VERIFY raises `CheckpointRaised` when a gate-relevant criterion's extraction was demoted below the hunt's `min_confidence`; §10.10 prompt persisted via runner; resume applies answer before SCORE (`"yes"` upgrades confidence to at least `min_confidence`); Tasks tab + `POST /jobs/{id}/checkpoint` complete the round-trip | §10.5, §10.10, §9.3 | ingest fixture that VERIFY demotes on a gated criterion parks at `waiting_user`; answer via API → job reaches `done`; score reflects confirmed value |
| P1-15 | Exit review: Yusuf's real hunt created through the UI, spreadsheet listings ingested via the API, rubric built through the wizard, scores match hand-checked expectations; `kill -9` on the API mid-job resumes within `JOB_ORPHAN_AFTER` on restart (manual verification); retire the spreadsheet; revise Phase 2 table | §19 | a week of real use without opening Excel |

### Phase 2 — collaboration

| # | Task | DESIGN refs | Done when |
|---|---|---|---|
| P2-1 | RLS policies for every per-hunt table per the permissions matrix; global tables client-read-only; **backfill `hunt_members` owner rows for pre-RLS hunts in the same migration** (the Phase 1 user has hunts but no membership row — flipping RLS without the backfill locks them out of their own data) | §4.2, §8.3 | policies deployed; Phase 1 hunts still fully accessible; privileged surface still only `privileged.py` |
| P2-2 | Permission integration tests: every forbidden (role, action) pair attempted against real RLS | §4.2, §6 (DESIGN) | full matrix red/green; this is the phase exit gate |
| P2-3 | Invites: create (email via Supabase Auth invite, or copy-link token), accept endpoint, role granting, expiry/revocation | §9.1 | second account joins via both paths; curator grant works |
| P2-4 | Realtime: per-hunt channels on the §13.3 tables → Query invalidation; delete P1-13 polling | §13.3 | two browsers see a score change < 2 s apart; no polling remains |
| P2-5 | Comments (soft-delete), per-user ratings, color assignment + settings UI | §8.2, §13 | rating dots render in member colors |
| P2-6 | Tasks History tab: run list w/ filters, expanded `Timeline` from job_events, checkpoint Q&A incl. auto-resolutions, per-run cost | FR10, §13.2 | a Phase 0-era job renders fully from its events |
| P2-7 | Member management: roles, removal, owner transfer, danger zone; hunt-settings panel (Owner-edited, member-viewable — §8.2 keys with plain-language labels) | §4.2, §8.2, §9.1 | owner transfer leaves exactly one owner (constraint-tested); settings edit round-trips through the P1-5 PATCH |
| P2-8 | Curator end-to-end: overrides/fees/checkpoints on others' listings allowed; job management on others' denied | §4.2 | verified by P2-2 suite + manual pass |
| P2-9 | Exit: partner active in the real hunt; revise Phase 3 table | §19 | both members using it in anger |

### Phase 3 — full agent system

| # | Task | DESIGN refs | Done when |
|---|---|---|---|
| P3-1 | Worker split to separate paid Render service; Playwright in image; in-process loop removed | §5 | API memory flat while a browser job runs |
| P3-2 | Planner v1, **scoped to ingest manifests** (cache/TTL-aware refresh planning completes in P3-12, which builds the inputs it reads) | §10.4 | ingest of a known property plans skip-refetch correctly |
| P3-3 | Maps tools + forever-cache: geocode, Places, Routes (pulled ahead of its consumers — DEDUPE and ENRICH both read geocode) | §10.9, §12 | cached second geocode is $0 and instant |
| P3-4 | DEDUPE full: geocode + name similarity, gray-zone `resolve_dedupe` checkpoint, `split_property` admin op | §8.2, §10.3 | seeded near-duplicate pair → checkpoint; split restores cleanly |
| P3-5 | DISCOVER: provider web-search tool, same-property judgment, official-site preference; source cap logic ("third only on disagreement"); Source Policy enforcement — skip stage under `trust_link`, plan-time tier caps on siblings (`skip: policy_tier_cap`), `tier_1_plus_official` carve-out; policy `Select` on the submit control + single-source badge | §10.2 P3, §10.3, §10.7, §15 | finds official site for ≥70% of bench complexes; `trust_link` run produces zero DISCOVER events; over-cap sibling recorded as skipped in the manifest |
| P3-6 | Multi-source fan-out: FETCH per source, EXTRACT/VERIFY per source, RECONCILE ladder + `resolution_rule` + `disputed` handling | §10.6 | conflicting fixture pair resolves per ladder; rule recorded |
| P3-7 | Images: download, WebP, ≤10 cap → VISION with versioned reference set; skip-on-unchanged-hashes | §10.8, §14 | two runs, no image change → zero vision spend |
| P3-8 | ENRICH remainder: grocery + commute criteria live (honoring `settings.proximity_mode`; edit → field-scoped location refresh); reviews summary + safety synthesis (low-confidence framing) | §8.2, §10.3, §10.9, R8 | safety renders with confidence labeling, not as fact; proximity-mode flip re-enriches without LLM spend |
| P3-9 | Utility baselines job + all-in composition (conservative default via `settings.cost_estimate_mode`, tagged components, "fees unverified" badge) | §8.2, §9.5 | winter-weighted estimate visible and overrideable; mode flip to median rescores without refetch |
| P3-10 | Custom criteria: authoring flow w/ routing classification + confirm, CUSTOM_MATCH dispatch | §9.2, §10.9 | commute-to-address criterion authored → scored end-to-end |
| P3-11 | Checkpoints complete: `waiting_user` UI w/ screenshot, 24 h sweep via scheduler tick, auto-resolve badge + reopen/re-score | §10.10, §5 | ignored checkpoint auto-resolves at 24 h; late answer re-scores |
| P3-12 | Refresh: TTL classes, content-hash gating, field-scoped partial refresh, batch-API routing; **planner refresh-mode completes here** | §14, §11.3, §10.4 | unchanged-page refresh costs a fetch + hash compare only |
| P3-13 | Compare view + mobile bottom-sheet polish | §13 | 3-listing compare usable on a phone |
| P3-14 ⚠ | Tier-3 adapters — **only if the Phase 0 census gate opened**, scoped to the specific hostile domains it named | §10.7, §19 | census-named domains fetch successfully, or task deleted |

Learning track L1–L4 interleaves per DESIGN §19 gating; L-tasks get their own table here when L1 unlocks (after Phase 0 exit), not before.

---

## 8. Runbooks

*Status: settled.*

**Add a catalog criterion:** edit `shared/catalog.py` → regenerate `supabase/seed.sql` → `supabase db reset` → extraction schema picks it up automatically → add golden covering it → if gate-eligible, add a bench label field.

**Modify an existing criterion:** *widening* (new enum value, relaxed bound) — edit `catalog.py`, regenerate (+ `catalog_sync` migration post-Phase 1), update the golden; history and rubrics stay valid. *Narrowing* (removed value, tightened bound) — (1) impact-query nonconforming extractions and affected rubric options first; (2) define the value mapping; (3) one migration: upsert schema → **append** superseding extraction rows with the mapped values (`resolution_rule='schema_migration'`; never rewrite append-only history) → rewrite affected rubric options → bump touched hunts' `rubric_version` → enqueue their rescores; (4) re-run the bench (schema changes are output-affecting); (5) DESIGN §20 entry, mandatory. *Type changes* — never in place: retire the old key (disable in rubrics, keep history), add a new key. Post-Phase 1 deploy order for any of these: `supabase db push` **before** rolling services — old-worker/new-DB skew is benign, the reverse is not.

**Change a prompt or model:** bump `version` in the prompt front-matter (or model pin in `llm/config.py` — OpenRouter slugs like `anthropic/claude-haiku-4.5`) → run the bench in replay-invalidating mode (`record` against bench set) → compare report to previous → commit prompt + report together (recordings stay local — they're keyed to the gitignored corpus, DESIGN §20 v2.8). No eyeball-only prompt merges (DESIGN §6).

**Record new fixtures:** save page HTML into a new corpus dir → run cleaner → `MANZIL_LLM_MODE=record uv run --package worker pytest -k <slug>`.

**Back up the eval kit (after every labeling/saving session):** the corpus + labels are gitignored (DESIGN §20 v2.8) and unrecoverable if lost — delisted pages 404 and hostile pages need a working tier 3. One command, output goes anywhere private (external drive, private bucket — never this repo):
```bash
tar czf ~/manzil-eval-kit-$(date +%Y%m%d).tgz -C worker/tests/fixtures corpus bench/labels
```

**Manually requeue an orphaned job:** `update jobs set state='queued', locked_by=null, locked_at=null where id=… and state='running';` — safe at any stage boundary by construction.

**Apply migrations to hosted Supabase (Phase 1+):** `supabase link` once, `supabase db push`; never edit applied migrations, always add.

**Catalog changes on hosted DB:** `supabase/seed.sql` is local-reset-only. When `shared/catalog.py` changes after Phase 1, the generator also emits an idempotent upsert migration (`NNNN_catalog_sync.sql`) — catalog rows reach production the same way schema does, and drift between code seed and hosted rows is structurally impossible.

**Deploy (Phase 1+):** frontend — CF Pages auto-builds from `main` (`pnpm build`, output `frontend/dist`). API/worker — Render blueprint in `infra/render.yaml`, deploy-on-push from `main`; env vars set in Render dashboard, never committed. Worker deploys are safe mid-job by construction (orphan reclaim resumes at `current_stage`); still, prefer deploying when the Tasks view is idle.

---

## 9. Changelog

Ascending chronological (matching DESIGN §20's convention); same-day entries ordered by version.

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-07-03 | Created at Phase 0 kickoff: environment, conventions, interface proposals, prompt/fixture/observability mechanics, Phase 0 work plan (14 tasks), runbooks. |
| 1.1 | 2026-07-03 | Phases 1–3 broken into task tables (14/9/14) with ⚠ marks on outcome-dependent items; "expand on entry" → "revise on entry". Critique fixes: DB-access strategy (asyncpg worker / supabase-py API / `privileged.py` exception), CI + branching defined, Langfuse removed from API env, record/replay hash keying specified, `manzil` script entry noted, catalog-sync migration + deploy runbooks added, frontend test convention added, P1-13 polling interim made explicit. |
| 1.2 | 2026-07-03 | Status taxonomy (settled / proposal / interim-conditional) with per-section labels; §3 records interfaces reviewed and deliberately left as proposals with graduation at end of Phase 0; tunables split — home settled, values are starting points. |
| 2.0 | 2026-07-03 | **Implementation-start baseline.** Phase-process critique: sequencing rules added (row order = default dependency order; 🧍 = human-only, start immediately); VALIDATE stage given an owner (P0-8); bench labeling marked parallel (P0-11); dev-seed script added (P1-1); RLS owner-membership backfill added (P2-1 — the lockout trap); Phase 3 reordered so geocode precedes its consumers (maps → DEDUPE → DISCOVER) and planner honestly split into ingest-scope (P3-2) + refresh-scope (P3-12). Changelog reordered ascending. |
| 2.0.1 | 2026-07-04 | P0-2 catalog count 15 → 19, tracking DESIGN v2.0's seed-set additions (parking, cooling, dishwasher, min_lease_months). |
| 2.0.2 | 2026-07-05 | P0-5/P0-6 landed: three classifier/fetch tunables added (`CLEANED_TEXT_MIN_CHARS` 800, `SHELL_SCRIPT_RATIO` 0.7, `TIER2_MIN_DELAY_SECONDS` 3.0). CLI grew corpus/census tooling: `manzil save-page` (fetch via ladder → corpus fixture), `manzil clean-corpus` (cleaner-change runbook), `manzil census` (emits `docs/hostile-domain-census.csv` from `infra/census_urls.txt`). First census run recorded: rent.com/apartmentguide/apartmentlist tier-1 ok; zumper/padmapper/hotpads need tier 2; apartments.com/zillow/realtor/trulia/forrent hostile at tier 2 — feeds the P0-14 gate. |
| 2.0.3 | 2026-07-06 | Tracking DESIGN v2.2 (Source Policy): `source_policy` field added to the RunState proposal; P1-7 accepts + persists the policy (inert until DISCOVER exists); P3-5 owns enforcement (skip under `trust_link`, plan-time tier caps, `tier_1_plus_official` carve-out) plus the submit-control `Select` and single-source badge. |
| 2.0.4 | 2026-07-06 | Tracking DESIGN v2.3 (hunt settings contract): P1-5 grows the settings PATCH (contract validation, scoring-affecting keys reuse bump-and-rescore); P2-7 grows the hunt-settings panel; P3-8 honors `proximity_mode` (edit → field-scoped location refresh); P3-9 reads `cost_estimate_mode`. |
| 2.0.5 | 2026-07-06 | P0-7 landed. Seam mechanics settled in code: recorded fixtures named `{stage}--{hash16}.json`; replay mode is untraced by design (a replay is not a model call; CI has no keys) while live/record hard-fail without Langfuse keys (NFR6); `call_agent`/`call_vision` keep their pinned §3 signatures but raise until their first consumers (P3-5/P3-7). CLI grew `manzil llm-smoke` (one traced structured call; in `record` mode it refreshes the committed replay fixture). Trace/job identity and the cost tally travel as context vars (`run_context`, `cost_tally`) since the pinned §11.1 signatures carry no trace argument — the P0-10 runner sets both around each stage. |
| 2.0.6 | 2026-07-06 | P0-8/9/10 landed — the pipeline spine. Semantics settled in code (proposal status, per §3's graduation rule): Phase 0 stage order is FETCH → VALIDATE → EXTRACT → VERIFY → SCORE, since content-based VALIDATE needs the primary fetch first (⚠ flagged against DESIGN §10.1's diagram order — ruled in 2.0.7 / DESIGN v2.4); the extraction schema includes only page-text criteria (tool/vision/composed keys excluded); VERIFY demotions keep the value and record a `VerifyFlag` — known values score regardless of confidence (superseded by 2.0.8: values now confidence-thresholded per the v2.3 `min_confidence` contract), and gate-relevant checkpoint escalation is deferred to Phase 1 (needs jobs/`waiting_user`); `all_in_monthly` interim composition = conservative advertised rent (rent_max) until P3-9; RunState grew `status`/`error`/`verify_flags`/`scores` and uses float `cost_usd`; Phase 0 persistence is atomic JSON run files under `.manzil/runs/` behind the same Persistence protocol P1-2's jobs row will implement. Three plausibility tunables added (see §3 table). CLI `manzil ingest <url>` is live against the hardcoded §19 rubric (`phase0_rubric.py`, rubric version 0). |
| 2.0.7 | 2026-07-06 | Tracking DESIGN v2.4 (VALIDATE split): new **VALIDATE_URL** stage (`stages/validate_url.py`) heads the spine — deterministic P2, zero LLM: http(s) scheme, public host (private/loopback refused, SSRF guard), not a binary extension; strips whitespace/fragments and writes the normalized URL back to RunState so the ladder and adapter registry see one canonical form. Spine order now VALIDATE_URL → FETCH → VALIDATE → EXTRACT → VERIFY → SCORE; the 2.0.6 ⚠ is closed. |
| 2.0.8 | 2026-07-06 | **Correction to 2.0.6** aligning SCORE with the DESIGN v2.3 hunt-settings contract: effective values are confidence-thresholded — a value below `min_confidence` (Phase 0: the contract default `medium`, injected via `StageCtx.min_confidence`; hunts own the setting from P1-5) scores as **unknown**, so a VERIFY-demoted value on a gate-bearing criterion fires the gate instead of passing suspect data. The value itself stays on `reconciled`/extractions as provenance; a Phase 1 `confirm_value` answer is the path back up. Floor-plan figures carry no confidence dimension yet and are not thresholded. Test-pinned both ways (`medium` gates a demoted value; `low` admits it). |
| 2.0.9 | 2026-07-06 | Seam goes multi-provider (the §11.2 bench prerequisite — adoption as a default pin still requires bench evidence + DESIGN §20 at P0-14): `_live_call` dispatches by model-ID prefix (`claude-*` → Anthropic forced-tool adapter, `gemini-*` → new Google adapter using `response_schema` structured output; thinking disabled on 2.5 Flash family; usage normalized to uncached-input convention). Cache economics are per-provider (Anthropic 10%/125%, Gemini implicit 25%/none); the two §11.2 Gemini candidates are priced in `MODEL_PRICES`. New `MANZIL_MODEL_<STAGE>` env override (refused unless priced). Langfuse pinned `>=4` and the removed v3 `update_current_trace` replaced with `propagate_attributes` (trace name + session). Deps: `google-genai` added, `python-dotenv` declared (was riding transitively). Docs: `uv sync` → `uv sync --all-packages` (plain sync uninstalls workspace-member deps). |
| 2.0.10 | 2026-07-07 | Code halves of P0-11/12/13 landed ahead of the human labels. **Label format settled** (owned by `evals/labels.py`): `labels/{slug}.json` = `criteria` (key → true value, validated against catalog `value_schema` via `schema_gen.value_adapter`), `unknown` (page genuinely doesn't state it — model graded correct only on null), optional `floor_plans` (omit = plans ungraded); keys absent from both maps are not graded; loader hard-fails on nulls/unknown keys/out-of-schema values. `manzil bench-skeleton <slug>` scaffolds from a corpus page. Harness (P0-12): EXTRACT → VERIFY over saved corpus text, graded per label; report carries per-listing job_id (= Langfuse session) plus tally-based tokens/cost/latency; per-listing failures never abort the run. `manzil bench-run` writes `worker/evals/reports/{name}.json`; `manzil bench-compare` renders the §11.2 decision table (P0-13) — it never edits pins. Gate accuracy = accuracy over rubric non-negotiable keys; `all_in_monthly` is graded through plan rent fields (composed, §9.5). Still human-blocked: the 20 labels (P0-11 🧍), record-mode bench runs (needs provider key), the P0-13/14 decisions. |
| 2.0.11 | 2026-07-07 | **Tier 3 landed free-plan-only per DESIGN v2.5** (§20 2026-07-07): `fetching/tier3.py` — provider seam (`MANZIL_TIER3_PROVIDER`: `brightdata` default via Web Unlocker API, `scrapingbee` alternate; adding one = a `_Provider` entry), off the ladder until the selected provider's key env is set. `MAX_TIER` 2→3; ladder start-tier now clamps to available fetchers (registry may demand 3 in a run without a tier-3 key) and escalation skips missing rungs (`{1,3}` under `--no-tier2`). Census: `tier3_outcome` column; verdicts `tier3_ok` / `hostile_unfetchable` (blocked even at 3) / `hostile_needs_tier3` (kept when tier 3 absent). CLI: `--no-tier3` on ingest/save-page/census. New tunable `TIER3_TIMEOUT_SECONDS` 90. **Stopgap**: `fetching/slug_hint.py` — deterministic URL-slug identity; FETCH's `source unfetchable` error now suggests the sibling-source search (manual DISCOVER stand-in until P3-5). |
| 2.0.12 | 2026-07-07 | **Phase 1 started in parallel with Phase 0's tail** (P0-11..14 — bench labeling, harness/model-bench runs, census + model-pin decisions — block nothing here; AGENTS.md §Current phase updated to describe both). Phase 1 table (§7) revised on entry per `.claude/plans/phase-1-frontend-api.md`: API structure adapted from fastapi-best-practices (domain-oriented layout + chain-of-dependencies, no ORM — stays inside the settled §2 DB-access rule); ownership stand-in (`current_user.id == hunt.owner_id`) shaped so P2's role matrix swaps only a dependency body; rescore-on-mutation made uniform across rubric/settings/overrides/fees (one job INSERT, never a direct recompute); two-client frontend data layer (direct Supabase reads + typed `apiClient` via `openapi-typescript` codegen, committed output); dev-seed specified as a Python script calling `run_job` in replay mode rather than hand SQL; queue mechanics given concrete function signatures; `FloorPlanPinControl` resolved as a new `PATCH /v1/listings/{id}/pins` mini-endpoint (not in DESIGN §5.1's route table — a Phase 1 fill-in, no design conflict). §1 env vars gained `MANZIL_WORKER_INPROCESS`, `API_CORS_ORIGINS`, `API_ENVIRONMENT`, `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY`/`VITE_API_BASE_URL`; `SUPABASE_SERVICE_ROLE_KEY` gains the api's in-process worker loop as a second legitimate holder. |
| 2.0.13 | 2026-07-07 | **Embedded structured-data miner per DESIGN v2.6** (§20 2026-07-07): `fetching/structured.py` mines JSON-LD + framework state blobs (`__NEXT_DATA__`, `window.__PRELOADED_STATE__ = {…}` assignments via `raw_decode`, bare-JSON state scripts) into a pruned digest the cleaner appends under `[EMBEDDED DATA]`; drop-before-keep pruning (`similar`/`nearby` = wrong-property contamination, dropped first), media/URL scrub, cap `EMBEDDED_DATA_MAX_CHARS` 40k (+ `EMBEDDED_SCRIPT_MIN_CHARS` 500 candidate floor). `CleanedPage.embedded_blobs` added. Classifier: positive cleaned-text check moved **above** the JS-shell signature and `has_listing_signal` now matches rental-fact JSON keys (`"priceLow":` …) — empty-DOM data-shipping pages settle at tier 1. JS object literals stay unminable by design (no JS evaluation). `save_page` tolerates an already-domain-prefixed slug (no more `domain--domain--slug` dirs). Corpus regenerated (16 pages: cleaned text now 16–45 KB, unit-level rents/sqft/availability present at tier 1); runbook unchanged: rerun `manzil clean-corpus` after miner list changes. |
| 2.0.14 | 2026-07-07 | **OpenRouter as sole LLM gateway per DESIGN v2.7** (§20 2026-07-07): direct `anthropic` and `google-genai` SDKs dropped; one `_live_call_openrouter` adapter via `openai` SDK → `https://openrouter.ai/api/v1`. Model pins are OpenRouter slugs (`anthropic/claude-haiku-4.5`, `anthropic/claude-sonnet-4.6`, bench candidates `google/gemini-2.5-flash-lite` / `google/gemini-2.5-flash`). Forced-tool structured output + `cache_control` on stable prefixes; upstream provider pinning via `openrouter_provider_order` (`Anthropic` / `Google AI Studio`). Usage normalized from `prompt_tokens_details` (uncached input convention preserved). OpenRouter `usage.cost` logged to Langfuse as `openrouter_cost_usd` cross-check. Env: `OPENROUTER_API_KEY` replaces `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`. Smoke replay fixture re-keyed to new model slug. Deps: `openai` added, `anthropic` + `google-genai` removed. |
| 2.0.15 | 2026-07-07 | **Eval kit made a local asset per DESIGN v2.8** (§20 2026-07-07): `fixtures/corpus/` and `fixtures/bench/labels/` gitignored with tracked `.gitkeep` placeholders; `bench/manifest.md` + the smoke replay fixture stay tracked; other record-mode artifacts ignored (keyed to local corpus content). `corpus_pages()` returns `[]` when the dir is absent so a fresh clone collects cleanly (test pinned). P0-11 exit metric reworded committed → present locally + backed up; P1-1 dev-seed retargeted to committed synthetic `fixtures/pages/`; §8 gained the backup-the-eval-kit runbook (tar to somewhere private after every labeling session). Reviewed and reaffirmed, no change: the 2026-06-28 production cleaned-text retention line (facts in `extractions` + gzipped cleaned text in Storage) — orthogonal to the repo decision. |
| 2.0.16 | 2026-07-07 | **API + frontend scaffolding landed** (P1-4 skeleton + P1-9 shell), per `.claude/plans/phase-1-frontend-api.md`. **API** (`api/`): domain-oriented layout (`config`/`schemas`/`exceptions`/`database`/`dependencies`/`worker_loop`/`main` + `hunts`/`rubric`/`listings`/`jobs`/`overrides`/`fees` packages). App boots: lifespan (asyncpg pool + gated in-process worker task, import-defensive until P1-2's `queue.run_worker_loop` exists), CORS, `ManzilAPIError`→`ErrorResponse` global handler, docs gated to local/staging, `/v1/health`. All 14 §4.3 routes declared with `response_model` (so OpenAPI/codegen see the real surface) but handlers `raise NotImplementedYet` until P1-5..P1-8/P1-13; the chain-of-dependencies auth (`get_current_user`/`get_user_client`, `valid_hunt_id`→`require_owner` ownership stand-in, `valid_listing_id`) is wired. First api→worker workspace edge; deps `fastapi`/`uvicorn`/`pydantic-settings`/`supabase`/`jsonschema`/`asyncpg`. Tests: `httpx.AsyncClient`+`ASGITransport` health smoke (root dev group gains `pytest-asyncio`+`httpx`, `asyncio_mode=auto`). **Frontend** (`frontend/`): Vite+React-TS+Mantine, TanStack Query, react-router (auth-guarded `/`, `/h/:huntId{,/rubric,/tasks,/settings}`, `/login` — no `/compare`/`/invite`), two-client data layer (`supabase.ts` reads + `apiClient.ts` mutations), magic-link `AuthProvider`, `openapi-typescript` codegen wired (committed `src/lib/generated/api.d.ts`). Route pages are placeholders naming their P1 task; real logic shipped where pure + testable: `value_schema`→widget dispatcher (`selectWidget`) and `ScoreCell` color scale, each vitest-covered. CI gains a `frontend` job (pnpm lint+test+build); tooling: pnpm installed, esbuild allowlisted in `pnpm-workspace.yaml`. §1 env vars (`MANZIL_WORKER_INPROCESS`/`API_CORS_ORIGINS`/`API_ENVIRONMENT`/`VITE_*`) added to `infra/.env.example`. All checks green: ruff/mypy clean, 186 py tests + 7 vitest pass, frontend builds. |
| 2.0.17 | 2026-07-08 | **P1-1 landed:** migration `20260708000000_hunt_and_pipeline_tables.sql` (4 enums, all §8.2 per-hunt/pipeline tables, claim/heartbeat/job_events indexes, `extractions.hunt_id` FK, hunt-scoped extraction index; no RLS). `scripts/dev_seed.py` enqueues three ingest jobs against committed `fixtures/pages/` in replay mode; committed seed recordings in `fixtures/recorded/`. Tests: `test_migration_0002_schema`, `test_dev_seed`. |
| 2.0.18 | 2026-07-08 | **P1-2 landed:** `queue.py` (`claim_next_job`, `heartbeat`, `reclaim_orphans`, `run_worker_loop`, ingest dispatch + result projection), `postgres_persistence.py` (`Persistence` protocol over `jobs` row + `job_events`). Tests: interchange, orphan reclaim, atomic projection. Ingest results commit atomically with the DONE flip via `PostgresPersistence.on_done`. Property-level-only scores (no scorable floor plan) fail loud — §8.2 `scores.floor_plan_id NOT NULL` leaves nowhere to write them, so the worker raises `StageFatal` rather than silently dropping. |
| 2.0.19 | 2026-07-08 | **P1-3 landed:** API lifespan starts `run_worker_loop` when `MANZIL_WORKER_INPROCESS=true` (default); clean-shutdown drain via `stop` Event. `worker_loop.py` passes `settings.database_url` into `build_dispatch` so the per-domain adapter registry uses Postgres even when `DATABASE_URL` comes from the `.env` file (pydantic-settings does not populate `os.environ`). `api/pyproject.toml` workspace-depends on `manzil-worker`. Test: `test_worker_inprocess`. |
| 2.0.20 | 2026-07-09 | **P1-5..P1-8 + P1-6 landed:** all 16 §4.3 handlers implemented (hunts CRUD/settings, rubric GET/PUT with jsonschema validation, listings + ingest jobs, jobs list/cancel/retry/checkpoint, overrides, fees). **Rescore-on-mutation** uniform: rubric/settings/overrides/fees enqueue one hunt-level `rescore` job; `stages/rescore.py` resolves effective values and upserts scores. Contract fixes: `RubricOption` imports shared §8.2 shape; `JobResponse.checkpoint` populated from parked `run_state`. API router integration tests + `test_e2e_flow`. |
| 2.0.21 | 2026-07-09 | **P1-14 landed:** VERIFY raises `confirm_value` checkpoint on gate-relevant demotions below `min_confidence`; resume path upgrades confidence on `"yes"`; `confirm_value_resolved` prevents re-raise after answer. Phase 1 task table grows to 15 rows (exit review → P1-15). |
