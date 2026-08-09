# Manzil — Agent Instructions

Agentic apartment-hunting dashboard. Monorepo: `frontend/` (React + Vite + Mantine) · `api/` (FastAPI) · `worker/` (agent pipeline) · `shared/` (domain models + scoring engine) · `supabase/` (migrations, RLS) · `infra/`.

## graphify
- **graphify** (`.claude/skills/graphify/SKILL.md`) - any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).


## Before any task
1. Read `DESIGN.md` §1 (usage + reading paths) and §3 (glossary). Domain terms — Hunt, Property, Listing, Source, Floor Plan, Unit Group, Criterion, Rubric, Gate, Extraction, Override, Job, Stage, Checkpoint — have exact meanings. Use them verbatim in code; never invent synonyms.
2. Follow the §1 reading path for the area you are touching.
3. `DESIGN.md` is authoritative for design intent. If code or reality contradicts it, STOP and flag the conflict — never silently pick a side. (`IMPLEMENTATION.md`, once it exists, owns current mechanics and may churn freely; DESIGN.md still wins on intent.)

## The working tree is shared — never revert what you did not write

**More than one agent works in this checkout.** Codex sessions run here in parallel
(`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`, cwd is this repo), and the Owner
edits by hand. Modified files you did not create are therefore the normal case, not
a defect, and **the git status captured at the start of your session is a snapshot
that goes stale immediately** — "the tree was clean when I started" is never evidence
that a change is not someone's live work.

1. **Changes you did not make, you do not touch.** No `git checkout --`, `git stash`,
   `git restore`, `git clean`, or overwrite — however unrelated the change looks, and
   however much tidier it would make your own diff. Diff hygiene is not a reason; it is
   never worth someone else's work.
2. **Report and work around.** If unexpected modifications appear, say so plainly in
   your response, name the files, and continue your task around them. If they collide
   with your scope, ask.
3. **If reverting is genuinely necessary, ask first and show the diff.** State exactly
   which files, paste the diff, and wait. Do not infer a cause and act on it — a
   formatter, a hook, a stray command are all *hypotheses*. Verify: check
   `.claude/settings.json` / `settings.local.json` for hooks, and the Codex rollouts
   above for a concurrent agent. Sampling one file and generalising to sixty is how
   this rule got written.
4. **Recovery, when something is already lost.** Unstaged changes discarded by
   `git checkout --` are gone from git (`git fsck` only helps if they were ever
   staged). The real sources are the Codex rollouts, which carry full
   `*** Update File` patch bodies and can be replayed verbatim, then editor local
   history (`~/Library/Application Support/Cursor|Code/User/History`), then Time
   Machine.

*(2026-08-08: a repo-wide `ruff format .` from a live Codex session was mistaken for
hook noise and reverted wholesale; 59 files were pure formatting, three were not, and
`fetching/corpus.py` lost a real B006 mutable-default fix. Restored from the rollout.)*

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

### Local Site Admin bootstrap

Before testing the website through a browser, ensure the local Auth account
`admin@manzil.local` is a Site Admin. **Immediately after every `supabase db
reset`, do this before any other local UI work** — reset deletes the local Auth
user and the `site_admins` grant.

1. Start/check the local stack with `supabase start`, then check both the user
   and grant (do not assume either exists):
   ```bash
   supabase db query --local "select u.id, u.email, exists (select 1 from public.site_admins sa where sa.user_id = u.id) as is_site_admin from auth.users u where u.email = 'admin@manzil.local';"
   ```
2. If the user exists, use it. If `is_site_admin` is false, add the grant in
   step 4. Do **not** recreate the user or change its password.
