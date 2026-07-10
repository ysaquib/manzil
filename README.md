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

**Current phase: Phase 0 tail ∥ Phase 1 in progress** — Phase 0 closes out the CLI pipeline spine and bench; Phase 1 replaces the spreadsheet with API + frontend. See DESIGN §19 for scope and exit gates, IMPLEMENTATION §7 for the task-by-task plan.

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
│   │   ├── evals/               # bench labels + eval harness + model compare (P0-11..13)
│   │   └── agents/              # agents mode ONLY (learning track); empty until L1
│   ├── tests/fixtures/          # pages/ (synthetic, committed) · corpus/ + bench/labels/ (LOCAL eval kit, gitignored) · recorded/ (smoke fixture committed)
│   └── evals/reports/           # generated bench reports (local artifacts — gitignored)
├── api/                         # manzil-api (FastAPI): domain routers + in-process worker loop
├── frontend/                    # Vite + React + Mantine: auth shell + feature pages (P1-9..13)
├── scripts/dev_seed.py          # P1-1: seed 1 hunt / 3 listings via the real ingest path
├── supabase/                    # config, migrations/, seed.sql (generated — never hand-edit)
├── infra/                       # .env.example, render.yaml (Phase 1+)
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

If all four are green, CI will be green — they are exactly the three CI jobs.

### Phase 1 local dev loop

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

Phase 1 ingest jobs persist to the `jobs` row via `PostgresPersistence` (not
`.manzil/runs/`). The CLI `manzil ingest` path still uses file persistence until
wired to enqueue jobs (P1-7).

Key env vars: `DATABASE_URL` (local Supabase Postgres), `MANZIL_WORKER_INPROCESS`
(API, default `true`), `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` /
`VITE_API_BASE_URL` (frontend) — full table in `infra/.env.example` and
IMPLEMENTATION §1.

### Frontend (Phase 1+)

```bash
pnpm -C frontend dev | test | build | gen:api-types
```

### Worker CLI (`manzil`)

`uv run manzil --help` lists everything. What exists today and when to reach for it:

| Command | What it does | Use it when |
|---|---|---|
| `manzil ingest <url>` | Full pipeline — validate-url → fetch → validate → extract → verify → score — printing the per-plan score breakdown, verify flags, and cost | The Phase 0 workhorse. **Spends tokens** (two to three LLM calls) unless `MANZIL_LLM_MODE=replay` |
| `manzil llm-smoke` | One structured call through the LLM seam; prints echo, tokens, cost | Verifying keys/tracing after env changes; with `MANZIL_LLM_MODE=record` it refreshes the committed replay fixture |
| `manzil save-page <url> <slug>` | Fetches through the tier ladder and saves a corpus fixture dir (`raw.html`, `cleaned.txt`, `meta.json`) | Growing the fixture corpus toward 50+ pages, and capturing bench listings for hand-labeling (P0-11) |
| `manzil clean-corpus` | Re-runs the cleaner over every corpus page, rewriting each `cleaned.txt` | **After any change to `cleaner.py` or `structured.py`** — cleaned text is derived data and must never go stale (runbook, IMPLEMENTATION §8) |
| `manzil census` | Probes every URL in `infra/census_urls.txt` through the tier ladder, writes `docs/hostile-domain-census.csv` | When a new listing domain enters the picture, or to refresh the Tier-3 decision-gate data (P0-14) |
| `manzil bench-skeleton <slug>` | Scaffolds `fixtures/bench/labels/{slug}.json` from a saved corpus page, every extractable key null | Starting a hand label (P0-11) — fill in true values, move unstated keys to `unknown`, delete ungraded keys |
| `manzil bench-run` | Runs EXTRACT → VERIFY over every bench label and grades against it; writes a JSON report to `worker/evals/reports/` | The eval harness (P0-12). **Spends tokens** unless `MANZIL_LLM_MODE=replay` |
| `manzil bench-compare <a.json> <b.json>…` | Side-by-side table over bench reports: gate/criterion accuracy, evidence flags, cost, latency | Judging a model sweep or prompt change (P0-13) — never eyeball-only |

`ingest` details worth knowing:

- Runs against the hardcoded Phase 0 rubric (`worker/src/manzil_worker/phase0_rubric.py` —
  2 br · in-unit laundry · cats · balcony · all-in < $2,000 conservative). Rubric editing
  arrives with the UI in Phase 1.
- Run state persists to `.manzil/runs/<job_id>.json` after **every** stage (gitignored) —
  inspect it to debug a run; this is the Phase 0 CLI resumability contract. Phase 1
  ingest jobs enqueued through the API or dev-seed use the `jobs` row instead.
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

Model pins live in `worker/src/manzil_worker/llm/config.py` as OpenRouter slugs
(`anthropic/claude-haiku-4.5`, `google/gemini-2.5-flash-lite`, …). All live calls
route through OpenRouter (`OPENROUTER_API_KEY`). For bench/dev runs,
`MANZIL_MODEL_<STAGE>` overrides a stage's pin without editing config (the model must be
priced in `MODEL_PRICES`, and recordings are keyed by model so replay never crosses models):

```bash
MANZIL_MODEL_SMOKE=google/gemini-2.5-flash-lite MANZIL_LLM_MODE=record uv run manzil llm-smoke
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

Copy `infra/.env.example` to `.env` at the repo root. Notable variables (full table in IMPLEMENTATION §1): `OPENROUTER_API_KEY`, `LANGFUSE_*` (tracing is wired before the first LLM call — an untraced call is a bug), `DATABASE_URL`, `SUPABASE_*` (service-role key is worker + API in-process loop only, never frontend), `MANZIL_WORKER_INPROCESS` (API, default `true`), `MANZIL_MODE` (`workflow` | `agents`), `MANZIL_LLM_MODE` (`live` | `record` | `replay`), `VITE_*` (frontend).

## CI

GitHub Actions on every PR (`.github/workflows/ci.yml`): ruff check + format check · `mypy --strict` on `shared/` · pytest for all packages with `MANZIL_LLM_MODE=replay` (CI can never spend tokens). Frontend `eslint` + `vitest` join in Phase 1. Branches are short-lived and named by task ID (e.g. `p0-7-llm-seam`).
