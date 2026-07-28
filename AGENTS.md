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
**Phase 3 (formally entered 2026-07-18) and the Phase 0 tail are running in parallel; Phases 1 and 2 are closed.** Full task tables: IMPLEMENTATION.md §7.

**Phase 0 (DESIGN.md §19) — closing out.** The pipeline spine (P0-1..P0-10) is done: `shared/` engine + catalog, migrations (global tables only), fetch tiers + outcome classifier + tier-3 free-plan stopgap, VALIDATE_URL → FETCH → VALIDATE → EXTRACT → VERIFY → SCORE, CLI `ingest <url>`, Langfuse wiring. Remaining, and safe to run alongside Phase 2: P0-11 (bench labeling — human-only, in progress at the trimmed 10-listing scope, DESIGN §20 2026-07-17), and P0-12/13/14 (eval harness + model bench + model pin — **all closed 2026-07-21, DESIGN §20**). **P0-14 fully ruled:** the census half (2026-07-17 — keep tier 3, Bright Data, free plan; Apify deferred; P3-14 retained) and now the model-pin half — EXTRACT/VERIFY pinned to `google/gemini-3-flash-preview` (`EXTRACT_VERIFY_MODEL`; the benched pair only, other workhorse stages + TASTE stay Anthropic); six unusable slugs pruned from `MODEL_PRICES`; the L0 harness fixed to grade checkpoint-flagged listings (accept-and-grade). The pin only affects `llm/config.py` and the re-keyed seed/e2e VERIFY replay fixtures (worker 451 + api 64 green). **Phase 0's decision gate is now fully closed** (P0-12/13 code had landed earlier; the remaining human task was P0-11 labeling).

**Phase 1 (DESIGN.md §19) — exited 2026-07-10.** The spreadsheet is replaced: API + durable Postgres queue + in-process worker loop, Overview table, detail panel, rubric editor, overrides, fees checklist, Tasks Active tab, `confirm_value` checkpoints, Supabase Auth. Exit confirmed by Yusuf (P1-15): the real hunt is created and managed through the UI, listings submitted via the API path; spreadsheet retired.

**Phase 2 (DESIGN.md §19) — exited 2026-07-18.** All tasks complete (P2-1..P2-9 and P2-11, incl. Managed Invitation Links); acceptance checks (manual Curator UI pass, real-partner workflow, two-browser Realtime) confirmed 2026-07-17; CI went green 2026-07-18 after committing the re-keyed seed EXTRACT replay recordings (+ a guard test pinning them git-tracked) and Yusuf recorded the sign-off (DESIGN §20 2026-07-18; IMPLEMENTATION 2.0.54–2.0.55). The one open follow-up is P2-12 (permission-aware UI: disable controls the viewer's role can't change instead of editable-then-error-on-save) — recorded, not started, not an exit condition.

**Phase 3 (DESIGN.md §19) — formally entered 2026-07-18.** Landed: P3-2 planner/manifest runner, P3-3 tool registry/Maps, P3-4 DEDUPE/reversal, **P3-5 DISCOVER** (2026-07-21, DESIGN v3.8 / IMPLEMENTATION 2.0.70: OpenRouter native search, exact same-Property candidate filtering, official link-only persistence, tier/family slate, editable Source Policy, reasoned single-source badge), **P3-SC2 scoped Extraction foundation** (2026-07-21, DESIGN v3.9 / IMPLEMENTATION 2.0.71: append-only candidate/resolved facts, Source-local Floor Plan identity, centralized current views/effective resolver, scoped Overrides, authoritative refresh and same-Property guards), **P3-SC3 Property Catalog/set-valued Rubric path** (2026-07-22, DESIGN v3.10 / IMPLEMENTATION 2.0.72: 13-Criterion Property tranche, strict `contains_any/all`, persisted Floor Plan unit types, separate Property/plan presentation, guarded versioned dev Rubric), **P3-SC4 engineering ✅⚠** (2026-07-27/28, DESIGN v3.15/v3.21: engineered scoped path landed; Owner waived the human canonical-ten/current-pin tail as a P3-6 prerequisite, and that evidence remains technical debt), **P3-6 multi-Source RECONCILE** (2026-07-28, DESIGN v3.21 / IMPLEMENTATION 2.0.83: per-Source fan-out/verification, family-deduped bounded official+sibling escalation, append-only candidate lineage, Source-local refresh retirement, split safety, dispute checkpoint and UI), the kitchen-first P3-7 VISION path (enabled by Owner overrides with outstanding classifier/quality evidence), **P3-SC5 Floor Plan detail + diagram substrate** (2026-07-28, IMPLEMENTATION §P3-SC5: drawer-scoped detail modal, scoped-amenity presentation with on-demand evidence, deterministic diagram classification, `webp-2048-q82-v1` profile fixed by the §7.5 legibility comparison, separate diagram budgets, alt-text association, Source-local retirement + `unlink` lifecycle, merge/split preservation, `manzil purge-images`, unmatched gallery — two items remain unevidenced: the partial item-7 visual pass and `full_size_url` on real pages), and **P3-19 map surfaces** (2026-07-26, DESIGN v3.14 / IMPLEMENTATION 2.0.77). P3-8 and P3-9 are landed ◐ with their live/bench follow-ups recorded in IMPLEMENTATION. The SSRF and Google Maps credential gates are cleared. P3-14 remains scoped to Bright Data's free plan and the five census-named hostile domains. Gemini 3 Flash Preview is Owner-pinned for P3-6 EXTRACT/VERIFY/plan-assist/equivalence; DISCOVER remains Haiku and VISION keeps its independent pin. Plan: `.claude/plans/phase-3-agent-system.md`. **Next eligible critical-path work: P3-SC6 or another Phase 3 task whose listed dependencies are satisfied.**

Learning Track stays at L0 (Phase 0's eval harness) — L1 remains gated on Phase 0's exit per §19; L2's phase gate (Phase 1 exit) is now met, but the track proceeds in order (L1 first) and never blocks shipping. No agents-mode code yet.
