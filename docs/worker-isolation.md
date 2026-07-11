# Worker Isolation Migration Guide

This runbook moves Manzil's existing durable worker loop out of the FastAPI
process. It is optional P3-1, not a Phase 3 prerequisite. The worker remains a
separate logical package in either deployment; this guide changes only process
ownership.

## When to use it

Keep `MANZIL_WORKER_INPROCESS=true` unless production evidence shows at least
one trigger from DESIGN §5:

- Tier-2 Playwright Jobs repeatedly push the API into memory pressure, restarts,
  or 502 responses.
- API latency materially worsens while a browser Job runs.
- The Hunt needs more Job concurrency than one API-hosted loop should provide.
- Scheduler ticks must remain continuously available independently of API
  lifecycle or scale-to-zero behavior.

Record the evidence (provider metrics, logs, Job IDs, and timestamps) before
starting. Confirm the added hosting cost with the Owner. Changing providers or
introducing infrastructure beyond one worker process requires its own design
review under NFR5.

## Invariants

The migration must preserve these properties:

1. Postgres `jobs` remains the only queue and state store.
2. The separate process calls the same `build_dispatch` and `run_worker_loop`
   code as the API lifespan loop.
3. Both processes use the same `DATABASE_URL`, worker/LLM/fetch settings, and
   service-role credentials.
4. Stage state is persisted before cursor advancement; no alternate persistence
   path is introduced.
5. There is exactly one intended worker claimant during cutover. `SKIP LOCKED`
   prevents duplicate claims, but overlapping loops are not the deployment
   strategy.
6. The API never receives Playwright, LLM, or Maps work through FastAPI
   `BackgroundTasks`; it only inserts Jobs.

## 1. Add and test a standalone entry point

There is currently no production worker command; the API imports the loop
directly. Add a thin entry point in `manzil_worker` which:

1. Loads the same root `.env`/environment configuration used by the worker.
2. Creates an `asyncpg` pool from `DATABASE_URL`.
3. Builds dispatch with `build_dispatch(pool, dsn=database_url)`.
4. Installs SIGTERM/SIGINT handlers that set the loop's `asyncio.Event`.
5. Calls `run_worker_loop(pool, stop=stop, dispatch=dispatch)`.
6. Stops claiming new Jobs on shutdown, allows the current Job to drain, and
   closes the pool.

Expose it as a package script such as `manzil-worker`. Do not duplicate queue or
dispatch logic in the entry point.

Add tests that prove:

- startup builds the Postgres registry rather than falling back to the
  in-memory registry;
- SIGTERM requests a clean drain;
- an ingest Job and a rescore Job reach terminal states through the entry point;
- an abrupt process exit leaves a running Job reclaimable after
  `JOB_ORPHAN_AFTER_SECONDS`;
- the API with `MANZIL_WORKER_INPROCESS=false` does not start a claimant.

Local validation should use two terminals:

```bash
# Terminal 1: API only
MANZIL_WORKER_INPROCESS=false \
  uv run --package manzil-api uvicorn manzil_api.main:app --port 8000

# Terminal 2: standalone worker (after the entry point is implemented)
uv run --package manzil-worker manzil-worker
```

Submit a synthetic fixture URL through the API and verify its Job is claimed
only by Terminal 2.

## 2. Build the worker image/service

Add the deployment definition only after the standalone entry point is green.
For Render, create one background worker using the same repository revision as
the API. Its build must:

1. Install the uv workspace with `uv sync --all-packages --frozen`.
2. Install Chromium and the OS libraries required by the pinned Playwright
   version. Prefer Playwright's supported image/base or its dependency installer
   rather than maintaining an incomplete library list manually.
3. Start only the standalone worker command—never Uvicorn.
4. Use a single worker-loop process initially. Increase concurrency only after
   measuring provider limits, browser memory, and `SKIP LOCKED` behavior.

The API image may continue containing the worker dependency because
`manzil_api.worker_loop` is the rollback path. Removing Playwright or the
`manzil-worker` workspace dependency from the API is a later optimization, not
part of the safe cutover.

Configure these worker secrets/settings to match the API where applicable:

- `DATABASE_URL`
- `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
- `OPENROUTER_API_KEY`
- `LANGFUSE_*`
- fetch-tier provider keys and `MANZIL_TIER3_PROVIDER`
- Google Maps credentials once those Stages exist
- `MANZIL_MODE`, `MANZIL_LLM_MODE`, Job retry/orphan timing, and model settings

Do not expose `SUPABASE_SERVICE_ROLE_KEY` to the frontend. The standalone worker
uses it for the same trusted global writes currently performed in-process.

## 3. Staging validation

Deploy the separate worker while keeping production unchanged. In a staging
database or a controlled maintenance window:

1. Ensure the API claimant is stopped or configured
   `MANZIL_WORKER_INPROCESS=false` before allowing the new worker to claim.
2. Enqueue one Tier-1 ingest, one Tier-2 Playwright ingest, and one rescore Job.
3. Verify `jobs.locked_by` identifies the standalone worker and only one worker
   claims each Job.
4. Verify Stage events, RunState snapshots, Extractions, Floor Plans, Scores,
   costs, and Realtime UI updates match the in-process path.
5. Terminate the worker during a non-destructive synthetic Job. Confirm the Job
   is reclaimed after the orphan threshold and resumes at its persisted Stage.
6. Confirm SIGTERM drains an in-flight Job during an ordinary deploy.
7. Run the worker/queue test suite and the collaboration/RLS matrix. The worker
   still uses trusted credentials; user-facing RLS behavior must not change.
8. Compare API latency and peak memory during the Tier-2 Job with the recorded
   pre-migration baseline.

Do not proceed unless the browser Job completes and orphan recovery succeeds.

## 4. Production cutover

Choose a period with no active Jobs visible in Tasks.

1. Deploy the validated standalone worker definition with claiming disabled or
   the process scaled to zero.
2. Set the API environment to `MANZIL_WORKER_INPROCESS=false` and deploy it.
3. Confirm API logs do not contain the in-process-loop startup message and the
   health endpoint remains green.
4. Start/scale the standalone worker.
5. Submit one known synthetic or low-risk Listing and watch it through DONE.
6. Submit a URL known to require Tier 2 and verify API health, worker memory,
   Job Events, output persistence, and Realtime updates.
7. Leave the API's worker code and toggle intact for rollback.

This ordering creates a short interval with no claimant rather than two
intentional claimants. Queued Jobs are durable, so that interval is safe.

## 5. Monitoring after cutover

For at least the first several real Jobs, watch:

- API and worker RSS/peak memory, restarts, and response latency;
- queue wait time (`created_at` to `started_at`) and Job runtime;
- orphan reclaims, attempts, dead-letter failures, and stale `locked_at` values;
- Playwright launch failures caused by missing browser/OS dependencies;
- scheduler tick logs and duplicate due-Job creation;
- LLM tracing coverage and provider credentials;
- hosting cost relative to the problem that triggered the migration.

The migration is successful when Tier-2 Jobs complete, API health remains
stable, no duplicate claimant behavior is observed, and the triggering metric
improves.

## 6. Rollback

If the standalone worker fails:

1. Stop or scale the standalone worker to zero first.
2. Wait for any clean drain. If it crashed, allow the orphan threshold to pass;
   do not manually clear a lock while its process may still be alive.
3. Restore `MANZIL_WORKER_INPROCESS=true` on the API and deploy it.
4. Confirm the API logs the loop startup and queued/orphaned Jobs resume.
5. Re-run one synthetic Job and inspect its Stage history.

No data migration is required in either direction because both deployments use
the same Postgres Job and persistence contracts.
