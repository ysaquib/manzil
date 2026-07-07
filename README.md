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

**Current phase: Phase 0** — prove the pipeline as a CLI (no UI, no auth, no RLS). See DESIGN §19 for scope and exit gates, IMPLEMENTATION §7 for the task-by-task plan.

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
│   │   ├── persistence.py       # Phase 0: run files under .manzil/runs/ (jobs table in P1)
│   │   ├── phase0_rubric.py     # the hardcoded Phase 0 rubric fixture (§19)
│   │   ├── stages/              # one module per DESIGN §10.3 stage + generated schema
│   │   ├── fetching/            # tier ladder, outcome classifier, cleaner, registry
│   │   ├── llm/                 # THE client seam — only package importing provider SDKs
│   │   └── agents/              # agents mode ONLY (learning track); empty until L1
│   ├── tests/fixtures/          # corpus/ (saved pages) · bench/ (labels) · recorded/ (replay)
│   └── evals/                   # dual-mode eval harness + reports
├── api/                         # manzil-api (FastAPI): near-empty until Phase 1
├── frontend/                    # Vite + React + Mantine: untouched until Phase 1
├── supabase/                    # config, migrations/, seed.sql (generated — never hand-edit)
├── infra/                       # .env.example, render.yaml (Phase 1+)
└── docs/adr/                    # rationale too detailed for DESIGN §20
```

## Setup

Prerequisites: [`uv`](https://docs.astral.sh/uv/) ≥ 0.5 · Supabase CLI · Docker (for the local Supabase stack) · Node 20 + `pnpm` (Phase 1+) · Playwright (`uv run playwright install chromium`, needed from P0-6).

```bash
uv sync                        # one venv, all workspace packages (pins Python 3.12)
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

### Worker CLI (`manzil`)

`uv run manzil --help` lists everything. What exists today and when to reach for it:

| Command | What it does | Use it when |
|---|---|---|
| `manzil ingest <url>` | Full pipeline — validate-url → fetch → validate → extract → verify → score — printing the per-plan score breakdown, verify flags, and cost | The Phase 0 workhorse. **Spends tokens** (two to three LLM calls) unless `MANZIL_LLM_MODE=replay` |
| `manzil llm-smoke` | One structured call through the LLM seam; prints echo, tokens, cost | Verifying keys/tracing after env changes; with `MANZIL_LLM_MODE=record` it refreshes the committed replay fixture |
| `manzil save-page <url> <slug>` | Fetches through the tier ladder and saves a corpus fixture dir (`raw.html`, `cleaned.txt`, `meta.json`) | Growing the fixture corpus toward 50+ pages, and capturing bench listings for hand-labeling (P0-11) |
| `manzil clean-corpus` | Re-runs the cleaner over every corpus page, rewriting each `cleaned.txt` | **After any change to `cleaner.py`** — cleaned text is derived data and must never go stale (runbook, IMPLEMENTATION §8) |
| `manzil census` | Probes every URL in `infra/census_urls.txt` through the tier ladder, writes `docs/hostile-domain-census.csv` | When a new listing domain enters the picture, or to refresh the Tier-3 decision-gate data (P0-14) |

`ingest` details worth knowing:

- Runs against the hardcoded Phase 0 rubric (`worker/src/manzil_worker/phase0_rubric.py` —
  2 br · in-unit laundry · cats · balcony · all-in < $2,000 conservative). Rubric editing
  arrives with the UI in Phase 1.
- Run state persists to `.manzil/runs/<job_id>.json` after **every** stage (gitignored) —
  inspect it to debug a run; it is the resumability contract in file form.
- Values VERIFY demoted below `min_confidence` (default `medium`) score as **unknown** —
  on a gated criterion that fires the gate. The extracted value is still in the run file's
  `reconciled` map with its flags; suspect data never silently passes.
- A malformed/private/binary URL fails at VALIDATE_URL before anything is fetched; a
  non-listing page fails at VALIDATE with the reason; a blocked/hostile domain fails at
  FETCH with the tier attempts; a checkpoint parks the run as `waiting_user` (exit code 3).
- `--no-tier2` forbids browser escalation, same as the other fetch commands.

Useful flags:

```bash
uv run manzil save-page <url> <slug> --official          # mark the source as the complex's own site
uv run manzil save-page <url> <slug> --notes "why saved" # provenance for meta.json
uv run manzil save-page <url> <slug> --no-tier2          # forbid browser escalation (fast, httpx only)
uv run manzil census --no-tier2                          # tier-1-only probe (no Playwright needed)
uv run manzil census my-urls.txt --out /tmp/census.csv   # custom input list / output path
```

Tier 2 needs the Playwright browser once per machine: `uv run playwright install chromium`.

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
| `fetching/cleaner.py` | `uv run manzil clean-corpus` → spot-check a few `cleaned.txt` → commit the regenerated corpus |
| `scoring/engine.py` | `uv run pytest shared/tests/golden` — any altered golden gets updated + explained in the same commit |
| Classifier heuristics | `uv run pytest -k "classifier or ladder"` — synthetic pages + real corpus sweep |
| A prompt (`llm/prompts/*.md`) or model pin (`llm/config.py`) | bump the prompt `version` front-matter → `MANZIL_LLM_MODE=record` against the bench set → compare the report — no eyeball-only merges. Old recordings invalidate automatically (the request hash covers prompt version + model) |
| `stages/schema_gen.py` or the catalog's `value_schema`s | `uv run pytest -k "schema_gen or extract"` — the extraction schema is generated, never hand-maintained |
| Migration files | `supabase db reset` must come back clean |

### Frontend (Phase 1+)

```bash
pnpm -C frontend dev | test | build
```

## Environment

Copy `infra/.env.example` to `.env` at the repo root. Notable variables (full table in IMPLEMENTATION §1): `ANTHROPIC_API_KEY`, `LANGFUSE_*` (tracing is wired before the first LLM call — an untraced call is a bug), `DATABASE_URL`, `SUPABASE_*` (service-role key is worker-only, never api or frontend), `MANZIL_MODE` (`workflow` | `agents`), `MANZIL_LLM_MODE` (`live` | `record` | `replay`).

## CI

GitHub Actions on every PR (`.github/workflows/ci.yml`): ruff check + format check · `mypy --strict` on `shared/` · pytest for all packages with `MANZIL_LLM_MODE=replay` (CI can never spend tokens). Frontend `eslint` + `vitest` join in Phase 1. Branches are short-lived and named by task ID (e.g. `p0-7-llm-seam`).
