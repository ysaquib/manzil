# Manzil

**Manzil** (منزل — dwelling; in classical usage also a stage of a journey) is a collaborative, agent-powered apartment-hunting dashboard for a small group of users.

Paste a listing URL. An agent pipeline validates it, deduplicates it against known properties, finds sibling sources, extracts structured details, verifies them against page evidence, reconciles conflicts across sources, assesses photos, enriches with location and utility-cost data, and scores the result against a rubric the hunt owner fully controls. Everything lands in a live, shared table with provenance on every value.

The LLM produces **facts**; only the deterministic rubric engine produces **points**. The tool never makes an apartment look cheaper than a worst realistic month.

Manzil is also deliberately dual-purpose: a real tool on a real deadline, and a vehicle for learning multi-agent architectures — the critical path stays boring, the ambition lives in a flag-isolated agents mode judged by evals.

## Documents

| Document | Role |
|---|---|
| [`DESIGN.md`](DESIGN.md) | Source of truth for intent, architecture, contracts. Read §1 + §3 before touching anything. |
| [`IMPLEMENTATION.md`](IMPLEMENTATION.md) | Current mechanics: environment, conventions, phase work plans, runbooks. |
| [`AGENTS.md`](AGENTS.md) | Instructions for coding agents (`CLAUDE.md` imports it). |
| [`CHANGELOG.md`](CHANGELOG.md) | What has landed in the code, by task. |

**Current phase: Phase 3 ∥ the Phase 0 tail** — Phases 1 and 2 have exited
(2026-07-10 and 2026-07-18); the spreadsheet is retired and collaboration ships.
Phase 3 is the agent system: the planner + manifest-driven runner, the tool
registry with per-stage allow-lists, DEDUPE, IMAGE_FETCH, ENRICH, and the full
§9.5 cost composition have landed. Next up is DISCOVER (P3-5). The Phase 0 tail
is closed: bench labeling done and the P0-14 model-pin verdict ruled 2026-07-21
(EXTRACT/VERIFY → gemini-3-flash-preview; DESIGN §20).
See DESIGN §19 for scope and exit gates, IMPLEMENTATION §7 for the task plan.

## Repo layout

```
manzil/
├── DESIGN.md / IMPLEMENTATION.md / AGENTS.md
├── pyproject.toml               # uv workspace root: shared, api, worker; single uv.lock
├── shared/                      # manzil-shared: domain-blind, LLM-free
│   ├── src/manzil_shared/
│   │   ├── models.py            # Pydantic domain models — DESIGN §3 terms, verbatim
│   │   ├── catalog.py           # criteria catalog seed → generates supabase/seed.sql
│   │   ├── config.py            # tunables (single home, no magic numbers in stages)
│   │   ├── errors.py            # exception taxonomy the runner maps to job outcomes
│   │   └── scoring/             # pure, deterministic engine (P0-3) + cost composer
│   └── tests/                   # catalog round-trip; golden/ = exact-breakdown tests
├── worker/                      # manzil-worker: the agent pipeline
│   ├── src/manzil_worker/
│   │   ├── cli.py               # `manzil ingest <url>` — Phase 0 entry point
│   │   ├── state.py / runner.py # RunState + persist-before-advance runner (§10.2)
│   │   ├── persistence.py       # Phase 0 CLI: run files under .manzil/runs/
│   │   ├── postgres_persistence.py # P1-2: durable sink behind the jobs row
│   │   ├── queue.py             # P1-2: claim/heartbeat/reclaim + worker loop
│   │   ├── phase0_rubric.py     # the hardcoded Phase 0 rubric fixture (§19)
│   │   ├── stages/              # one module per DESIGN §10.3 stage + generated schema
│   │   ├── fetching/            # tier ladder, outcome classifier, cleaner + embedded-data miner, registry
│   │   ├── llm/                 # THE client seam — only package importing provider SDKs
│   │   ├── enrich/              # P3-7a images + P3-8 maps/proximity/ratings (geocode forever-cache)
│   │   ├── ops/                 # admin operations behind CLI commands (split_property)
│   │   ├── evals/               # bench labels + eval harness + model compare (P0-11..13)
│   │   └── agents/              # agents mode ONLY (learning track); empty until L1
│   ├── tests/fixtures/          # pages/ (synthetic, committed) · corpus/ + bench/labels/ (LOCAL eval kit, gitignored) · recorded/ (smoke fixture committed)
│   └── evals/reports/           # generated bench reports (local artifacts — gitignored)
├── api/                         # manzil-api (FastAPI): domain routers + in-process worker loop
├── frontend/                    # Vite + React + Mantine: auth shell + feature pages (P1-9..13)
├── scripts/dev_seed.py          # P1-1: seed 1 hunt / 3 listings via the real ingest path
├── supabase/                    # config, migrations/, seed.sql (generated — never hand-edit)
├── infra/                       # environment template + deployment inputs
└── docs/adr/                    # rationale too detailed for DESIGN §20
```

