# Phase 1 Implementation Plan — API + Frontend ("replace the spreadsheet")

Status: proposed plan, not yet executed. Written against DESIGN.md (read at commit
`d8a8235`) §5, §6, §7, §8, §13, §19 and IMPLEMENTATION.md §7's provisional Phase 1
table (P1-1..P1-15), which this plan revises per IMPLEMENTATION.md's own "entering a
phase means revising its table first" rule. FastAPI structural conventions follow
https://github.com/zhanymkanov/fastapi-best-practices, adapted at the one point where
it conflicts with a settled Manzil decision (DB access — see §2.1 below).

## 0. Scope

**In scope (DESIGN §19 Phase 1):** API + durable Postgres queue + worker loop
(in-process, per §5 budget option); Overview table; detail panel; rubric builder;
overrides; fees checklist; Tasks Active tab; Supabase Auth for one user.
**Exit:** Yusuf's real hunt runs here, spreadsheet retired.

**Explicitly out of scope** (later phases — do not build, per AGENTS.md hard rule on
§18/phase discipline):
- RLS policies, permissions matrix, Curator role enforcement (Phase 2, P2-1/P2-2)
- Invites, comments, ratings, member colors (Phase 2)
- Realtime subscriptions on `jobs`/`job_events` (Phase 2, P2-4) — Phase 1 polls
- Tasks **History** tab (Phase 2, P2-6)
- DISCOVER/RECONCILE multi-source, VISION, Maps/reviews ENRICH, utility baselines,
  custom criteria, checkpoint UI, refresh/TTL machinery, Compare view, separate paid
  worker, mobile sheet polish (Phase 3)
- `all_in_monthly` stays the Phase 0 interim composition (advertised `rent_max`) —
  real composition is P3-9

This plan covers the API and frontend end-to-end, plus the minimum adjacent
worker/DB work those two need to function (migration 0002, queue mechanics, the
in-process worker loop, the rescore job). It does not redesign worker pipeline
internals beyond that.

---

## 1. Cross-cutting decisions

### 1.1 API structure: fastapi-best-practices adapted to the settled DB-access rule

IMPLEMENTATION.md §2 already settled DB access and it does **not** match
fastapi-best-practices' SQLAlchemy/Alembic default: *"The API performs user-context
mutations through `supabase-py` with the caller's access token, so PostgREST
evaluates RLS with the real JWT — the API never simulates permissions it can hand to
the database."* There is no SQLAlchemy, no Alembic, no ORM models in the API. What we
take from the best-practices guide instead:

- **Domain-oriented package layout** (`src/<domain>/{router,schemas,service,
  dependencies,exceptions}.py`) instead of layering by file type.
- **Chain-of-dependencies** pattern for resource validation + auth (`valid_hunt_id`
  → `require_owner` → route).
- **Pydantic `BaseSettings`**, split global vs. module-level.
- **Module-specific exception classes**, mapped to one error envelope by a global
  handler.
- **`response_model` + full endpoint metadata** (tags, summary, status codes) on
  every route.
- **Async test client** (`httpx.AsyncClient` + `ASGITransport`) with
  `dependency_overrides` for auth fakes.
- **Hide OpenAPI docs** outside local/staging.
- Ruff for lint/format (already the repo convention).

`service.py` in each module wraps `supabase-py` calls (PostgREST embedded-resource
selects for joins, e.g. `.select("*, floor_plans(*)")`) instead of SQLAlchemy query
building — this is the "SQL-first, let the database do the work" principle applied
through the tool this project actually uses for the API layer. The worker's `asyncpg`
+ raw SQL (already established in `fetching/registry.py`) is untouched and stays the
worker's own pattern for its service-role, non-JWT'd access — the two data-access
strategies belong to different processes.

### 1.2 Auth

Frontend authenticates via `supabase-js` (`supabase.auth.signInWithOtp` or
password — Phase 1 is one user, so magic-link email is enough; no need to build a
password-reset flow). Every API call carries `Authorization: Bearer <access_token>`
from the current Supabase session. The API's `get_current_user` dependency verifies
the JWT (via `supabase-py`'s `auth.get_user(token)` against the Supabase Auth server,
or local verification against the project JWT secret — plan uses `auth.get_user`
for Phase 1 simplicity; revisit for latency if it matters) and returns a
`UserContext(id, email)`. A second dependency, `get_user_client(token)`, builds a
request-scoped `supabase-py` `Client` authenticated with that token, so every
service-layer call already carries the caller's identity into PostgREST — this is
what makes turning on RLS in Phase 2 a schema-only change, not an API rewrite.

### 1.3 Ownership/permission stand-in for Phase 1