3. If the user is absent, create the confirmed local-only account with password
   `local-dev-password`. Keep the service-role key in the shell; never print it,
   commit it, or expose it to the frontend:
   ```bash
   MANZIL_LOCAL_STATUS="$(supabase status -o json)"
   MANZIL_LOCAL_API_URL="$(printf '%s' "$MANZIL_LOCAL_STATUS" | jq -er '.API_URL')"
   MANZIL_LOCAL_SERVICE_ROLE_KEY="$(printf '%s' "$MANZIL_LOCAL_STATUS" | jq -er '.SERVICE_ROLE_KEY')"
   curl --fail --silent --show-error -X POST "$MANZIL_LOCAL_API_URL/auth/v1/admin/users" \
     -H "apikey: $MANZIL_LOCAL_SERVICE_ROLE_KEY" \
     -H "Authorization: Bearer $MANZIL_LOCAL_SERVICE_ROLE_KEY" \
     -H 'Content-Type: application/json' \
     --data '{"email":"admin@manzil.local","password":"local-dev-password","email_confirm":true}' >/dev/null
   ```
4. Ensure the account has a Site Admin grant. On a fresh reset it becomes the
   immutable primordial admin; otherwise it is an ordinary additional admin:
   ```bash
   supabase db query --local "insert into public.site_admins (user_id, is_primordial, note) select u.id, not exists (select 1 from public.site_admins), 'Local development bootstrap admin' from auth.users u where u.email = 'admin@manzil.local' on conflict (user_id) do nothing;"
   ```

Sign into the local app as `admin@manzil.local` / `local-dev-password`. This is
local-development bootstrap only; production account provisioning must use the
audited Site Admin path (PR-1).

## Current phase
**Phase 3 (formally entered 2026-07-18) and the Phase 0 tail are running in parallel; Phases 1 and 2 are closed.** Full task tables: IMPLEMENTATION.md §7.

**Phase 0 (DESIGN.md §19) — closing out.** The pipeline spine (P0-1..P0-10) is done: `shared/` engine + catalog, migrations (global tables only), fetch tiers + outcome classifier + tier-3 free-plan stopgap, VALIDATE_URL → FETCH → VALIDATE → EXTRACT → VERIFY → SCORE, CLI `ingest <url>`, Langfuse wiring. Remaining, and safe to run alongside Phase 2: P0-11 (bench labeling — human-only, in progress at the trimmed 10-listing scope, DESIGN §20 2026-07-17), and P0-12/13/14 (eval harness + model bench + model pin — **all closed 2026-07-21, DESIGN §20**). **P0-14 fully ruled:** the census half (2026-07-17 — keep tier 3, Bright Data, free plan; Apify deferred; P3-14 retained) and now the model-pin half — EXTRACT/VERIFY pinned to `google/gemini-3-flash-preview` (`EXTRACT_VERIFY_MODEL`; the benched pair only, other workhorse stages + TASTE stayed Anthropic at the time — the **whole workhorse tier moved to that slug on 2026-07-28, DESIGN §20 v3.23**, with DISCOVER and TASTE still exempt); six unusable slugs pruned from `MODEL_PRICES`; the L0 harness fixed to grade checkpoint-flagged listings (accept-and-grade). The pin only affects `llm/config.py` and the re-keyed seed/e2e VERIFY replay fixtures (worker 451 + api 64 green). **Phase 0's decision gate is now fully closed** (P0-12/13 code had landed earlier; the remaining human task was P0-11 labeling).

**Phase 1 (DESIGN.md §19) — exited 2026-07-10.** The spreadsheet is replaced: API + durable Postgres queue + in-process worker loop, Overview table, detail panel, rubric editor, overrides, fees checklist, Tasks Active tab, `confirm_value` checkpoints, Supabase Auth. Exit confirmed by Yusuf (P1-15): the real hunt is created and managed through the UI, listings submitted via the API path; spreadsheet retired.

**Phase 2 (DESIGN.md §19) — exited 2026-07-18.** All tasks complete (P2-1..P2-9 and P2-11, incl. Managed Invitation Links); acceptance checks (manual Curator UI pass, real-partner workflow, two-browser Realtime) confirmed 2026-07-17; CI went green 2026-07-18 after committing the re-keyed seed EXTRACT replay recordings (+ a guard test pinning them git-tracked) and Yusuf recorded the sign-off (DESIGN §20 2026-07-18; IMPLEMENTATION 2.0.54–2.0.55). The one open follow-up is P2-12 (permission-aware UI: disable controls the viewer's role can't change instead of editable-then-error-on-save) — recorded, not started, not an exit condition.

