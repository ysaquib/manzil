# Manzil — Agent Instructions

Agentic apartment-hunting dashboard. Monorepo: `frontend/` (React + Vite + Mantine) · `api/` (FastAPI) · `worker/` (agent pipeline) · `shared/` (domain models + scoring engine) · `supabase/` (migrations, RLS) · `infra/`.

## Before any task
1. Read `DESIGN.md` §1 (usage + reading paths) and §3 (glossary). Domain terms — Hunt, Property, Listing, Source, Floor Plan, Unit Group, Criterion, Rubric, Gate, Extraction, Override, Job, Stage, Checkpoint — have exact meanings. Use them verbatim in code; never invent synonyms.
2. Follow the §1 reading path for the area you are touching.
3. `DESIGN.md` is authoritative for design intent. If code or reality contradicts it, STOP and flag the conflict — never silently pick a side. (`IMPLEMENTATION.md`, once it exists, owns current mechanics and may churn freely; DESIGN.md still wins on intent.)

## Hard rules
- Never implement anything listed in DESIGN.md §18 (Deferred / Backlog) unless explicitly asked.
- Ambiguous or missing design detail → ask, don't guess. The answer gets recorded in DESIGN.md.
- Material design changes require a §20 Decision Log entry (append to decision log table) plus in-place updates to affected sections.
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
- Fixture corpus: `worker/tests/fixtures/corpus/` (50+ real listing pages) — a **local eval kit**, gitignored with the bench labels (DESIGN §20 v2.8); CI reads only the committed synthetic `fixtures/pages/`.

## Commands
- Python (uv workspace, root lockfile): `uv sync --all-packages` (plain `uv sync` uninstalls workspace-member deps) · `uv run --package manzil-shared pytest shared/tests` (likewise `manzil-api`, `manzil-worker`) · `uv run ruff check --fix .`
- Frontend: `pnpm -C frontend dev | test | build`
- DB: `supabase db reset` locally; migrations live in `supabase/migrations/`.

## Current phase
**Phase 0 tail, Phase 2 exit acceptance, and Phase 3 Wave A are running in parallel.** Full task tables: IMPLEMENTATION.md §7.

**Phase 0 (DESIGN.md §19) — closing out.** The pipeline spine (P0-1..P0-10) is done: `shared/` engine + catalog, migrations (global tables only), fetch tiers + outcome classifier + tier-3 free-plan stopgap, VALIDATE_URL → FETCH → VALIDATE → EXTRACT → VERIFY → SCORE, CLI `ingest <url>`, Langfuse wiring. Remaining, and safe to run alongside Phase 2: P0-11 (bench labeling — human-only, in progress), P0-12/13 (eval harness + model bench — code landed, real runs and the model-pin decision still pending), P0-14 (census verdict + model choice → DESIGN §20 entries). Nothing in Phase 2 depends on these — the model pin and census verdict only affect `llm/config.py` and the tier-3 gate (they scope P3-14 at Phase 3 entry).

**Phase 1 (DESIGN.md §19) — exited 2026-07-10.** The spreadsheet is replaced: API + durable Postgres queue + in-process worker loop, Overview table, detail panel, rubric editor, overrides, fees checklist, Tasks Active tab, `confirm_value` checkpoints, Supabase Auth. Exit confirmed by Yusuf (P1-15): the real hunt is created and managed through the UI, listings submitted via the API path; spreadsheet retired.

**Phase 2 (DESIGN.md §19) — implementation complete through P2-8; exit acceptance in progress.** P2-9's automated Curator matrix is complete; its manual UI pass remains. P2-10 repository preparation is complete, but exit still requires the second real user workflow, two-browser Realtime check, and CI confirmation. Phase 3 readiness/dependency tables are prepared in IMPLEMENTATION §7; do not declare Phase 3 entered until Yusuf confirms the Phase 2 exit.

**Phase 3 (DESIGN.md §19) — Waves A/B running 2026-07-12 ahead of formal entry** (Yusuf-directed; Phase-0-tail precedent). Landed: P3-2 (planner v1 + manifest-driven runner + plan/cost persistence), P3-3 (tool registry with seam-enforced per-stage allow-lists, `call_agent` loop, `fetch_page`, Maps tools + geocode forever-cache), and P3-4 (DEDUPE between EXTRACT and VERIFY — zero tools, geocode as a plain call; `resolve_dedupe` checkpoint defaulting `keep_separate`; merge absorbs the submit-time placeholder Property at terminal projection; `manzil split-property` reverses a wrong merge and enqueues rescores — DESIGN §20 2026-07-12, IMPLEMENTATION §9 2.0.41). Plan: `.claude/plans/phase-3-agent-system.md`. Also landed 2026-07-12: the fetcher-layer SSRF guard (DESIGN §20; IMPLEMENTATION §9 2.0.40) — the HTTP path is closed with tier-1 IP-pinning. **Two smoke checks remain before P3-5/P3-10 wire Chromium into a live loop:** a manual browser smoke test of tier-2's route-guard/`page.url` backstop, and one live-HTTPS fetch confirming the pin's cert path (both unprovable under CI's mock transport).

Learning Track stays at L0 (Phase 0's eval harness) — L1 remains gated on Phase 0's exit per §19; L2's phase gate (Phase 1 exit) is now met, but the track proceeds in order (L1 first) and never blocks shipping. No agents-mode code yet.