DESIGN §4.2's full role matrix (Owner/Curator/Member) is Phase 2 (RLS + P2-2 tests).
Phase 1 has exactly one user, but `hunt_members` is created now (migration 0002,
since Phase 2 needs it and retrofitting is worse than seeding it correctly) with the
dev-seed inserting one `owner` row per hunt. Route-level dependencies check
`current_user.id == hunt.owner_id` (equivalent to "Owner" for every action, since
there's only one role in play) rather than hand-rolling a partial permissions
system — this keeps the P1 dependency signatures identical to what Phase 2's real
matrix will slot into (`valid_hunt_id` → `require_role(min=...)`), so P2-1/P2-2 change
the dependency body, not every router.

### 1.4 Error envelope

```python
class ErrorResponse(BaseModel):
    detail: str
    code: str  # machine-readable, e.g. "hunt_not_found", "invalid_rubric_option"
```

Global handler in `main.py` catches `ManzilAPIError` (new base in
`src/manzil_api/exceptions.py`) and Pydantic `ValidationError`, returns this shape
with the right status code. Module exceptions (`HuntNotFound`, `RubricOptionInvalid`,
`NotHuntOwner`, …) subclass it with a fixed `status_code` + `code`.

### 1.5 Worker loop wiring (P1-3, DESIGN §5 budget option)

New env var `MANZIL_WORKER_INPROCESS` (default `true` in Phase 1). API's `lifespan`
starts an asyncio task running `manzil_worker.queue.run_worker_loop(pool, ...)` when
true; Phase 3 (P3-1, separate Render worker service) flips it to `false` in that
deployment's env without touching code. This makes `manzil-api` depend on
`manzil-worker` for the first time — a new workspace edge, added only for this
lifespan wiring, matching DESIGN §5's explicit sanction of the in-process option.

### 1.6 Frontend data layer: two clients, on purpose

Per DESIGN §5.1 ("reads that the table renders continuously go straight from
frontend to Supabase; the API exists for validated mutations"):

- **`supabase-js`** (`lib/supabase.ts`): auth session, and **direct reads** of
  `hunts`, `hunt_listings`, `properties`, `floor_plans`, `extractions`,
  `rubric_criteria`, `scores`, `overrides`, `fee_checklist`, `criteria_catalog` —
  wrapped in TanStack Query hooks per feature module. No RLS is live yet (open
  tables, single user) — this is a known, accepted Phase 1 gap closed by P2-1's
  backfill migration, not a bug to fix now.
- **Typed API client** (`lib/apiClient.ts`): every **mutation** (create hunt, edit
  rubric, submit URL, cancel/retry job, answer checkpoint, create override, upsert
  fee entry) plus the one polled read DESIGN pins to the API surface: `GET
  /v1/hunts/{id}/jobs`. Generate request/response types from the API's OpenAPI
  schema via `openapi-typescript` (dev-only codegen, zero runtime dependency) so the
  two services can't silently drift — `npm run gen:api-types` fetches
  `http://localhost:8000/openapi.json` when the API is running locally.

Tasks Active tab (P1-13) polls `GET /v1/hunts/{id}/jobs?state=queued,running,
waiting_user` via TanStack Query `refetchInterval: 3000` — no Supabase Realtime in
Phase 1 (that's P2-4, which also deletes this polling).

### 1.7 Rescore-on-mutation, uniformly

Every scoring-input mutation (rubric PUT, hunt-settings PATCH on a scoring-affecting
key, override POST, fee-checklist POST/PATCH) ends its service function with one
`INSERT INTO jobs (type='rescore', payload={'hunt_id': ...})` — never a direct
score recompute in the API request. This mirrors the settled "API's job is one
INSERT; the worker does the rest" principle (DESIGN §5) and the v1.1 decision that
rescore is one hunt-level job. Rescore is $0 (no LLM calls, NFR1), so hunt-wide
fan-out on every override is cheap and keeps one code path instead of a targeted
"just this listing" special case.

---

## 2. Database: migration 0002 + dev-seed

### 2.1 New file: `supabase/migrations/<timestamp>_hunt_and_pipeline_tables.sql`

Follows migration 0001's style (plain SQL, DESIGN §-referencing comments, text+check
for vocab that must not require a migration to extend). New enums (the four not
created in 0001 — confidence/fetch_outcome already exist):

```sql
create type hunt_role as enum ('owner', 'curator', 'member');
create type job_type as enum ('ingest', 'refresh', 'rescore', 'investigate');
create type job_state as enum ('queued', 'running', 'waiting_user', 'done', 'failed', 'cancelled');
create type value_state as enum ('extracted', 'manual', 'estimated', 'unknown');
```

Tables (field lists are the DESIGN §8.2 pinned shapes, verbatim):

| Table | Key columns beyond FK/PK | Notes |
|---|---|---|
| `hunts` | `name, owner_id, domain text check (domain in ('rent','buy')) default 'rent', rubric_version int not null default 0, settings jsonb not null default '{}', archived_at` | settings validated app-side against the §8.2 contract, not by a DB check |
| `hunt_members` | `hunt_id, user_id, role hunt_role not null, color text` | PK `(hunt_id, user_id)` |
| `invites` | `hunt_id, email, token unique, role_granted hunt_role not null default 'member', created_by, expires_at, accepted_by` | table created now, **unused** until P2-3 |
| `hunt_listings` | `hunt_id, property_id, added_by, status text check (status in ('active','archived')) default 'active', source_policy text check (source_policy in ('trust_link','tier_1','tiers_1_2','tiers_1_2_3','tier_1_plus_official')) default 'tiers_1_2_3', pins jsonb not null default '{}', created_at` | index `hunt_listings_hunt_id_idx` |
| `rubric_criteria` | `hunt_id, catalog_key references criteria_catalog(key), custom_def jsonb, enabled bool not null default true, options jsonb not null default '[]', unknown_delta numeric not null default 0, non_negotiable jsonb, is_bonus bool not null default false, position int not null default 0` | `catalog_key` nullable (custom criteria) |
| `overrides` | `hunt_listing_id, criterion_key, value jsonb, user_id, note, created_at` | append-only, no update/delete path in the API |
| `fee_checklist` | `hunt_listing_id, fee_slot text, amount numeric(10,2), value_state value_state not null default 'unknown', entered_by, evidence_ref, updated_at` | unique `(hunt_listing_id, fee_slot)` — upsert target |
| `scores` | `hunt_listing_id, floor_plan_id references floor_plans(id), total numeric not null, breakdown jsonb not null, rubric_version int not null, computed_at timestamptz not null default now()` | unique `(hunt_listing_id, floor_plan_id)` — upsert target for rescore |
| `comments` | `hunt_listing_id, user_id, body, created_at, deleted_at` | table created now, **unused** until P2-5 |
| `ratings` | `hunt_listing_id, user_id, rating smallint` | table created now, **unused** until P2-5 |
| `jobs` | `hunt_listing_id, type job_type not null, state job_state not null default 'queued', current_stage text, plan jsonb, payload jsonb not null default '{}', attempts int not null default 0, error text, cost_actual_usd numeric(10,4) not null default 0, locked_by text, locked_at timestamptz, created_at timestamptz not null default now(), finished_at timestamptz` | the queue |
| `job_events` | `job_id, stage text, event text not null check (event in ('started','completed','failed','checkpoint_asked','checkpoint_answered','checkpoint_auto_resolved','escalated_tier')), detail jsonb not null default '{}', at timestamptz not null default now()` | `event` is text+check (not in the §8.1 enum list — matches the catalog-vocab pattern) |

Indexes beyond FK/PK:
```sql
create index hunt_listings_hunt_id_idx on hunt_listings (hunt_id);
create index rubric_criteria_hunt_id_idx on rubric_criteria (hunt_id);
create index overrides_listing_criterion_idx on overrides (hunt_listing_id, criterion_key, created_at desc);
create index fee_checklist_listing_idx on fee_checklist (hunt_listing_id);
create index scores_listing_idx on scores (hunt_listing_id);
create index jobs_hunt_listing_idx on jobs (hunt_listing_id);
create index jobs_claimable_idx on jobs (created_at) where state = 'queued';
create index jobs_running_heartbeat_idx on jobs (locked_at) where state = 'running';
create index job_events_job_id_idx on job_events (job_id, at);
-- extractions.hunt_id gets its FK now that hunts exists (per DESIGN v2.1 §20):
alter table extractions add constraint extractions_hunt_id_fkey
    foreign key (hunt_id) references hunts (id) on delete cascade;
-- the latest-row lookup for custom (hunt-scoped) criteria, complementing 0001's
-- global-criterion index:
create index extractions_hunt_criterion_idx
    on extractions (hunt_id, property_id, criterion_key, extracted_at desc)
    where hunt_id is not null;
```

No RLS statements in this migration — deliberate (§1.3 above); P2-1 adds `enable row
level security` + policies + the owner-membership backfill for every table here.

### 2.2 New file: `supabase/seed_dev.sql` (or a Python script `scripts/dev_seed.py`)

Per P1-1's "done when": a demo hunt with 3 listings sourced from Phase 0 corpus
extractions, so frontend tasks (P1-10..12) have real data on day one without an
API round-trip. Concretely:
- One `hunts` row (owner = the one dev user, created via `supabase auth` locally),
  the Phase 0 rubric (`worker/src/manzil_worker/phase0_rubric.py`) translated into
  `rubric_criteria` rows.
- 3 `properties` + their `property_sources`/`floor_plans`/`extractions` rows,
  copied from 3 already-ingested Phase 0 CLI runs (`.manzil/runs/*.json` or
  re-run `manzil ingest` against 3 corpus URLs with `DATABASE_URL` set so
  `PostgresRegistry`/future Postgres persistence lands them directly).
- 3 `hunt_listings` rows tying those properties to the demo hunt.
- One `jobs` row per listing already `state='done'` (so Tasks Active tab has
  nothing stale to show, and History — even though its UI is Phase 2 — has real
  rows from day one).

Prefer a small Python script (`scripts/dev_seed.py`, run via
`uv run --package worker python scripts/dev_seed.py`) over hand-written SQL: it can
literally call `run_job` against real corpus fixtures in `MANZIL_LLM_MODE=replay`,
which both seeds data and doubles as an end-to-end smoke test that the ingest path
still writes to Postgres correctly after P1-2's persistence swap (§3.2 below).

**Test:** `supabase db reset && uv run --package worker python scripts/dev_seed.py`
leaves 1 hunt / 3 listings / non-zero scores, asserted by a small pytest using
`asyncpg` against the local stack.

---

## 3. Worker: queue mechanics + rescore job (prerequisite for the API)

These are IMPLEMENTATION.md's P1-2/P1-3/P1-6, included here only to the depth the
API needs to build against a real contract — not a full worker redesign.

### 3.1 New file: `worker/src/manzil_worker/postgres_persistence.py`

Implements the same `Persistence` protocol as `FilePersistence`
(`worker/src/manzil_worker/persistence.py`), but `save(state)` writes to the `jobs`
row (by `state.job_id`): `state`, `current_stage` (from `state.cursor` and the stage
list), `payload` (whatever's not already a column — e.g. the checkpoint prompt when
parked), `cost_actual_usd`, `error`, `finished_at`. `load(job_id)` reads the row back
into a `RunState`. Existing stage code is untouched — it only knows about the
`Persistence` protocol, never the storage.

**Test:** round-trip a `RunState` through `PostgresPersistence` against the local
Supabase stack; assert `FilePersistence` and `PostgresPersistence` are
interchangeable for `run_job` (parametrized fixture).

### 3.2 New file: `worker/src/manzil_worker/queue.py`

```python
async def claim_next_job(pool: asyncpg.Pool, worker_id: str) -> JobRow | None: ...
async def heartbeat(pool: asyncpg.Pool, job_id: UUID, worker_id: str) -> None: ...
async def reclaim_orphans(pool: asyncpg.Pool) -> int: ...
async def run_worker_loop(pool: asyncpg.Pool, ctx_factory, poll_interval=2.0, stop: asyncio.Event) -> None: ...
```
`claim_next_job`: `SELECT ... FOR UPDATE SKIP LOCKED WHERE state='queued' ORDER BY
created_at LIMIT 1`, flips to `running`, sets `locked_by`/`locked_at`. Orphan reclaim
(`JOB_ORPHAN_AFTER_SECONDS` tunable, already in `shared/config.py`) resets
`locked_at is null and state back to queued` for `running` rows whose `locked_at` is
stale — runs once per loop tick, not just at startup. `run_worker_loop` claims →
builds `RunState` from the job row (dispatches on `job_type`: `ingest` builds the
Phase 0 `RunState` shape; `rescore` builds the minimal state `RESCORE_STAGES` needs)
→ `run_job(state, ctx, stages=...)` → loops until `stop.is_set()` (clean-shutdown
drain: stop claiming new jobs, let the in-flight one finish — safe by construction
since stages persist before advancing).

**Test:** `kill -9` equivalent — start a job, force-kill the loop mid-stage (mock
sleep to never return, cancel the task), assert a second `run_worker_loop` picks it
up from `current_stage` within `JOB_ORPHAN_AFTER_SECONDS`.

### 3.3 New file: `worker/src/manzil_worker/stages/rescore.py` + rescore stage list

A hunt-level rescore is not the ingest pipeline — it has no URL, no fetch. New
minimal state (or a `RescoreState` sibling to `RunState` — interface stays
"proposal" per IMPLEMENTATION §3, settle in code) carrying `hunt_id`, iterating that
hunt's active `hunt_listings`:
1. Load the hunt's `rubric_criteria` (enabled).
2. Per listing: resolve **effective values** — latest `extractions` row per
   criterion (global for catalog keys, `hunt_id`-scoped for custom keys),
   confidence-thresholded by the hunt's `settings.min_confidence`, then overridden by
   the latest `overrides` row for that `(hunt_listing_id, criterion_key)` if present
   (§9.6: override > extraction).
3. Per floor plan of the listing's property: call `shared.scoring.engine.score(...)`,
   upsert into `scores` (unique on `(hunt_listing_id, floor_plan_id)`).
4. Write `job_events` (`started`/`completed`).

**Test:** golden-style — seed a hunt_listing with a known extraction + an override
that should win, assert the persisted `scores.breakdown` matches
`shared/tests/golden` expectations for that input; assert a rubric edit's rescore
job updates all 3 dev-seed listings' scores.

### 3.4 Wiring change: `worker/pyproject.toml`

No change needed here (worker doesn't depend on api). `api/pyproject.toml` gains
`manzil-worker` as a workspace dependency (§1.5).

---

## 4. API (`api/`)

### 4.1 Directory tree

```
api/
├── pyproject.toml                 # + fastapi, uvicorn, supabase, jsonschema, python-jose (or PyJWT)
├── src/manzil_api/
│   ├── main.py                    # app factory, lifespan (worker loop + supabase admin client),
│   │                               #   CORS, exception handlers, docs hidden outside local/staging
│   ├── config.py                  # global Settings: SUPABASE_URL, SUPABASE_ANON_KEY,
│   │                               #   SUPABASE_SERVICE_ROLE_KEY (worker loop only), DATABASE_URL,
│   │                               #   ENVIRONMENT, CORS_ORIGINS, MANZIL_WORKER_INPROCESS
│   ├── database.py                # asyncpg pool (for the in-process worker loop) +
│   │                               #   supabase-py client factories (anon/service/user-token)
│   ├── dependencies.py            # get_current_user, get_user_client, get_db_pool
│   ├── exceptions.py               # ManzilAPIError base + global handler registration
│   ├── schemas.py                  # ErrorResponse; shared response envelope pieces
│   ├── worker_loop.py              # thin lifespan glue calling manzil_worker.queue.run_worker_loop
│   ├── hunts/
│   │   ├── router.py               # POST /v1/hunts, GET /v1/hunts, GET/PATCH /v1/hunts/{id}
│   │   ├── schemas.py              # HuntCreate, HuntUpdate, HuntSettingsPatch, HuntResponse
│   │   ├── service.py              # create/list/get/patch, settings-contract validation
│   │   ├── dependencies.py         # valid_hunt_id, require_owner (chains off get_current_user)
│   │   └── exceptions.py           # HuntNotFound, NotHuntOwner, InvalidHuntSettings
│   ├── rubric/
│   │   ├── router.py               # GET/PUT /v1/hunts/{id}/rubric
│   │   ├── schemas.py              # RubricCriterionIn/Out (mirrors manzil_shared.models shapes)
│   │   ├── service.py              # validate options vs catalog value_schema (jsonschema),
│   │   │                           #   write rows, bump hunts.rubric_version, enqueue rescore job
│   │   └── exceptions.py           # InvalidRubricOption
│   ├── listings/
│   │   ├── router.py               # POST /v1/hunts/{id}/listings, GET /v1/hunts/{id}/listings,
│   │   │                           #   DELETE /v1/listings/{id}
│   │   ├── schemas.py              # ListingCreate (url, source_policy?), ListingResponse
│   │   ├── service.py              # create hunt_listing (dedupe-by-property is a P3 concern —
│   │   │                           #   Phase 1 always creates a fresh property + ingest job),
│   │   │                           #   insert ingest job (type=ingest, payload={url, source_policy})
│   │   └── dependencies.py         # valid_listing_id
│   ├── jobs/
│   │   ├── router.py               # GET /v1/hunts/{id}/jobs?state=, POST /v1/jobs/{id}/cancel,
│   │   │                           #   POST /v1/jobs/{id}/retry, POST /v1/jobs/{id}/checkpoint
│   │   ├── schemas.py              # JobResponse, CheckpointAnswer
│   │   ├── service.py              # state-transition guards (cancel only queued/running/
│   │   │                           #   waiting_user; retry only failed/cancelled)
│   │   └── exceptions.py           # JobNotFound, JobNotCancellable, JobNotRetryable
│   ├── overrides/
│   │   ├── router.py               # POST /v1/listings/{id}/overrides
│   │   ├── schemas.py              # OverrideCreate
│   │   └── service.py              # insert override row, enqueue hunt rescore
│   └── fees/
│       ├── router.py               # PUT /v1/listings/{id}/fees/{fee_slot}
│       ├── schemas.py              # FeeEntryUpsert
│       └── service.py              # upsert fee_checklist row, enqueue hunt rescore
└── tests/
    ├── conftest.py                 # AsyncClient fixture, dependency_overrides for auth,
    │                               #   a fixture that resets the local Supabase stack per module
    ├── test_health.py
    ├── hunts/test_hunts_router.py
    ├── rubric/test_rubric_router.py
    ├── listings/test_listings_router.py
    ├── jobs/test_jobs_router.py
    ├── overrides/test_overrides_router.py
    └── fees/test_fees_router.py
```

### 4.2 `main.py` sketch

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await asyncpg.create_pool(settings.DATABASE_URL)
    app.state.db_pool = pool
    stop = asyncio.Event()
    task = None
    if settings.MANZIL_WORKER_INPROCESS:
        task = asyncio.create_task(run_worker_loop(pool, ctx_factory, stop=stop))
    yield
    stop.set()
    if task:
        await task
    await pool.close()

app_configs = {"title": "Manzil API", "version": "1.0"}
if settings.ENVIRONMENT not in ("local", "staging"):
    app_configs["openapi_url"] = None
app = FastAPI(**app_configs, lifespan=lifespan)
app.include_router(hunts.router, prefix="/v1")
app.include_router(rubric.router, prefix="/v1")   # nested path, own module
app.include_router(listings.router, prefix="/v1")
app.include_router(jobs.router, prefix="/v1")
app.include_router(overrides.router, prefix="/v1")
app.include_router(fees.router, prefix="/v1")

@app.get("/v1/health")
async def health(): return {"status": "ok"}
```

### 4.3 Endpoint list (final, Phase 1)

| Method | Path | Auth check | Enqueues |
|---|---|---|---|
| POST | `/v1/hunts` | any authed user (becomes owner) | — |
| GET | `/v1/hunts` | authed user's own hunts | — |
| GET | `/v1/hunts/{id}` | owner | — |
| PATCH | `/v1/hunts/{id}` | owner | rescore iff settings key is scoring-affecting |
| GET | `/v1/hunts/{id}/rubric` | owner (read) | — |
| PUT | `/v1/hunts/{id}/rubric` | owner | rescore (always — version bump) |
| POST | `/v1/hunts/{id}/listings` | owner | ingest |
| GET | `/v1/hunts/{id}/listings` | owner | — |
| DELETE | `/v1/listings/{id}` | owner | — |
| GET | `/v1/hunts/{id}/jobs` | owner | — |
| POST | `/v1/jobs/{id}/cancel` | owner | — |
| POST | `/v1/jobs/{id}/retry` | owner | — |
| POST | `/v1/jobs/{id}/checkpoint` | owner | resumes the parked job |
| POST | `/v1/listings/{id}/overrides` | owner | rescore |
| PUT | `/v1/listings/{id}/fees/{fee_slot}` | owner | rescore |

`GET` on overrides/fees/comments/ratings deliberately absent — frontend reads those
tables directly (§1.6). No `/v1/hunts/{id}/members`, `/invites`, `/refresh` routes in
Phase 1 (Phase 2/3).

### 4.4 New API dependencies (`api/pyproject.toml`)

`fastapi`, `uvicorn[standard]`, `supabase` (supabase-py), `jsonschema` (rubric option
validation against `value_schema`), `manzil-worker` (workspace, for the lifespan
loop — §1.5), plus dev: `pytest-asyncio`, `httpx`.

---

## 5. Frontend (`frontend/`)

### 5.1 Scaffold

```
pnpm create vite frontend --template react-ts
cd frontend && pnpm add @mantine/core @mantine/hooks @mantine/dates @mantine/notifications \
  @tanstack/react-query @tanstack/react-table mantine-react-table \
  @supabase/supabase-js react-router-dom
pnpm add -D vitest @testing-library/react @testing-library/jest-dom jsdom \
  openapi-typescript eslint
```

### 5.2 Directory tree

```
frontend/
├── index.html
├── vite.config.ts                 # vitest config co-located (test: {...})
├── .env.example                    # VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, VITE_API_BASE_URL
├── src/
│   ├── main.tsx                    # MantineProvider, QueryClientProvider, RouterProvider
│   ├── theme.ts
│   ├── lib/
│   │   ├── supabase.ts             # createClient(import.meta.env...)
│   │   ├── queryClient.ts
│   │   ├── apiClient.ts            # fetch wrapper: attaches Bearer token, throws ApiError
│   │   └── generated/api.d.ts      # openapi-typescript output (gitignored or committed — pick
│   │                               #   committed, so CI type-checks without a running API)
│   ├── auth/
│   │   ├── AuthProvider.tsx        # session context (onAuthStateChange)
│   │   ├── useAuth.ts
│   │   ├── RequireAuth.tsx         # route guard, redirects to /login
│   │   └── LoginPage.tsx           # magic-link email form
│   ├── routes/
│   │   └── router.tsx              # createBrowserRouter — routes below, §13.1 subset:
│   │                               #   "/" "/h/:huntId" "/h/:huntId/rubric" "/h/:huntId/tasks"
│   │                               #   "/h/:huntId/settings" "/login"
│   │                               #   (NOT /h/:huntId/compare, NOT /invite/:token — Phase 2/3)
│   ├── features/
│   │   ├── hunts/
│   │   │   ├── api.ts              # useHunts, useHunt, useCreateHunt (supabase-js reads +
│   │   │   │                       #   apiClient mutation)
│   │   │   ├── HuntSwitcherPage.tsx
│   │   │   └── HuntSettingsPage.tsx  # minimal: name/archive + the 4-key settings form
│   │   ├── rubric/
│   │   │   ├── api.ts              # useRubric (direct read), useUpdateRubric (apiClient)
│   │   │   ├── RubricWizardPage.tsx  # Stepper
│   │   │   ├── CriterionCard.tsx     # Switch + options table + NumberInput delta steppers
│   │   │   ├── GateControls.tsx      # dealbreaker / non-negotiable toggles + set-score input
│   │   │   └── widgets/
│   │   │       ├── BoolWidget.tsx
│   │   │       ├── EnumWidget.tsx
│   │   │       ├── NumberWidget.tsx
│   │   │       └── widgetForSchema.tsx   # value_schema -> widget dispatcher
│   │   ├── listings/
│   │   │   ├── api.ts              # useListings (direct read w/ embedded floor_plans/scores),
│   │   │   │                       #   useCreateListing, useDeleteListing (apiClient)
│   │   │   ├── OverviewPage.tsx
│   │   │   ├── OverviewTable.tsx     # mantine-react-table, one row per Unit Group
│   │   │   ├── ScoreCell.tsx         # color scale + multi-score stacked-layers indicator
│   │   │   ├── SubmitUrlControl.tsx  # URL TextInput + Source Policy Select (defaulted)
│   │   │   ├── DetailDrawer.tsx
│   │   │   ├── CriterionBreakdown.tsx  # renders scores.breakdown; evidence quotes
│   │   │   ├── OverrideControl.tsx     # inline edit -> POST override; shows original on hover
│   │   │   ├── FeeChecklist.tsx        # PUT fee entry per slot
│   │   │   └── FloorPlanPinControl.tsx # writes hunt_listings.pins (via a small apiClient PATCH,
│   │   │                               #   or fold into listings PATCH if simpler — resolve in code)
│   │   └── jobs/
│   │       ├── api.ts              # useJobs (apiClient GET, refetchInterval 3000),
│   │       │                       #   useCancelJob, useRetryJob, useAnswerCheckpoint
│   │       ├── TasksActivePage.tsx
│   │       ├── JobCard.tsx
│   │       └── CheckpointPrompt.tsx
│   └── components/                 # StaleBadge, EstimatedTag, AutoResolvedBadge (stubs —
│                                    #   full semantics arrive with P3 TTLs/checkpoints, but the
│                                    #   score cell needs the visual slot now per §13.2)
└── tests/setup.ts                  # jest-dom matchers
```

Note on `FloorPlanPinControl`: DESIGN doesn't give pins their own route in §5.1's
API table — they're part of `hunt_listings.pins`. Simplest Phase 1 shape: add a
`PATCH /v1/listings/{id}/pins` mini-endpoint (small enough to fold into
`listings/router.py` rather than a new module) rather than stretching the
`PATCH /v1/hunts/{id}` route to cover a per-listing field.

### 5.3 Key component behavior notes (from DESIGN §13.2)

- **ScoreCell**: color scale by `total`; stacked-layers indicator when a unit group
  has >1 scored plan; badge slots for stale/auto-resolved/single-source
  (`trust_link`) even though their triggering logic (TTLs, checkpoints) isn't built
  until Phase 3 — render the slot as inert/hidden until then, don't fake data.
- **RubricWizard widgets**: generated from `criteria_catalog.value_schema`
  (`{type: integer, minimum, maximum}` → `NumberWidget`; `{type: boolean}` →
  `BoolWidget`; `{type: string, enum: [...]}` → `EnumWidget`). This is the same
  `value_schema` the API validates options against — one schema, two consumers,
  exactly as DESIGN §8.2 intends.
- **CriterionBreakdown**: renders the persisted `scores.breakdown` JSON directly
  (already resolved/effective per §9.6) — don't re-derive effective values
  client-side.
- **OverrideControl**: on submit, POSTs to `/v1/listings/{id}/overrides`, then
  invalidates the `scores`/`overrides` query keys (the rescore job is async — a
  brief stale window until the ~3s job poll or a manual refetch is acceptable in
  Phase 1; Phase 2's realtime removes the gap).

### 5.4 Testing (per IMPLEMENTATION §2, "fills in at Phase 1")

`vitest` + Testing Library, component tests for anything with logic:
- `ScoreCell.test.tsx` — color-scale thresholds, multi-score indicator presence
- `widgetForSchema.test.tsx` — each `value_schema` shape renders the right widget
- `CriterionBreakdown.test.tsx` — gate rendering vs. delta rendering
- `OverrideControl.test.tsx` — provenance (original value) reachable
- `RubricWizardPage.test.tsx` — wizard output shape matches what the API accepts
  (share a fixture rubric between frontend and API tests if convenient)

No snapshot tests (repo convention). Mock `apiClient` calls with `vi.fn()`
rather than adding MSW — keeps the new dependency surface minimal (NFR5 spirit);
revisit if network-level mocking pain shows up.

---

## 6. Environment variables (additions to `infra/.env.example`)

| Var | Used by | Notes |
|---|---|---|
| `SUPABASE_SERVICE_ROLE_KEY` | api (lifespan worker loop only) | *(already listed as worker-only — Phase 1 adds the api's in-process loop as a second legitimate holder; still never in frontend)* |
| `MANZIL_WORKER_INPROCESS` | api | `true` in Phase 1; `false` from Phase 3 (P3-1) |
| `API_CORS_ORIGINS` | api | frontend dev origin(s), comma-separated |
| `API_ENVIRONMENT` | api | `local \| staging \| production` — gates OpenAPI docs exposure |
| `VITE_SUPABASE_URL` | frontend | public |
| `VITE_SUPABASE_ANON_KEY` | frontend | public, RLS-safe by design |
| `VITE_API_BASE_URL` | frontend | e.g. `http://localhost:8000` locally |

---

## 7. Task sequencing

Dependency graph (independent tracks after the migration lands):

```
DB: migration 0002 + dev-seed  (§2)
        │
        ├──► Worker: postgres_persistence + queue.py + rescore stage  (§3)
        │        │
        │        └──► API: lifespan worker-loop wiring, jobs router  (§4)
        │
        ├──► API: hunts, rubric, listings, overrides, fees routers  (§4)
        │        (parallel with the worker track above — different files)
        │
        └──► Frontend: auth shell, routes, direct-read hooks  (§5.1–5.2)
                 │
                 └──► Frontend: feature components  (§5.2–5.3)
                          (blocked on API only for mutation endpoints' shapes —
                          agree on request/response schemas early via the OpenAPI
                          codegen step so this doesn't block on a running API)
```

Concretely, in build order:
1. Migration 0002 + dev-seed script (§2) — everything else needs real rows.
2. `postgres_persistence.py` + `queue.py` (§3.1–3.2) — swap Phase 0's file
   persistence for Postgres; re-run existing worker tests against it.
3. API skeleton: `main.py`, `config.py`, `dependencies.py`, `exceptions.py`,
   health route, lifespan loop wired but harmless (no jobs yet) (§4.1–4.2).
4. Rescore stage (§3.3) + `rubric`/`overrides`/`fees` routers together, since all
   three just validate + write + enqueue rescore (§4.3).
5. `hunts` + `listings` + `jobs` routers (§4.3).
6. Frontend shell (auth, routes, Query client, Mantine frame) — can start as soon
   as step 3's OpenAPI schema exists, in parallel with steps 4–5.
7. Frontend feature modules, in the same dependency order as the routers they call.
8. Exit review against the real hunt (§8).

---

## 8. Testing & CI updates

- **API**: `pytest` + `httpx.AsyncClient(transport=ASGITransport(app))`,
  `dependency_overrides[get_current_user]` for a fake user. Tests run against the
  **local Supabase stack** (already a prerequisite per IMPLEMENTATION §1), not a
  mocked DB — this is the same stack Phase 2's RLS integration tests (P2-2) will
  need, so paying for it now is not wasted setup. New CI step before `pytest`:
  `supabase start && supabase db reset`, torn down after; `DATABASE_URL`/
  `SUPABASE_URL`/`SUPABASE_ANON_KEY` point at the local stack in CI.
- **Worker**: existing fixture-replay tests unaffected; new tests for
  `postgres_persistence` round-trip and `queue.py` orphan-reclaim (§3.1–3.2).
- **Frontend**: `pnpm -C frontend test` (vitest) and `pnpm -C frontend build`
  (catches TS errors against the generated API types) added to CI as their own job,
  matching IMPLEMENTATION §2's "frontend eslint + vitest from Phase 1" line.
- Update `IMPLEMENTATION.md` §2 CI description and §7 Phase 1 table once this plan
  is executed (small tasks land as changelog entries, per that doc's lightweight
  update protocol — no DESIGN §20 entry needed unless something here contradicts
  DESIGN, which it shouldn't).

---

## 9. Exit criteria (DESIGN §19)

- Yusuf's real hunt is created through the UI, all current spreadsheet listings
  ingested through `POST /v1/hunts/{id}/listings`, rubric built through the wizard,
  scores match hand-checked expectations.
- A week of real use without opening the spreadsheet.
- `kill -9` on the API process mid-job → job resumes within
  `JOB_ORPHAN_AFTER_SECONDS` on restart (manual verification of P1-2's contract).
- Rubric edit visibly rescoring all listings within a few seconds (bounded by the
  3s poll).
- Revise Phase 2's IMPLEMENTATION.md table on entry, per that doc's own rule.