## Setup

Prerequisites: [`uv`](https://docs.astral.sh/uv/) ≥ 0.5 · Supabase CLI · Docker (for the local Supabase stack) · Node 20 + `pnpm` (Phase 1+) · Playwright (`uv run playwright install chromium`, needed from P0-6).

```bash
uv sync --all-packages         # one venv, all workspace packages (pins Python 3.12)
                               # plain `uv sync` installs only the root package's deps
                               # and UNINSTALLS the workers' — always pass the flag
cp infra/.env.example .env     # fill in keys; never commit real values
supabase start                 # local Postgres/Auth/Storage/Realtime stack
```

## Commands

### The daily loop

The four commands you run constantly, in the order you usually run them:

```bash
supabase db reset          # rebuild local DB: migrations + generated catalog seed
uv run pytest              # full suite: goldens, catalog round-trip, cleaner, classifier, ladder
uv run ruff check --fix . && uv run ruff format .
uv run mypy                # --strict on shared/ (the engine must be airtight)
```

If all four are green, CI will be green — they are the CI jobs. The one thing they
don't cover is the `collaboration-security` job (the RLS matrix), which needs a live
Supabase stack; see [Tests](#tests).

### Local app loop

Two terminals after setup (`uv sync --all-packages`, `cp infra/.env.example .env`,
`supabase start`):

```bash
# One command — Supabase check/start + API + frontend in tmux (reattaches if already running)
scripts/dev
scripts/dev status   # supabase + tmux session summary
scripts/dev kill     # stop the tmux session; Supabase keeps running
```

Requires `tmux` (`brew install tmux`). Pane 0 is the API; pane 1 is the frontend.
`Ctrl-b` then arrow keys switches panes; `Ctrl-b d` detaches without stopping servers.

Manual two-terminal loop (same processes, useful when debugging pipeline logs in isolation):

```bash
# Terminal 1 — DB + seed (once per reset)
supabase db reset
uv run --package manzil-worker python scripts/dev_seed.py

# Terminal 1 — API (in-process worker loop on by default via MANZIL_WORKER_INPROCESS=true)
uv run --package manzil-api uvicorn manzil_api.main:app --reload --port 8000

# Terminal 2 — frontend
pnpm -C frontend install   # first time
pnpm -C frontend dev
```

Regenerate API types after handler changes (API must be running locally):

```bash
pnpm -C frontend gen:api-types
```

Submitting a listing through the API creates the Listing and its ingest job in
one `submit_listing` RPC; the worker runs it and the terminal projection writes
the derived rows (property, sources, extractions, floor plans, scores). **This is
the only path that creates Listings** — `manzil ingest` is a debugging tool that
writes no database rows at all. See [Worker CLI](#worker-cli-manzil).

Key env vars: `DATABASE_URL` (local Supabase Postgres), `MANZIL_WORKER_INPROCESS`
(API, default `true`), `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` /
`VITE_API_BASE_URL` (frontend) — full table in `infra/.env.example` and
IMPLEMENTATION §1.

The durable worker runs inside the API process by default, including Tier-2
Playwright fetches. A separate worker service is optional; use the
[worker-isolation runbook](docs/worker-isolation.md) only if the operational
triggers in DESIGN §5 are observed.

`MANZIL_FRONTEND_URL` is the public frontend base used for copy-link and email-
invite redirects (`http://localhost:5173` locally). Supabase's local Mailpit
inbox is at `http://127.0.0.1:54324` after `supabase start`.

Local Auth disables public sign-up via `supabase/config.toml`; Site Admins
provision accounts from Admin → People. For hosted Supabase, disable **Allow new
users to sign up** and enable **Confirm email** in Authentication → Providers → Email,
allow the deployed `/auth/callback` and `/auth/reset-password` redirect URLs,
and keep both `{{ .ConfirmationURL }}` and `{{ .Token }}` in the magic-link
email template so existing users can click the link or enter its six-digit code.

To restore public registration in a future product phase, make it an explicit
security change: set `[auth].enable_signup` to `true`, restore a Register mode
that calls `supabase.auth.signUp`, and add back the anonymous-signup acceptance
test. Keep `[auth.email].enable_signup = true` in both postures: in the local
CLI it enables the email provider itself, including password login. Do not
enable only the UI or only GoTrue; the two-layer switch prevents an API caller
from bypassing the product surface while registration is disabled.

The frontend origin must exactly match `API_CORS_ORIGINS`; `localhost` and
`127.0.0.1` are different browser origins. To allow either local spelling:

```bash
API_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

Restart Uvicorn after changing `.env` so cached settings are reconstructed.

### Frontend (Phase 1+)

```bash
pnpm -C frontend dev | test | build | gen:api-types
```

### Worker CLI (`manzil`)

`uv run manzil --help` lists everything. What exists today and when to reach for it:

| Command | What it does | Use it when |
|---|---|---|
| `manzil ingest <url>` | Full pipeline — validate-url → fetch → validate → extract → verify → score — printing the per-plan score breakdown, verify flags, and cost. **Writes no database rows**; output goes to a run file | Debugging a fetch or an extraction against a real URL without touching your hunt. **Spends tokens** (two to three LLM calls) unless `MANZIL_LLM_MODE=replay` |
| `manzil llm-smoke` | One structured call through the LLM seam; prints echo, tokens, cost | Verifying keys/tracing after env changes; with `MANZIL_LLM_MODE=record` it refreshes the committed replay fixture |
| `manzil save-page <url> <slug>` | Fetches through the tier ladder and saves a corpus fixture dir (`raw.html`, `cleaned.txt`, `meta.json`) | Growing the fixture corpus toward 50+ pages, and capturing bench listings for hand-labeling (P0-11) |
| `manzil clean-corpus --slug <slug>` | Re-runs the cleaner over every corpus page, rewriting each `cleaned.txt` Optional `--slug` to clean only one page | **After any change to `cleaner.py` or `structured.py`** — cleaned text is derived data and must never go stale (runbook, IMPLEMENTATION §8) |
| `manzil split-property <property-id> --source-url <url>` | Peels a Source off a merged Property onto a fresh one, re-points its extractions/floor plans/Listings, enqueues a rescore per affected Hunt | Reversing a wrong DEDUPE merge (P3-4). Admin-only: connects with `DATABASE_URL` **below** the RLS boundary. `--listing <uuid>` (repeatable) moves Listings explicitly when no ingest job carried the URL |
| `manzil census` | Probes every URL in `infra/census_urls.txt` through the tier ladder, writes `docs/hostile-domain-census.csv` | When a new listing domain enters the picture, or to refresh the Tier-3 decision-gate data (P0-14) |
| `manzil bench-skeleton <slug>` | Scaffolds `fixtures/bench/labels/{slug}.json` from a saved corpus page, every extractable key null | Starting a hand label (P0-11) — fill in true values, move unstated keys to `unknown`, delete ungraded keys |
| `manzil extract-corpus <slug>` | Runs only EXTRACT → VERIFY over a saved corpus page and prints the raw result as JSON; no label, fetch, grading, scoring, or database writes | Inspecting one corpus Extraction directly. Honors `MANZIL_LLM_MODE`; `record` saves both LLM responses, while `replay` requires them |
| `manzil bench-run` | Runs EXTRACT → VERIFY over every bench label and grades against it; writes a JSON report to `worker/evals/reports/` | The eval harness (P0-12). **Spends tokens** unless `MANZIL_LLM_MODE=replay` |
| `manzil bench-compare <a.json> <b.json>…` | Side-by-side table over bench reports: gate/criterion accuracy, evidence flags, cost, latency | Judging a model sweep or prompt change (P0-13) — never eyeball-only |

`ingest` details worth knowing:

- **It is not a second way to add a listing.** `ingest` runs the pipeline in-process with
  file persistence and stops there: no `jobs` row, no property, no sources, no
  extractions, no scores. The terminal projection that writes those rows lives in the
  worker loop (`queue.py`), which the CLI never enters — so a DEDUPE merge decided during
  the run is also discarded, since the projection is what applies it. Use the UI/API to
  add a listing for real.
- **The score it prints is not your hunt's score.** It scores against the hardcoded Phase 0
  rubric (`worker/src/manzil_worker/phase0_rubric.py` — 2 br · in-unit laundry · cats ·
  balcony · all-in < $2,000 conservative), because the CLI has no hunt to read a rubric
  from. Two listings can tie here and differ in the app. Treat the facts and verify flags
  as the useful output, not the total. (A `--hunt` flag to score against a real rubric is
  planned — `.claude/plans/cli-submit-and-hunt-rubric.md`.)
- One thing it *does* share: with `DATABASE_URL` set it uses `PostgresRegistry` rather than
  an in-memory one, so it reads and updates the fetch/domain registry.
- Run state persists to `.manzil/runs/<job_id>.json` after **every** stage (gitignored) —
  inspect it to debug a run; this is the Phase 0 CLI resumability contract. Jobs enqueued
  through the API or dev-seed use the `jobs` row and `PostgresPersistence` instead.
- Values VERIFY demoted below `min_confidence` (default `medium`) score as **unknown** —
  on a gated criterion that fires the gate. The extracted value is still in the run file's
  `reconciled` map with its flags; suspect data never silently passes.
- A malformed/private/binary URL fails at VALIDATE_URL before anything is fetched; a
  non-listing page fails at VALIDATE with the reason; a blocked/hostile domain fails at
  FETCH with the tier attempts **plus a search hint pulled from the URL slug**
  ("try searching *riverfront towers detroit mi* on a fetchable source") so you can resubmit the
  same property from a friendlier site — the manual stand-in for DISCOVER until Phase 3.
- `--no-tier2` forbids browser escalation; `--no-tier3` forbids unblocker escalation —
  both apply to `ingest`, `save-page`, and `census` alike.

Useful flags:

```bash
uv run manzil save-page <url> <slug> --official          # mark the source as the complex's own site
uv run manzil save-page <url> <slug> --notes "why saved" # provenance for meta.json
uv run manzil save-page <url> <slug> --no-tier2          # forbid browser escalation (fast, httpx only)
uv run manzil census --no-tier2                          # tier-1-only probe (no Playwright needed)
uv run manzil census my-urls.txt --out /tmp/census.csv   # custom input list / output path
```

Tier 2 needs the Playwright browser once per machine: `uv run playwright install chromium`.

### What's inside `cleaned.txt`

Three sections, produced by `fetching/cleaner.py` in one pass (DESIGN v2.6):

1. **Readable page text** — trafilatura (readability-lxml fallback), 5–10×
   smaller than the raw HTML.
2. **`[FEE TABLES]`** — fee/deposit/pet-charge tables re-rendered row-by-row
   when the generic extractor dropped them.
3. **`[EMBEDDED DATA]`** — a pruned JSON digest mined from script tags
   (`fetching/structured.py`): JSON-LD blocks plus framework state blobs
   (`__NEXT_DATA__`, `window.__PRELOADED_STATE__`, bare-JSON state scripts).
   This is where listing sites actually ship floor plans, unit rents, sqft and
   availability — often *only* here at tier 1. Noise and `similar`/`nearby`
   listings (another property's prices!) are pruned; media/URL bulk is
   scrubbed; the digest is capped at 40k chars. Zero LLM involved, and JS
   object literals are never evaluated — sites shipping those still contribute
   via JSON-LD.

EXTRACT sees this one text blob and nothing else; the classifier also counts
it, so a page whose DOM is empty but whose state blob carries the listing
classifies `success` at tier 1 instead of escalating.

### Tier 3 — managed unblocker (free plans only)

The fetch ladder escalates to a scraping-API vendor when tiers 1–2 come back blocked —
but **only if a provider key is configured**; without one the ladder behaves exactly as
before. Strictly free plans (DESIGN §20 2026-07-07): going paid is a design decision,
not an env change.

```bash
# .env — Bright Data Web Unlocker is the default provider
BRIGHTDATA_API_KEY=...          # from brightdata.com → Web Unlocker zone
BRIGHTDATA_ZONE=web_unlocker1   # your zone name (this is their default)
```

**Changing the provider** is one env var — the selected provider's own key gates it:

```bash
MANZIL_TIER3_PROVIDER=scrapingbee   # + SCRAPINGBEE_API_KEY=...
```

**Adding a provider** is one `_Provider` entry in `worker/src/manzil_worker/fetching/tier3.py`
(request builder + required env names) — nothing outside that module changes. After any
provider change, re-run `uv run manzil census` and check the `tier3_outcome` column:
`tier3_ok` means the vendor beats the domain, `hostile_unfetchable` means even tier 3 lost.

### Bench workflow (P0-11 → P0-13)

```bash
uv run manzil save-page <url> <slug>                     # 1. capture the page into the corpus
uv run manzil bench-skeleton <slug>                      # 2. scaffold labels/{slug}.json
$EDITOR worker/tests/fixtures/bench/labels/<slug>.json   # 3. HAND-label: values / unknown / plans
$EDITOR worker/tests/fixtures/bench/manifest.md          #    …and say why the page earned a slot
MANZIL_LLM_MODE=record uv run manzil bench-run --name baseline-haiku   # 4. run + record (tokens!)
MANZIL_MODEL_EXTRACT=google/gemini-2.5-flash-lite MANZIL_LLM_MODE=record \
  uv run manzil bench-run --name flash-lite              # 5. sweep another model
uv run manzil bench-compare worker/evals/reports/baseline-haiku.json \
  worker/evals/reports/flash-lite.json                   # 6. the P0-13 decision table
```

Labels are ground truth **only a human writes** (step 3) — the loader refuses unfilled
skeletons, unknown keys, and out-of-catalog values, so a typo'd label can't silently
mis-grade a run. Keys absent from both `criteria` and `unknown` simply aren't graded.

The corpus and labels are a **local eval kit** — gitignored, never repo content
(scraped pages carry copyright + embedded vendor keys; labels only grade the exact
snapshots next to them; DESIGN §20 v2.8). `bench/manifest.md` is the tracked part.
**Back the kit up after every session** (runbook, IMPLEMENTATION §8):

```bash
tar czf ~/manzil-eval-kit-$(date +%Y%m%d).tgz -C worker/tests/fixtures corpus bench/labels
```

### Tests

```bash
uv run pytest                                       # everything (shared + api + worker)
uv run --package manzil-shared pytest shared/tests  # engine goldens + catalog round-trip only
uv run --package manzil-worker pytest worker/tests  # cleaner, classifier, ladder, fixtures
uv run pytest -k classifier                         # one area, by keyword
```

API router/integration tests require the local Supabase stack because their
shared fixtures mint real users/JWTs and use PostgREST plus Postgres. The RLS
matrix remains a separate command so CI reports the collaboration-security gate
independently:

```bash
supabase start
supabase db reset --yes
MANZIL_WORKER_INPROCESS=false \
  uv run --package manzil-api pytest api/tests --ignore=api/tests/test_rls_matrix.py -q
MANZIL_WORKER_INPROCESS=false \
  uv run --package manzil-api pytest api/tests/test_rls_matrix.py -q
```

Use `MANZIL_WORKER_INPROCESS=false` while running API tests if a development API
is also connected to the same local database. Otherwise its worker can claim a
test Job immediately after it is queued, making state-transition assertions race
with legitimate worker activity. The CI `collaboration-security` job starts a
fresh Supabase stack and runs this command on every change.

LLM call modes (`MANZIL_LLM_MODE`):

| Mode | Behavior | Use it when |
|---|---|---|
| `live` | Real API calls | Local dev against a real model (default) |
| `record` | Real calls, responses saved to `fixtures/recorded/` | Adding a fixture, or after a prompt/model version bump (re-record the bench) |
| `replay` | Serves from disk, **fails on any miss** | CI always; locally to prove a change is LLM-neutral |

```bash
MANZIL_LLM_MODE=replay uv run pytest                                     # what CI runs — zero tokens
MANZIL_LLM_MODE=record uv run --package manzil-worker pytest -k <slug>   # re-record one fixture (spends tokens)
```

Model pins live in `worker/src/manzil_worker/llm/config.py` as OpenRouter slugs, one
per stage. All live calls route through OpenRouter (`OPENROUTER_API_KEY`).

**`MANZIL_MODEL_<STAGE>` overrides one stage's pin for a single run** — the P0-13 sweep
mechanism, so a model can be judged without editing config (and without a config edit
sneaking into a commit). The variable is *not* in `.env.example` on purpose: it is a
per-command knob, not an environment setting. Two guardrails apply — the override must
be priced in `MODEL_PRICES` (an unpriced model raises rather than guessing at cost), and
recordings are keyed by model, so `replay` can never serve one model's response for
another.

`<STAGE>` is the upper-cased stage name from `STAGE_MODELS`:

| Variable | Overrides |
|---|---|
| `MANZIL_MODEL_EXTRACT` | EXTRACT — the structured pull from `cleaned.txt`. The main bench dial, and the model `bench-run` names its default report after |
| `MANZIL_MODEL_VERIFY` | VERIFY check 4 (the LLM check; checks 1–3 are code). Sweep it *with* `MANZIL_MODEL_EXTRACT` — the bench grades the pair, since a demotion below `min_confidence` scores as unknown |
| `MANZIL_MODEL_SMOKE` | `llm-smoke` — the cheapest way to prove a new slug routes and is priced |
| `MANZIL_MODEL_VALIDATE` | VALIDATE (is this page a listing?) |
| `MANZIL_MODEL_DISCOVER` · `MANZIL_MODEL_VISION` | The taste-tier stages (P3-5, P3-7b) |
| `MANZIL_MODEL_RECONCILE_EQUIVALENCE` · `MANZIL_MODEL_CUSTOM_MATCH` · `MANZIL_MODEL_ENRICH_REVIEWS` · `MANZIL_MODEL_UTILITY_BASELINES` · `MANZIL_MODEL_PLAN_ASSIST` | The remaining workhorse stages |

```bash
MANZIL_MODEL_SMOKE=google/gemini-2.5-flash-lite MANZIL_LLM_MODE=record uv run manzil llm-smoke

# sweep the extraction pair — one --name per run, then compare
MANZIL_MODEL_EXTRACT=google/gemini-3.1-flash-lite \
MANZIL_MODEL_VERIFY=google/gemini-3.1-flash-lite \
MANZIL_LLM_MODE=record uv run manzil bench-run --name flash-lite-pair
```

Golden-test rule: if an engine change alters any golden in `shared/tests/golden/`, update the golden **in the same commit** with an explanation — that's the audit trail for scoring behavior.

### Lint, format, types

```bash
uv run ruff check --fix . && uv run ruff format .   # lint + format (line length 100)
uv run ruff format --check .                        # check-only, what CI runs
uv run mypy                                         # --strict on shared/ (configured in root pyproject)
```

### Database and catalog

```bash
supabase start                                                   # bring up the local stack (Docker)
supabase stop                                                    # tear it down
supabase db reset                                                # reapply migrations + seed (destructive, local only)
uv run --package manzil-shared python -m manzil_shared.catalog   # regenerate supabase/seed.sql from catalog.py
docker exec -it supabase_db_manzil psql -U postgres              # poke the DB directly
```

`supabase/seed.sql` is generated — never edit it by hand; the drift-guard test fails if it's stale. Migrations are append-only: never edit an applied migration, always add a new one.

### When X changes, run Y

| You changed… | Then run… |
|---|---|
| `shared/catalog.py` (add/edit a criterion) | regenerate seed → `supabase db reset` → add a golden covering it → if gate-eligible, add a bench label field |
| `fetching/cleaner.py` or `fetching/structured.py` (incl. its drop/signal/scrub lists) | `uv run manzil clean-corpus` → spot-check a few `cleaned.txt` (floor plans present? no `similar` contamination?) — the corpus is local (gitignored, DESIGN §20 v2.8), nothing to commit |
| `scoring/engine.py` | `uv run pytest shared/tests/golden` — any altered golden gets updated + explained in the same commit |
| Classifier heuristics | `uv run pytest -k "classifier or ladder"` — synthetic pages + real corpus sweep |
| A prompt (`llm/prompts/*.md`) or model pin (`llm/config.py`) | bump the prompt `version` front-matter → `MANZIL_LLM_MODE=record` against the bench set → compare the report — no eyeball-only merges. Old recordings invalidate automatically (the request hash covers prompt version + model) |
| `stages/schema_gen.py` or the catalog's `value_schema`s | `uv run pytest -k "schema_gen or extract"` — the extraction schema is generated, never hand-maintained |
| A bench label, or `evals/` grading logic | `uv run pytest -k bench` — then re-run `manzil bench-run` before trusting any older report |
| Migration files | `supabase db reset` must come back clean |

### Environment

Copy `infra/.env.example` to `.env` at the repo root. Notable variables (full table in IMPLEMENTATION §1): `OPENROUTER_API_KEY`, `LANGFUSE_*` (tracing is wired before the first LLM call — an untraced call is a bug), `DATABASE_URL`, `SUPABASE_*` (service-role key is worker + API in-process loop only, never frontend), `GOOGLE_MAPS_API_KEY` (Phase 3 ENRICH), `MANZIL_WORKER_INPROCESS` (API, default `true`), `MANZIL_MODE` (`workflow` | `agents`), `MANZIL_LLM_MODE` (`live` | `record` | `replay`), `VITE_*` (frontend).

#### Per-command variables (deliberately not in `.env`)

These are run knobs, not configuration. Setting them in `.env` makes a temporary
choice permanent and invisible — prefix them onto the one command instead.

| Variable | Effect | Typical use |
|---|---|---|
| `MANZIL_MODEL_<STAGE>` | Overrides one stage's model pin for this run; must be priced in `MODEL_PRICES` | Model sweeps — see the table above |
| `MANZIL_LLM_MODE` | `live` \| `record` \| `replay`. Has an `.env` default, but is normally set per command | `replay` to prove a change spends no tokens; `record` to refresh a fixture |
| `MANZIL_RECORDED_DIR` | Relocates the replay/record fixture directory (default `worker/tests/fixtures/recorded/`) | Recording into a scratch dir to diff against the committed fixtures before overwriting them |
| `MANZIL_WORKER_INPROCESS=false` | Stops the API process from claiming jobs | **Required for API tests** when a dev API is on the same local DB — otherwise its worker claims a test Job and races the state-transition assertions |
| `MANZIL_MODE=agents` | Selects the learning track | Not usable yet — `manzil ingest` exits 2 until L1 lands |
| `DATABASE_URL` | Also read directly by the CLI | `ingest` uses `PostgresRegistry` when set and an in-memory one when not; `split-property` **requires** it (service-role, below RLS) |
| `MANZIL_TIER3_PROVIDER` | `brightdata` (default) \| `scrapingbee` | Switching unblocker vendors; the selected provider's key still gates the tier |

Two things that look like env vars but aren't: **`MANZIL_JOB_MAX_ATTEMPTS`** is a constant
in `shared/src/manzil_shared/config.py` (the dead-letter threshold — change it in code,
with intent), and **`BRIGHTDATA_ZONE`** defaults to `web_unlocker1` in `tier3.py` if unset.

## CI

GitHub Actions on every PR (`.github/workflows/ci.yml`): ruff check + format check · `mypy --strict` on `shared/` · pytest for all packages with `MANZIL_LLM_MODE=replay` (CI can never spend tokens). Frontend `eslint` + `vitest` join in Phase 1. Branches are short-lived and named by task ID (e.g. `p0-7-llm-seam`).
