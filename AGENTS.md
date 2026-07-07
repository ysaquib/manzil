# Manzil — Agent Instructions

Agentic apartment-hunting dashboard. Monorepo: `frontend/` (React + Vite + Mantine) · `api/` (FastAPI) · `worker/` (agent pipeline) · `shared/` (domain models + scoring engine) · `supabase/` (migrations, RLS) · `infra/`.

## Before any task
1. Read `DESIGN.md` §1 (usage + reading paths) and §3 (glossary). Domain terms — Hunt, Property, Listing, Source, Floor Plan, Unit Group, Criterion, Rubric, Gate, Extraction, Override, Job, Stage, Checkpoint — have exact meanings. Use them verbatim in code; never invent synonyms.
2. Follow the §1 reading path for the area you are touching.
3. `DESIGN.md` is authoritative for design intent. If code or reality contradicts it, STOP and flag the conflict — never silently pick a side. (`IMPLEMENTATION.md`, once it exists, owns current mechanics and may churn freely; DESIGN.md still wins on intent.)

## Hard rules
- Never implement anything listed in DESIGN.md §18 (Deferred / Backlog) unless explicitly asked.
- Ambiguous or missing design detail → ask, don't guess. The answer gets recorded in DESIGN.md.
- Material design changes require a §20 Decision Log entry plus in-place updates to affected sections.
- No provider SDK imports outside `worker/pipeline/llm/`. Every model call goes through the client seam: `call_structured` / `call_agent` / `call_vision`.
- `shared/` stays domain-blind (no rental-specific assumptions) and LLM-free. The scoring engine is pure and deterministic — facts in, points out, nothing else.
- Pipeline stages persist state BEFORE advancing the cursor. Stages are idempotent and resumable.
- Extraction stages get ZERO tools (security control, §16). Tool loops are turn-budgeted and per-stage allow-listed (§10.2). In workflow mode, only DISCOVER and location-type custom criteria use tool loops — nothing else.
- RLS is the security boundary. Frontend checks are UX, never enforcement.

## Modes (§10.11)
- The hard rules above govern **workflow mode** — the shipping baseline and critical path. It must work standalone, always.
- **Agents mode** (`--mode=agents`) is the learning track: LangGraph + multi-agent patterns, allowed ONLY inside `worker/src/manzil_worker/agents/`. It imports the deterministic truth layer (VERIFY checks 1–3, RECONCILE ladder, SCORE) and the RunState/persistence contract; it never modifies them, and nothing on the critical path imports from `agents/`.
- No agents-mode component becomes default behavior without eval-harness evidence AND a §20 Decision Log entry.
- Langfuse tracing on EVERY LLM call, both modes, from the first call (NFR6). An untraced call is a bug.

## Pinned data contracts (do not reshape)
Catalog entry (§8.2) · hunt settings (§8.2) · rubric option (§8.2) · score breakdown (§9.3) · plan manifest (§10.4) · checkpoint prompt (§10.10).

## Testing
- Scoring engine: golden tests in `shared/` asserting exact breakdowns.
- Pipeline stages: fixture-based (saved cleaned text + recorded LLM responses). No live LLM calls in CI, ever.
- Prompt or model changes: re-run the Phase 0 bench set. Eyeballing is not validation.
- Fixture corpus: `worker/tests/fixtures/` (50+ real listing pages).

## Commands
- Python (uv workspace, root lockfile): `uv sync --all-packages` (plain `uv sync` uninstalls workspace-member deps) · `uv run --package manzil-shared pytest shared/tests` (likewise `manzil-api`, `manzil-worker`) · `uv run ruff check --fix .`
- Frontend: `pnpm -C frontend dev | test | build`
- DB: `supabase db reset` locally; migrations live in `supabase/migrations/`.

## Current phase
Phase 0 (DESIGN.md §19): CLI pipeline proof. In scope: `shared/` engine + catalog, migrations (global tables only), fetch tiers + outcome classifier, EXTRACT → VERIFY, CLI `ingest <url>`, Langfuse wiring, eval harness skeleton, model bench, hostile-domain census. Learning Track L0 only — no agents-mode code before Phase 0 exits. Exit gates listed in §19.