**Phase 3 (DESIGN.md §19) — formally entered 2026-07-18.** Landed: P3-2 planner/manifest runner, P3-3 tool registry/Maps, P3-4 DEDUPE/reversal, **P3-5 DISCOVER** (2026-07-21, DESIGN v3.8 / IMPLEMENTATION 2.0.70: OpenRouter native search, exact same-Property candidate filtering, official link-only persistence, tier/family slate, editable Source Policy, reasoned single-source badge), **P3-SC2 scoped Extraction foundation** (2026-07-21, DESIGN v3.9 / IMPLEMENTATION 2.0.71: append-only candidate/resolved facts, Source-local Floor Plan identity, centralized current views/effective resolver, scoped Overrides, authoritative refresh and same-Property guards), **P3-SC3 Property Catalog/set-valued Rubric path** (2026-07-22, DESIGN v3.10 / IMPLEMENTATION 2.0.72: 13-Criterion Property tranche, strict `contains_any/all`, persisted Floor Plan unit types, separate Property/plan presentation, guarded versioned dev Rubric), **P3-SC4 engineering ✅⚠** (2026-07-27/28, DESIGN v3.15/v3.21: engineered scoped path landed; Owner waived the human canonical-ten/current-pin tail as a P3-6 prerequisite, and that evidence remains technical debt), **P3-6 multi-Source RECONCILE** (2026-07-28, DESIGN v3.21 / IMPLEMENTATION 2.0.83: per-Source fan-out/verification, family-deduped bounded official+sibling escalation, append-only candidate lineage, Source-local refresh retirement, split safety, dispute checkpoint and UI), the kitchen-first P3-7 VISION path (enabled by Owner overrides with outstanding classifier/quality evidence), **P3-SC5 Floor Plan detail + diagram substrate** (2026-07-28, IMPLEMENTATION §P3-SC5: drawer-scoped detail modal, scoped-amenity presentation with on-demand evidence, deterministic diagram classification, `webp-2048-q82-v1` profile fixed by the §7.5 legibility comparison, separate diagram budgets, alt-text association, Source-local retirement + `unlink` lifecycle, merge/split preservation, `manzil purge-images`, unmatched gallery — two items remain unevidenced: the partial item-7 visual pass and `full_size_url` on real pages), **P3-8 ENRICH ✅** (Detroit-metro live acceptance completed 2026-08-02), **P3-10 custom Criteria ✅** (live test accepted 2026-08-02; no dedicated programmatic test), **P3-12 deterministic refresh** (2026-07-30, DESIGN v3.31 / IMPLEMENTATION 2.0.92: exact TTL classes, contributing-Slate Planner, hash gating, scheduler, refresh API/RLS, stale UI), **P3-13 compare/mobile ✅** (mobile exploratory acceptance completed 2026-08-02), **P3-14 Tier-3 ✅** (all five census-named domains confirmed 2026-08-02), and **P3-19 map surfaces** (2026-07-26, DESIGN v3.14 / IMPLEMENTATION 2.0.77). P3-9 is landed ◐ with its owed bench rerun recorded in IMPLEMENTATION. The SSRF and Google Maps credential gates are cleared. Before production, **PR-1** must restrict account provisioning to Site Admins, disable public registration, and block magic-link/OTP account creation. Gemini 3 Flash Preview is Owner-pinned for P3-6 EXTRACT/VERIFY/plan-assist/equivalence; DISCOVER remains Haiku and VISION keeps its independent pin. Plan: `.claude/plans/phase-3-agent-system.md`. **Next eligible critical-path work: PR-1 or another Phase 3 task whose listed dependencies are satisfied.**

