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
│   │   ├── stages/              # one module per DESIGN §10.3 stage
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

### CLI

```bash
uv run manzil --help
uv run manzil ingest <url>     # ingest a listing URL, print the score breakdown (lands in P0-10)
```

### Tests

```bash
uv run pytest                                       # everything
uv run --package manzil-shared pytest shared/tests  # engine goldens + catalog round-trip
uv run --package manzil-worker pytest worker/tests  # stages vs fixtures (replay mode)
uv run --package manzil-api    pytest api/tests

MANZIL_LLM_MODE=replay uv run pytest                # CI mode: replay misses fail, no live LLM calls
MANZIL_LLM_MODE=record uv run --package manzil-worker pytest -k <slug>   # re-record fixtures (spends tokens)
```

### Lint, format, types

```bash
uv run ruff check --fix . && uv run ruff format .   # lint + format (line length 100)
uv run mypy                                         # --strict on shared/ (configured in root pyproject)
```

### Database and catalog

```bash
supabase db reset                                            # apply migrations + generated seed
uv run --package manzil-shared python -m manzil_shared.catalog   # regenerate supabase/seed.sql from catalog.py
```

To add a catalog criterion: edit `shared/src/manzil_shared/catalog.py` → regenerate seed → `supabase db reset` → add a golden test. Full runbooks (prompt changes, fixture recording, orphaned-job requeue, deploys) in IMPLEMENTATION §8.

### Frontend (Phase 1+)

```bash
pnpm -C frontend dev | test | build
```

## Environment

Copy `infra/.env.example` to `.env` at the repo root. Notable variables (full table in IMPLEMENTATION §1): `ANTHROPIC_API_KEY`, `LANGFUSE_*` (tracing is wired before the first LLM call — an untraced call is a bug), `DATABASE_URL`, `SUPABASE_*` (service-role key is worker-only, never api or frontend), `MANZIL_MODE` (`workflow` | `agents`), `MANZIL_LLM_MODE` (`live` | `record` | `replay`).

## CI

GitHub Actions on every PR (`.github/workflows/ci.yml`): ruff check + format check · `mypy --strict` on `shared/` · pytest for all packages with `MANZIL_LLM_MODE=replay` (CI can never spend tokens). Frontend `eslint` + `vitest` join in Phase 1. Branches are short-lived and named by task ID (e.g. `p0-7-llm-seam`).