**Visits workstream (`VC-0`…`VC-8`) — entered 2026-07-30, parallel to Phase 3, gating nothing.** The Visit Checklist (DESIGN §9.7): a tour of a Property recorded collaboratively on a phone and read on desktop. It has **no pipeline and, in v1, no LLM surface** — API + DB + frontend only (deferred voice-note transcription would end that; §18) — and is deliberately *not* numbered into Phase 3, so it is not a Phase 3 exit condition. **VC-0 (design ratification) landed 2026-07-30**: DESIGN v3.30 (§3 glossary, §4.2 roles, §8.2–§8.3, new §9.7, §13.1–§13.3, §18, §19, §20) and IMPLEMENTATION 2.0.91 (§3 Visit Checklist contract, §7 `VC` table). **VC-1 (foundations) landed 2026-07-30** (IMPLEMENTATION 2.0.93): migration `20260817000000_visits.sql` (four tables, three guard helpers, the `visits_enforce_update_rules` trigger, RLS, Realtime) and `api/src/manzil_api/visits/` with the 248-item template as generated-and-parity-tested seed. **VC-2 (Visits tab) landed 2026-07-30** (IMPLEMENTATION 2.0.94): `features/visits/` with the three routes, the nav item, the four-state list, the create flow, and the prep-only pre-visit page. **VC-3 (checklist runtime) landed 2026-07-30** (IMPLEMENTATION 2.0.96): migration `20260819000000_visit_entries.sql` — append-only `visit_entries`, the `current_visit_entries` view, and the `visit_entries_enforce_shape` trigger that refuses a mis-scoped or mis-owned answer — plus the batched `PUT /v1/visits/{id}/entries` and the four entry-kind controls with the tier dial, unit switcher and scope bar. **VC-4 (defect log) landed 2026-07-30** (IMPLEMENTATION 2.0.97): `visit_defects` with Check→Defect promotion inside `save_entries`, once-only per `(visit, item, unit)` via a partial unique index, soft delete that leaves the Check's answer alone, and the per-member red-flag tally. **VC-5 (collaboration) landed 2026-07-30** (2.0.98): five visit tables wired into `realtime.ts`, plus the app's first **Presence** channel — one ref-counted channel per Visit; note that `track()` appends a presence meta and `untrack()` removes only one, so a section change must untrack before re-tracking or the member never leaves. **VC-6 (local-first) landed 2026-07-30** (2.0.99): TanStack paused-mutation persistence with the mutation function on the query client (a restored write has no closure), optimistic answers marked `optimistic:` and never usable as a `prev_entry_id`, the sync badge, and `visit_entry_conflicts` — a fork is rows sharing a parent **whose answers differ**, resolved by an ordinary answer descending from the chosen branch. **VC-7 (money) landed 2026-07-30** (2.0.100): `visit_fee_proposals`; accepting **delegates** to `fees.upsert_fee` / `overrides.create_override` so the row is indistinguishable from a manual drawer edit (`manual` provenance, base rent scoped to the walked unit's Floor Plan), rejecting writes only the decision. **VC-8 (surfacing) landed 2026-07-30** (2.0.101): `visit_unit_group_scores` holds all four roll-up rules — per-member-then-across averaging, latest tour per door, best door per group, and no row for a unit whose Unit Group the Property does not advertise. **The workstream is complete (VC-0…VC-8).** Deferred to a *Visits phase 2* (§18): photos, **voice notes + transcription** (the first LLM surface Visits would have, and the first time a member's voice leaves the app — it also needs a ruling on whether a recording can satisfy the Question gate, which §9.7 currently answers only for typed text), Rubric-derived checklist items, hunt-wide recurring custom items. Key invariants a contributor must not break: visit state is **derived from timestamps**, never stored; `visit_units` are human-typed **labels** that leave §18's individual-unit-inventory deferral intact; entries are **append-only** with current value via `current_visit_entries`; conflicts are **surfaced, never auto-resolved**; a Visit **never** feeds the scoring engine. Plan: `.claude/plans/visit-checklist.md`.

Learning Track stays at L0 (Phase 0's eval harness) — L1 remains gated on Phase 0's exit per §19; L2's phase gate (Phase 1 exit) is now met, but the track proceeds in order (L1 first) and never blocks shipping. No agents-mode code yet.
