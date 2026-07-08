# Manzil — Design Document

> **Codename:** Manzil (منزل — dwelling; in classical usage also a stage of a journey). Whether it doubles as the public product name is an open question ([§21](#21-open-questions)).

| | |
|---|---|
| **Version** | 2.8 |
| **Status** | Living document — this is the source of truth during implementation |
| **Supersedes** | `apartment-hunt-dashboard-design.md` draft v0.4 |
| **Owner** | Yusuf |
| **Repo location** | `/DESIGN.md` (monorepo root) |

---

## Table of Contents

- [Manzil — Design Document](#manzil--design-document)
  - [Table of Contents](#table-of-contents)
  - [1. Purpose and Usage](#1-purpose-and-usage)
  - [2. Product Overview](#2-product-overview)
    - [2.1 Problem](#21-problem)
    - [2.2 Solution](#22-solution)
    - [2.3 Goals](#23-goals)
    - [2.4 Non-Goals](#24-non-goals)
    - [2.5 Learning Objectives](#25-learning-objectives)
  - [3. Glossary and Domain Model](#3-glossary-and-domain-model)
  - [4. Requirements](#4-requirements)
    - [4.1 Functional](#41-functional)
    - [4.2 Roles and Permissions](#42-roles-and-permissions)
    - [4.3 Non-Functional](#43-non-functional)
  - [5. System Architecture](#5-system-architecture)
    - [5.1 API Surface](#51-api-surface)
  - [6. Monorepo Layout](#6-monorepo-layout)
  - [7. Technology Stack](#7-technology-stack)
  - [8. Database Design](#8-database-design)
    - [8.1 Enums](#81-enums)
    - [8.2 Tables](#82-tables)
    - [8.3 RLS Strategy](#83-rls-strategy)
  - [9. Business Logic](#9-business-logic)
    - [9.1 Hunts, Membership, Invites](#91-hunts-membership-invites)
    - [9.2 Rubric System](#92-rubric-system)
    - [9.3 Scoring Engine](#93-scoring-engine)
    - [9.4 Floor Plans and Unit Groups](#94-floor-plans-and-unit-groups)
    - [9.5 Utilities and All-In Monthly Cost](#95-utilities-and-all-in-monthly-cost)
    - [9.6 Overrides and Provenance](#96-overrides-and-provenance)
  - [10. Agent Pipeline](#10-agent-pipeline)
    - [10.1 Job Lifecycle](#101-job-lifecycle)
    - [10.2 Implementation Patterns](#102-implementation-patterns)
    - [10.3 Stage Catalog](#103-stage-catalog)
    - [10.4 Planner](#104-planner)
    - [10.5 Verification Agent](#105-verification-agent)
    - [10.6 Conflict Resolution](#106-conflict-resolution)
    - [10.7 Fetching Subsystem](#107-fetching-subsystem)
    - [10.8 Vision](#108-vision)
    - [10.9 Custom Criteria Routing](#109-custom-criteria-routing)
    - [10.10 User Checkpoints](#1010-user-checkpoints)
    - [10.11 Agents Mode (Learning Track)](#1011-agents-mode-learning-track)
  - [11. LLM Strategy](#11-llm-strategy)
    - [11.1 Provider Seam](#111-provider-seam)
    - [11.2 Model Roles and Candidates](#112-model-roles-and-candidates)
    - [11.3 Cross-Cutting Techniques](#113-cross-cutting-techniques)
  - [12. External Integrations](#12-external-integrations)
  - [13. Frontend Design](#13-frontend-design)
    - [13.1 Routes](#131-routes)
    - [13.2 Key Views (Mantine mapping)](#132-key-views-mantine-mapping)
    - [13.3 Realtime](#133-realtime)
  - [14. Caching and Refresh Strategy](#14-caching-and-refresh-strategy)
  - [15. Cost Model and Optimization](#15-cost-model-and-optimization)
  - [16. Security and Privacy](#16-security-and-privacy)
  - [17. Risks and Concerns Register](#17-risks-and-concerns-register)
  - [18. Deferred Features and Backlog](#18-deferred-features-and-backlog)
  - [19. Implementation Phases](#19-implementation-phases)
  - [20. Decision Log](#20-decision-log)
  - [21. Open Questions](#21-open-questions)

---

## 1. Purpose and Usage

This document describes the design intent, architecture, and business logic of Manzil: a collaborative, agent-powered apartment-hunting dashboard for a small group of users. It is written for two audiences with equal weight:

**For the human (Yusuf):** the reference for every architectural decision, its rationale, and the trade-offs accepted. When implementation reality contradicts this document, update the document — that is what "living" means.

**For coding agents:** this document is authoritative context. When implementing any feature, read the relevant section *and* the [Glossary](#3-glossary-and-domain-model) first; domain terms (Hunt, Property, Listing, Criterion, Checkpoint) have precise meanings and the code must use them consistently. Do not invent alternative names for concepts defined here. Do not implement anything listed in [Deferred Features](#18-deferred-features-and-backlog) unless explicitly asked. When a design detail is ambiguous or missing, stop and ask rather than guessing — then the answer gets recorded here.

**Reading paths** (read §3 first in every case): implementing the schema → §8, §9; the scoring engine → §3, §9.3, §9.4; a pipeline stage → §10.1, that stage's subsection, §11.3; the frontend → §4.2, §13, §8.2 (the tables you subscribe to); anything cost-sensitive → §15 before writing a prompt.

**Update protocol:** material design changes append an entry to the [Decision Log](#20-decision-log) (date, decision, rationale, sections touched) and update the affected sections in place. Never let the log and the body disagree; the body wins for "what is," the log wins for "why it changed." Implementation mechanics — interfaces, tunables, work plans, runbooks — live in the sibling `IMPLEMENTATION.md`, which churns freely without this ceremony; the authority order is DESIGN (intent) > IMPLEMENTATION (mechanics) > code (exact interfaces).

---

## 2. Product Overview

### 2.1 Problem

Rental listing sites are hostile to comparison: fees hide behind "contact us," identical units appear at different prices across sites, and the true all-in monthly cost is never the headline number. The current workflow — a hand-maintained spreadsheet, one row per listing — is tedious to bootstrap, tedious to maintain, and silently goes stale.

### 2.2 Solution

Paste a listing URL. An agent pipeline validates it, deduplicates it against known properties, finds sibling sources, extracts structured details, verifies them against the page evidence, reconciles conflicts across sources, assesses photos, enriches with location and utility-cost data, and scores the result against a rubric the hunt owner fully controls. Everything lands in a live, shared table with provenance on every value.

### 2.3 Goals

1. One-click ingestion: URL in, fully populated and scored row out, within minutes.
2. Deterministic, transparent, user-controlled scoring — the LLM produces facts; only the rubric produces points.
3. Small-group collaboration: shared hunts, roles, comments, ratings, realtime sync.
4. Data honesty: provenance and confidence on every value; estimates visually distinct from facts; overrides preserve originals; the tool never makes an apartment look cheaper than a worst realistic month.

### 2.4 Non-Goals

- Not a search engine — it evaluates URLs users bring; no automated listing discovery or alerts (backlog, [§18](#18-deferred-features-and-backlog)).
- No native mobile app; responsive web only.
- No multi-tenant SaaS hardening, billing, or public availability. Personal tool for a small circle — this posture also bounds the scraping risk ([§17](#17-risks-and-concerns-register)).

### 2.5 Learning Objectives

Manzil is deliberately dual-purpose: a real tool with real users on a real deadline (the apartment hunt), and a vehicle for learning multi-agent architectures by building them against a genuine problem rather than a toy. For a learning project, overkill is not a bug — it is the assignment; the "don't build multi-agent unless justified" rule is shipping advice, deliberately suspended *off* the critical path. The reconciliation is one governing principle, applied everywhere it matters:

> **The critical path stays boring; the ambition lives where failure is survivable.** A listing that scores late is fine; a listing that scores *wrong silently* is not.

Concretely: the shipping pipeline is the workflow-mode baseline ([§10.2](#102-implementation-patterns)); the multi-agent architectures live in an isolated, flag-gated agents mode ([§10.11](#1011-agents-mode-learning-track)); and every learning claim is settled empirically by the dual-mode eval harness, not by faith in either direction. The deliverable of the learning track is *earned judgment* — knowing what multi-agent buys and costs on a real task, with data.

---

## 3. Glossary and Domain Model

Precise terms. Code, schema, API routes, and UI copy must use these consistently.

| Term | Definition |
|---|---|
| **Hunt** | A named apartment search (e.g., "Apartment Search 2026") owning a rubric, members, and a set of listings. The top-level collaboration container. |
| **Property** | A canonical, globally shared apartment complex/building — deduplicated by address + name. Extracted facts attach to properties, not hunts. |
| **Listing** (`hunt_listing`) | The association of a Property with a Hunt. Scores, overrides, comments, ratings, pins, and the fees checklist live here. |
| **Source** (`property_source`) | One known listing page (URL) for a Property on a specific site. Official complex sites are flagged `is_official`. |
| **Floor Plan** | One distinct unit layout at a Property (from one source): beds, baths, sqft range, rent range, availability. |
| **Unit Group** | The derived grouping of a Property's floor plans by (beds, baths). One table row per unit group. Not a stored entity. |
| **Criterion** | One scoreable dimension (e.g., in-unit laundry). Predefined criteria live in the `criteria_catalog`; hunts may add custom criteria. |
| **Rubric** | A hunt's enabled criteria with their options, point deltas, unknown-deltas, and gate flags. Versioned per hunt. |
| **Gate** | A dealbreaker (option-level: if matched, score is SET) or non-negotiable (criterion-level: if no acceptable option matched, score is SET). An option is *acceptable* when its `delta ≥ 0` and it is not itself a dealbreaker option; an unknown value never satisfies a non-negotiable — missing data cannot pass a gate. |
| **Extraction** | One agent-derived fact: (property, criterion) → value + confidence + evidence + source + model + timestamp. |
| **Override** | A per-listing human-supplied value that displays instead of an extraction without destroying it. |
| **Job** | One pipeline run (ingest / refresh / rescore) for a listing. The `jobs` table is simultaneously the queue, the state store, and the task-history record. |
| **Stage** | One step of the pipeline state machine (PLAN, VALIDATE, …). Stages are idempotent and resumable. |
| **Checkpoint** | A pipeline pause (`WAITING_USER`) presenting a structured question to the submitter, a Curator, or the Owner. Typed by `kind`: `confirm_value`, `resolve_dedupe`, `resolve_dispute`. Auto-resumes with a declared default after 24h. There is no separate "needs review" state — human review *is* a checkpoint. |
| **Adapter Registry** | Per-domain record of which fetch tier a site requires and its settings. |
| **Source Policy** | A per-submission constraint on cross-checking (defaulted from hunt settings): whether DISCOVER runs at all and how high the fetch ladder may climb for *discovered sibling sources*. One of `trust_link`, `tier_1`, `tiers_1_2`, `tiers_1_2_3` (default), `tier_1_plus_official`. Never constrains the submitted URL itself ([§10.7](#107-fetching-subsystem)). |
| **Baseline** | A cached metro-level median/peak utility cost used when a utility is not included in rent. |

Ownership chain: `Hunt → hunt_listings → Property → (sources, floor_plans, extractions, images)`. Global facts flow left-to-right; per-hunt opinion (scores, overrides, comments) never leaves the Listing.

---

## 4. Requirements

### 4.1 Functional

- **FR1 — Hunts:** create/rename/archive; a Property may appear in multiple Hunts; extracted data is shared globally, everything opinionated is per-hunt.
- **FR2 — Rubric:** guided builder, skippable but required before first submission. Owner-edited, member-viewable (read-only rubric page). Toggle catalog criteria, edit deltas, per-criterion unknown-delta, custom criteria, dealbreakers, non-negotiables. Edits bump `rubric_version` and trigger a free re-score of all listings.
- **FR3 — Ingestion:** submit URL → pipeline per [§10](#10-agent-pipeline). Each submission carries a **Source Policy** ([§10.7](#107-fetching-subsystem)) — defaulting to full cross-check — controlling whether sibling sources are discovered and how high the fetch ladder may climb for them. Progress visible live; jobs cancellable by their submitter or the Owner.
- **FR4 — Utilities intelligence:** determine included utilities; estimate excluded ones from winter-weighted metro baselines; compose all-in monthly cost with actual/estimated/unknown tagging ([§9.5](#95-utilities-and-all-in-monthly-cost)).
- **FR5 — Table and detail:** sortable/filterable table, one row per Unit Group, detail panel (slide-up sheet on mobile) with full breakdown, evidence, images, floor plans, sources, comments, ratings.
- **FR6 — Collaboration:** email + link invites, per-user colors, realtime sync, comments, ratings.
- **FR7 — Overrides:** any extracted value overrideable per role matrix below; original value + provenance preserved and viewable; override badge in UI.
- **FR8 — Refresh:** per-listing and hunt-wide refresh re-running only stale data classes ([§14](#14-caching-and-refresh-strategy)); field-scoped partial refresh.
- **FR9 — Compare:** 2–4 listings side-by-side at criterion granularity.
- **FR10 — Task history:** the Tasks view shows Active and History tabs. Every past job is retained and inspectable: plan manifest, per-stage timeline with outcomes, checkpoint Q&A (including auto-resolutions), errors, and actual LLM cost per run.
- **FR11 — Dual-mode pipeline + eval harness:** the pipeline runs as `--mode=workflow` (baseline, ships) or `--mode=agents` ([§10.11](#1011-agents-mode-learning-track)); both share the RunState/persistence contract and the deterministic truth layer. An eval harness runs both modes against the bench set and reports accuracy (verification pass-rate, gate-criterion correctness), tokens, and latency.
- **FR12 — Property investigation (agents mode, off critical path):** an on-demand "Investigate this property" action producing a structured brief — reviews and management reputation, scam signals and cross-listing price checks, area context — via a spawnable worker crew. Slow, costly, or occasionally dumb is acceptable here by design; nothing downstream depends on it.

### 4.2 Roles and Permissions

Three roles per hunt. The middle role is named **Curator** — chosen over "Editor" precisely because of the ambiguity Yusuf flagged: *every* member can submit and edit their own contributions; what the middle role adds is stewardship over the *data quality* of the whole hunt. Curator says exactly that. (Rejected: Editor — implies members can't edit anything; Moderator — implies people-management, which stays with the Owner.)

Enforced via Supabase RLS at the database layer, mirrored by API checks. Never frontend-only.

| Action | Owner | Curator | Member |
|---|---|---|---|
| Edit rubric | yes | — | — |
| Edit hunt settings ([§8.2](#82-tables)) | yes | — | — |
| View rubric | yes | yes | yes |
| Add listing / submit URL | yes | yes | yes |
| Manage (cancel/retry/reorder) **own** jobs | yes | yes | yes |
| Manage **anyone's** jobs and listings | yes | — | — |
| Resolve checkpoints | any listing | any listing | own listings |
| Overrides + fees-checklist entries | any listing | any listing | own listings |
| View task history | yes | yes | yes |
| Comments, ratings, own color | yes | yes | yes |
| Invites, remove members, change roles, delete listings, archive hunt | yes | — | — |

### 4.3 Non-Functional

- **NFR1 — Cost:** <$0.15 LLM+API per new listing, <$0.01 per refresh, $0 per re-score ([§15](#15-cost-model-and-optimization)).
- **NFR2 — Latency:** ingestion async; target <3 min single-source submit-to-score; UI via realtime events, no polling.
- **NFR3 — Resumability:** every stage idempotent; failed stages retry with backoff; completed stages never re-run on resume; deploys/restarts must not lose jobs (queue is durable in Postgres).
- **NFR4 — Provenance:** every stored fact carries source, timestamp, model, confidence, and (post-reconciliation) the resolution rule that selected it.
- **NFR5 — Simplicity:** boring infrastructure *on the critical path*; the Postgres instance is the database, the queue, the realtime bus, and the auth store. New moving parts require a decision-log entry justifying them (the learning track's two — LangGraph, Langfuse — are justified in [§10.11](#1011-agents-mode-learning-track) and gated by [§19](#19-implementation-phases)).
- **NFR6 — Observability:** every LLM call in **both modes** is traced (Langfuse) with stage, mode, model, tokens, and cost, wired before the first agent call and non-negotiable thereafter. Multi-agent debugging without traces is the canonical failure mode — and the debugging itself is curriculum.

---

## 5. System Architecture

```
┌──────────────┐      ┌───────────────────┐      ┌─────────────────────┐
│  Frontend     │─────▶│  API (FastAPI)     │─────▶│  Supabase            │
│  React+Mantine│◀─────│  Render service    │      │  Postgres · Auth ·   │
│  CF Pages     │      └──────┬────────────┘      │  Storage · Realtime  │
│      ▲        │             │ INSERT job         └──────────┬──────────┘
│      └────────┼── realtime subscriptions ◀─────────────────┘
└──────────────┘             ▼
                      ┌───────────────────┐
                      │  Worker (Render)   │  polls jobs (FOR UPDATE SKIP LOCKED)
                      │  pipeline runner   │──▶ LLM APIs (extract/verify/vision)
                      │  + Playwright      │──▶ fetch tiers (§10.6)
                      └───────────────────┘──▶ Google Maps Platform
```

**Data flow, narrated once:** the frontend authenticates against Supabase Auth and calls the API with the JWT. Mutations (submit URL, edit rubric, override) go through the API, which validates, writes, and — for pipeline work — inserts a `jobs` row. The worker claims jobs from Postgres, executes the stage machine, and writes results (extractions, scores, job_events) back to Postgres. The frontend hears every change through Realtime subscriptions on the tables it renders — the worker never talks to the frontend directly and the API never blocks on pipeline work.

**Role of FastAPI background tasks:** used for *lightweight, post-response* work only — dispatching invite emails, firing a re-score after a rubric save, cleanup chores. Pipeline runs are explicitly **not** background tasks: they are minutes long, memory-heavy (Playwright), must survive deploys, and need retry semantics — all properties `BackgroundTasks` lacks and the durable Postgres queue provides. The API's job in ingestion is one `INSERT`; the worker does the rest.

### 5.1 API Surface

REST, resource-oriented, versioned under `/v1`. The contract is intentionally boring so it need not be specified route-by-route — a coding agent should derive it from these conventions plus the [schema](#8-database-design), and any endpoint that can't be derived this way earns a line here first:

| Resource | Routes | Notes |
|---|---|---|
| Hunts | CRUD `/hunts`, `/hunts/{id}` | archive = PATCH status; `settings` edits (Owner-only) validated against the [§8.2](#82-tables) settings contract, with the per-key edit effects specified there (rescore / location refresh / nothing) |
| Members / invites | `/hunts/{id}/members`, `/hunts/{id}/invites`, `POST /invites/{token}/accept` | role changes Owner-only |
| Rubric | `GET/PUT /hunts/{id}/rubric` | PUT validates against `value_schema`, bumps version, enqueues rescore |
| Listings | `POST /hunts/{id}/listings` (body: URL + optional `source_policy`, defaulted from hunt settings) → creates listing + ingest job; `GET`, `DELETE` | Source Policy per [§10.7](#107-fetching-subsystem) |
| Overrides / fees / comments / ratings | nested under `/listings/{id}/…` | permissions per [§4.2](#42-roles-and-permissions) |
| Jobs | `GET /hunts/{id}/jobs?state=…`, `POST /jobs/{id}/cancel|retry`, `POST /jobs/{id}/checkpoint` (answer) | reads also served by Realtime |
| Refresh | `POST /listings/{id}/refresh`, `POST /hunts/{id}/refresh` (optional `fields`) | inserts refresh jobs |

Reads that the table renders continuously (listings, scores) go straight from the frontend to Supabase (RLS-guarded selects + Realtime); the API exists for validated mutations and anything requiring the service role.

**Scheduling.** Three duties recur on timers: TTL-driven refresh scans ([§14](#14-caching-and-refresh-strategy)), the 24 h checkpoint-timeout sweep ([§10.10](#1010-user-checkpoints)), and the 120 d utility-baseline job ([§9.5](#95-utilities-and-all-in-monthly-cost)). All three are owned by a **scheduler tick inside the worker's main loop** (every ~5 min: run three SQL queries, insert due jobs / flip timed-out checkpoints to their defaults). No cron service, no scheduler infrastructure — the duties are just rows becoming due, which Postgres answers directly (NFR5). If the worker is down, ticks are missed and caught up on restart; nothing here is time-critical at minute granularity.

**Worker deployment options:** (a) *recommended* — separate Render background worker (~$7/mo), isolating Playwright memory and pipeline latency from the API; (b) *budget option for Phase 1* — an asyncio worker loop started in the API process via FastAPI lifespan. Option (b) is tolerable early precisely because NFR3 makes interrupted jobs resume cleanly after a restart — but move to (a) before Playwright enters the picture (Phase 3), since browser memory spikes inside the API process are how you get mystery 502s.

---

## 6. Monorepo Layout

```
manzil/
├── DESIGN.md                    # this document — intent, contracts, decisions
├── IMPLEMENTATION.md            # current mechanics — interfaces, tunables, work plans, runbooks
├── CLAUDE.md                    # agent instructions (AGENTS.md symlinks to it)
├── pyproject.toml               # uv workspace root: members = shared, api, worker
├── uv.lock                      # single lockfile, root only
├── .python-version              # 3.12
│
├── shared/                      # domain-blind, LLM-free (CLAUDE.md hard rules)
│   ├── pyproject.toml           # manzil-shared
│   ├── src/manzil_shared/
│   │   ├── models.py            # Pydantic domain models — §3 terms, verbatim
│   │   ├── catalog.py           # criteria catalog seed (generates supabase/seed.sql)
│   │   └── scoring/
│   │       ├── engine.py        # pure score() → breakdown (§9.3 contract)
│   │       └── composition.py   # cost composer behind an interface (§18 buy-domain seam)
│   └── tests/golden/            # exact-breakdown assertions
│
├── worker/
│   ├── pyproject.toml           # depends on manzil-shared { workspace = true }
│   ├── src/manzil_worker/
│   │   ├── cli.py               # Phase 0 entry: `manzil ingest <url>`
│   │   ├── runner.py            # run_job — persist-before-advance (§10.2)
│   │   ├── state.py             # RunState
│   │   ├── stages/              # one module per §10.3 stage
│   │   ├── fetching/            # tiers, outcome classifier, cleaner, adapter registry (§10.7)
│   │   ├── agents/              # agents mode ONLY (§10.11): LangGraph graph, orchestrator,
│   │   │                        #   critic, triage router, investigator crew
│   │   ├── llm/                 # client.py = the seam (§11.1); config.py = model pins
│   │   └── schemas.py           # dynamic extraction model from catalog (§10.2 P1)
│   ├── tests/fixtures/
│   │   ├── corpus/              # 50+ saved real listing pages (local eval asset — gitignored, §20 v2.8)
│   │   ├── bench/               # stratified ~20: labels/ local (gitignored) + manifest.md tracked
│   │   └── recorded/            # captured LLM responses — smoke fixture tracked for CI replay; the rest local
│   └── evals/                   # dual-mode harness + written reports (FR11, §19 Learning Track)
│
├── api/                         # near-empty until Phase 1 (health route only)
│   └── src/manzil_api/
├── frontend/                    # Vite scaffold; untouched until Phase 1
├── supabase/
│   ├── migrations/              # 0001: global tables only (Phase 0 scope)
│   └── seed.sql                 # generated FROM shared/catalog.py — never edited by hand
├── infra/                       # render.yaml, .env.example
└── docs/adr/                    # rationale too detailed for §20
```

**Testing strategy:** the scoring engine gets exhaustive golden tests in `shared/` (rubric + values in, exact breakdown out — this is the component where a silent regression does the most damage); pipeline stages get unit tests against recorded fixtures (saved cleaned text + canned LLM responses; no live LLM calls in CI); tier-detection heuristics get committed synthetic signal pages plus a local (gitignored, [§20](#20-decision-log) v2.8) corpus of real pages collected during Phase 0 — the corpus sweep skips cleanly where the corpus is absent; RLS policies get integration tests that attempt every forbidden action per role (Phase 2 exit criterion); LLM prompt changes are validated by re-running the Phase 0 bench set, not by eyeballing.

Conventions: the **scoring engine and Pydantic domain models live in `shared/`** and are imported by both services — a scoring result must be identical whether computed during a pipeline run or a rubric-edit re-score. Python tooling: `uv` **workspace** rooted at `/`: a single shared `uv.lock` and one venv; `shared/`, `api/`, `worker/` are workspace members, with `api` and `worker` depending on `shared` via `[tool.uv.sources] shared = { workspace = true }`. Run `uv sync` at root; target a member with `uv run --package <name>`. `ruff` for lint/format, `pytest`. Frontend: `pnpm`, `eslint`, `vitest`.

---

## 7. Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| Frontend framework | React 18 + Vite + TypeScript | SPA is sufficient (no SEO need); Vite for iteration speed |
| UI library | **Mantine** (+ `@mantine/hooks`, `mantine-react-table` or Mantine + TanStack Table) | Yusuf's choice. Fits unusually well: Mantine ships the exact primitives this app needs — DataTable-grade tables, `Drawer` (detail panel), `Modal`, `Stepper` (rubric wizard), `Timeline` (job history), `Badge`/`Indicator` (override, auto-resolved, multi-score, stale markers), `Spotlight`, dark mode — without Tailwind's design-from-scratch tax |
| Client data | TanStack Query for server state + Supabase JS for auth/realtime | Query cache invalidated by realtime events — one consistency mechanism |
| API | FastAPI + Pydantic v2; `BackgroundTasks` for light post-response work only (see [§5](#5-system-architecture)) | Same stack as RoleCast — reuse deployment, client, and testing patterns |
| Worker | Python 3.12 asyncio loop; claims from Postgres queue | No Celery/Redis: durable queue in Postgres via `SKIP LOCKED`; jobs debuggable with plain SQL (NFR5) |
| Orchestration (workflow mode) | Hand-rolled state machine: Pydantic `RunState` + ordered stage functions | The shipping baseline: linear pipeline, two fan-outs, no framework tax |
| Orchestration (agents mode) | LangGraph + Postgres checkpointer | Learning track only ([§10.11](#1011-agents-mode-learning-track)); its interrupt/resume model matches §10.10 checkpoints exactly — the design converged on it independently |
| Observability | Langfuse (cloud free tier or self-hosted) | Traces every LLM call with stage/mode/cost in both modes; wired day one (NFR6) |
| LLM access | Thin provider-agnostic client in `worker/pipeline/llm/`; per-stage model config in one settings file | Keeps the multi-provider door open without committing to it ([§11](#11-llm-strategy)) |
| Fetching | Tiered ladder: httpx → Playwright → unblocker/actor ([§10.7](#107-fetching-subsystem)) | Escalate per domain, not per fetch |
| HTML cleaning | trafilatura primary, readability-lxml fallback, custom fee-table preserver, embedded structured-data miner (JSON-LD + framework state blobs, [§20](#20-decision-log) v2.6) | 5–10× token reduction before any LLM sees the page; the data sites ship as JSON survives it |
| Maps/location | Google Maps Platform: Geocoding, Places, Routes | One vendor; monthly free credit covers this scale |
| DB/Auth/Storage/Realtime | Supabase | Postgres as the single stateful system (NFR5); RLS as the security boundary |
| Hosting | Cloudflare Pages (frontend) + Render (api, worker) + Supabase | Identical operational model to RoleCast |

---

## 8. Database Design

Postgres via Supabase migrations (`supabase/migrations/`). All timestamps UTC `timestamptz`. Soft deletes only where noted; everything else hard-deletes under RLS.

### 8.1 Enums

`hunt_role`: owner | curator | member · `job_type`: ingest | refresh | rescore | investigate · `job_state`: queued | running | waiting_user | done | failed | cancelled · `confidence`: high | medium | low | not_found · `fetch_outcome`: success | shell | blocked | not_listing | error · `value_state`: extracted | manual | estimated | unknown

Each enum type is created by the first migration whose tables need it (0001 creates `confidence` and `fetch_outcome`; the rest ship with the per-hunt/pipeline tables in 0002). Catalog vocabulary columns (`category`, `domain`, `requires_tool`, `refresh_class`) are deliberately **text + check constraints**, not enum types: their vocabularies live in `shared/models.py`, and adding a catalog category must never require a migration.

### 8.2 Tables

Global (shared across hunts):

- **properties** — `id, name, canonical_address, place_id, lat, lng, official_url, first_seen_at`. Dedup identity: geocode proximity (<100 m) AND name similarity above threshold; gray zone → checkpoint ([§10.10](#1010-user-checkpoints)). A `split_property` admin operation exists from day one — unmerging after extractions accumulate is miserable to retrofit.
- **property_sources** — `property_id, url, site_domain, is_official, last_fetched_at, last_success_at, cleaned_text_path, cleaned_text_hash, image_urls jsonb, screenshot_path nullable`. Stored artifact is gzipped **cleaned text** (KB, not MB) + image URL list; raw HTML is transient within a run. Trade-off accepted: cleaner bugs or future markup-dependent fields require a refetch. Screenshots: compressed full-page WebP captured opportunistically on browser-tier fetches, 30-day retention, debugging + checkpoint UX only.
- **floor_plans** — `property_id, source_id, plan_name, beds, baths, sqft_min, sqft_max, rent_min, rent_max, deposit, availability_date, available_units, raw jsonb`.
- **extractions** — `property_id, hunt_id nullable, criterion_key, value jsonb, confidence, evidence_quote, source_id, model, resolution_rule, extracted_at`. **Append-only**: the current value is simply the latest row per (property, hunt_id, criterion) — no updates, no separate history table; a partial index serves the latest-row lookup. `hunt_id` is NULL for catalog criteria (global facts, shared across hunts) and set for **custom criteria**, whose keys are hunt-scoped and must never collide in or leak through the global namespace — consequently custom-criterion values do not transfer when a property is added to another hunt, which is correct. Pipeline always extracts the **full catalog** regardless of enabled criteria — storage is free, re-extraction is not.
- **property_images** — `property_id, storage_path, kind, vision_assessment jsonb`. WebP, ≤10 per property.
- **criteria_catalog** (seeded from `shared/`) — `key, label, category, domain (rent | buy | both), value_schema jsonb, default_options jsonb, extraction_hint, requires_tool (null|maps|vision|web_search), refresh_class`. A hunt sees only its domain's slice. `value_schema` is the single source of truth for: extraction schema generation, backend option validation, and frontend widget rendering. One complete entry, since three subsystems must agree on this shape:

```json
{ "key": "beds", "label": "Number of bedrooms", "category": "unit",
  "value_schema": { "type": "integer", "minimum": 0, "maximum": 5 },
  "default_options": [
    { "match": {"op": "eq", "value": 2}, "delta": 0.5 },
    { "match": {"op": "eq", "value": 1}, "delta": 0.0 },
    { "match": {"op": "eq", "value": 0}, "delta": -0.5 }
  ],
  "extraction_hint": "Count distinct bedrooms; a studio is 0.",
  "requires_tool": null,
  "refresh_class": "listing_details" }
```

The v1 seed set (`refresh_class` values map to the TTL table in [§14](#14-caching-and-refresh-strategy)):

| key | category | value type | requires_tool | refresh_class |
|---|---|---|---|---|
| beds | unit | int 0–5 | — | listing_details |
| baths | unit | number 1–4 (0.5 steps) | — | listing_details |
| sqft | unit | int | — | listing_details |
| patio_balcony | unit | bool | — | listing_details |
| private_entry | unit | bool | — | listing_details |
| in_unit_laundry | unit | enum: in_unit, hookups, on_site, none | — | listing_details |
| pets_policy | policy | enum: cats_and_dogs, cats_only, dogs_only, none | — | listing_details |
| all_in_monthly | cost | number (composed, [§9.5](#95-utilities-and-all-in-monthly-cost)) | — | pricing |
| security_deposit | cost | number | — | pricing |
| availability_date | availability | date | — | pricing |
| kitchen_quality | condition | int 1–5 (anchored, [§10.8](#108-vision)) | vision | images |
| flooring_quality | condition | int 1–5 (anchored) | vision | images |
| parking | unit | enum: garage, carport, dedicated_lot, street_only, none | — | listing_details |
| cooling | unit | enum: central, window_units, none | — | listing_details |
| dishwasher | unit | bool | — | listing_details |
| min_lease_months | policy | int (shortest offered term) | — | pricing |
| grocery_proximity | location | number (minutes, walking or driving per the hunt's `proximity_mode` setting) | maps | location |
| management_reviews | reputation | number 1–5 + summary text | maps (Places reviews) | reviews |
| location_safety | location | enum low/med/high, low-confidence by design (R8) | web_search | reviews |

The §9.5 utility/fee fields (`utilities_included`, `mandatory_fees`, `pet_costs`, `heating_type`) are extraction fields feeding the `all_in_monthly` composition, not standalone criteria.

**Deliberately absent** (documented so they aren't "helpfully" added later without revisiting the reasoning): **base rent** — owned by `floor_plans` and scored through `all_in_monthly`; a separate rent criterion would double-count the number the composition already weighs. **year_built / last-renovated** — a weak proxy for what vision measures directly (a 1990 building with a 2024 kitchen scores as its kitchen, not its birth year); add later via the re-extraction runbook if a real need appears. **Amenities catch-all** (gym, pool, clubhouse…) — an unscoreable grab-bag as one criterion; any specific amenity someone cares about is exactly what custom criteria exist for. **Floor level** and **commute-to-address** — the canonical custom-criteria examples, per §9.2.
- **utility_baselines** — `metro, beds_bucket, utility, monthly_high, monthly_median, sources jsonb, refreshed_at`. Metro-level; 120-day TTL; `monthly_high` is the winter-weighted peak-month figure ([§9.5](#95-utilities-and-all-in-monthly-cost)).
- **fetch_adapter_registry** — `site_domain, required_tier, adapter_config jsonb, last_success_tier, last_outcome, updated_at` ([§10.7](#107-fetching-subsystem)).

Per hunt:

- **hunts** — `id, name, owner_id, domain (rent | buy, v1 supports rent only), rubric_version int, settings jsonb, archived_at`. `settings` is the **hunt settings object** — Owner-edited ([§4.2](#42-roles-and-permissions)), API-validated, with every key defaulted so an empty object is always valid. Its shape is pinned here because the API (validation), the engine/composer (scoring inputs), the planner (source policy), and the frontend (settings panel) all read it:

```json
{ "default_source_policy": "tiers_1_2_3",
  "cost_estimate_mode": "conservative",
  "min_confidence": "medium",
  "proximity_mode": "driving" }
```

  Key semantics, each owned by the section cited: `default_source_policy` — seeds the per-submission Source Policy selector ([§10.7](#107-fetching-subsystem)); editing it affects **future submissions only** — existing listings keep their persisted per-listing policy. `cost_estimate_mode` (`conservative | median`) — which baseline figure estimated utility components use in the all-in composition ([§9.5](#95-utilities-and-all-in-monthly-cost)). `min_confidence` (`low | medium | high`) — extractions below this confidence score as unknown ([§9.3](#93-scoring-engine)); default `medium`, so low-confidence values can never silently satisfy a gate. `proximity_mode` (`walking | driving`) — travel mode for location-proximity criteria such as `grocery_proximity`.

  Edit effects follow from what each key feeds: `cost_estimate_mode` and `min_confidence` are **scoring inputs**, so editing them takes the exact rubric-mutation path ([§9.2](#92-rubric-system)) — bump `rubric_version`, enqueue the free hunt-level rescore; `rubric_version` is honestly "the version of how points are computed," and these settings are part of that. `proximity_mode` changes what ENRICH computes, so editing it enqueues a field-scoped refresh of location-class criteria ([§14](#14-caching-and-refresh-strategy)) — cheap Maps calls, no LLM. `default_source_policy` triggers nothing.
- **hunt_members** — `hunt_id, user_id, role hunt_role, color`. Every per-hunt RLS policy keys off this table.
- **invites** — `hunt_id, email nullable, token, role_granted, created_by, expires_at, accepted_by`.
- **hunt_listings** — `hunt_id, property_id, added_by, status (active | archived), source_policy text, pins jsonb, created_at`. `source_policy` is the Source Policy chosen at submission ([§10.7](#107-fetching-subsystem)) — text + check constraint, defaulted from `hunts.settings.default_source_policy`; refresh jobs read it so a trusted-link listing never silently grows sibling sources. `pins` maps a Unit Group key (`"{beds}-{baths}"`) to a `floor_plan_id` — a pin is **per unit group**, not per listing, because one listing typically holds several groups.
- **rubric_criteria** — `hunt_id, catalog_key nullable, custom_def jsonb nullable, enabled, options jsonb, unknown_delta numeric, non_negotiable jsonb nullable, is_bonus bool (derived), position`. Option shape (one of two places code snippets are warranted — this object is load-bearing):

```json
{ "match": {"op": "eq|lt|gt|range|in|bool", "value": ...},
  "delta": 0.5,
  "dealbreaker_set_score": null }
```

- **overrides** — `hunt_listing_id, criterion_key, value jsonb, user_id, note, created_at`. Display precedence: override > extraction. Append-only history.
- **fee_checklist** — `hunt_listing_id, fee_slot, amount, value_state, entered_by nullable, evidence_ref nullable, updated_at`.
- **scores** — `hunt_listing_id, floor_plan_id, total numeric, breakdown jsonb, rubric_version, computed_at`. Breakdown records per criterion: matched option, delta, gate firings.
- **comments** — `hunt_listing_id, user_id, body, created_at, deleted_at`.
- **ratings** — `hunt_listing_id, user_id, rating smallint`.

Pipeline:

- **jobs** — `id, hunt_listing_id, type, state, current_stage, plan jsonb, payload jsonb, attempts, error, cost_actual_usd numeric (summed from provider usage fields by the LLM client), locked_by, locked_at, created_at, finished_at`. The queue (claimed via `FOR UPDATE SKIP LOCKED`), the live task state, and — because rows are never deleted — the task history (FR10). Crash recovery: the claiming worker refreshes `locked_at` as a heartbeat between stages; a `running` job whose `locked_at` is older than 5 minutes is considered orphaned and reclaimable by any worker, which resumes it from `current_stage` — safe precisely because stages persist before advancing (NFR3).
- **job_events** — `job_id, stage, event (started|completed|failed|checkpoint_asked|checkpoint_answered|checkpoint_auto_resolved|escalated_tier), detail jsonb, at`. Feeds the per-job timeline in the History tab and the realtime Tasks view.

### 8.3 RLS Strategy

Global tables (`properties`, `extractions`, …) are readable by any authenticated user and writable only by the service role (worker/API) — regular clients never write facts. Per-hunt tables are readable/writable per the [permissions matrix](#42-roles-and-permissions), expressed as policies joining through `hunt_members`. Realtime respects RLS, so subscription security is automatic. The API runs with the user's JWT for user-initiated writes (RLS enforced) and the service role only inside the worker.

---

## 9. Business Logic

### 9.1 Hunts, Membership, Invites

Hunt creation makes the creator Owner and opens the rubric wizard (skippable; first URL submission is blocked until a rubric exists). Invites carry a role (`member` default; Owner may grant `curator`) via email or copy-link token; email delivery uses **Supabase Auth's built-in invite/magic-link email** — no third-party email provider enters the stack (NFR5), and the copy-link token path requires no email at all. Acceptance inserts into `hunt_members` and assigns the next unused color. Owner transfer is a single mutation; a hunt always has exactly one Owner.

### 9.2 Rubric System

The catalog defines what *can* be scored; the rubric defines what *is* scored and how. Validation: every option `match` must satisfy the criterion's `value_schema` (backend-enforced; frontend renders widgets from the same schema — one schema, two validators, zero drift). Options are ordered; first match wins; overlapping matches produce a save-time warning. `is_bonus` is derived: all deltas ≥ 0. Any rubric mutation bumps `hunts.rubric_version` and enqueues **one hunt-level `rescore` job** that fans out over the hunt's listings internally — atomic per rubric version, no LLM, effectively free. Scoring-affecting hunt-settings edits (`cost_estimate_mode`, `min_confidence` — [§8.2](#82-tables)) take this same path: same version bump, same rescore job.

Custom criteria: name → description → automatic routing classification (`requires_tool`) via one cheap LLM call → **user confirms the routing with one click** → options defined like any catalog criterion. Misroutes are caught at authoring time, not ingestion time.

### 9.3 Scoring Engine

Pure, deterministic, LLM-free, lives in `shared/`: `score(rubric, effective_values, floor_plan) → {total, breakdown}`.

1. *Effective value* per criterion: override ▸ else latest extraction ▸ else unknown. Extractions below the hunt's `min_confidence` setting ([§8.2](#82-tables)) are treated as unknown. Floor-plan fields overlay property-level values for plan-scoped criteria (`beds`, `baths`, `sqft`, `security_deposit`, `availability_date`); `sqft` takes the conservative end of a range (`sqft_min` when present) — the tool never makes a unit look better than its worst case.
2. *Gate pass:* evaluate all non-negotiables and dealbreakers first. Any firing → `total = min(set_scores fired)`, breakdown records the gates, stop. (Min: multiple gates must not average up.) A dealbreaker fires when the first-matching option carries a `dealbreaker_set_score`; a non-negotiable fires unless the value is known and its first-matching option is acceptable per the [§3 Gate definition](#3-glossary-and-domain-model).
3. *Delta pass:* start at 10; apply first-matching option's delta per enabled criterion; a known value matching no option contributes 0; unknown → `unknown_delta`.
4. Clamp to [0, 15] (bonuses may exceed 10).

Match semantics (settled with the engine, P0-3): `range` is inclusive on both ends; `lt`/`gt`/`range` compare numbers with numbers or strings with strings (ISO dates order correctly as strings); object values such as `management_reviews` `{rating, summary}` compare on their `rating` field; type mismatches never raise — they simply don't match.

The `breakdown` persisted with every score is a contract between the engine, its golden tests, and the detail-panel UI — its shape is fixed here:

```json
{ "base": 10, "total": 9.5, "rubric_version": 4, "clamped": false,
  "gates": [],
  "criteria": [
    { "key": "beds", "value": 2,
      "matched": {"op": "eq", "value": 2}, "delta": 0.5 },
    { "key": "in_unit_laundry", "value": null,
      "matched": null, "delta": -1.0, "unknown": true }
  ] }
```

When a gate fires, `gates` carries `{key, kind: "dealbreaker"|"non_negotiable", set_score}`, `total` equals the minimum set-score, and `criteria` is empty — the delta pass never ran, and the UI should say so rather than showing a hollow list.

Rationale for keeping gates rather than refusing to ingest mismatched listings: a dealbreaker-zeroed row preserves the "why we rejected it" record; a table filter (`hide score < N`) provides the decluttering without the data loss. Silent non-ingestion would confuse (URL in, nothing out).

### 9.4 Floor Plans and Unit Groups

Floor plans are first-class; the table row is a derived Unit Group per (beds, baths). Sqft/rent columns render ranges with a plan count when the group holds >1 plan. **Each floor plan is scored independently; the group displays the best score, never naked:** a stacked-layers indicator appears on the score cell whenever >1 scored plan exists, with per-plan breakdown in tooltip and detail panel. A per-hunt, **per-unit-group pin** on a specific plan switches that group's display and score to the pinned plan (stored in `hunt_listings.pins`, keyed by the group). Rationale: `min` lies about the unit you'd take; a range with no per-plan scores makes comparison mushy; best-with-indicator is honest and decision-relevant.

### 9.5 Utilities and All-In Monthly Cost

The criterion that matters most gets its own machinery.

*Extraction:* structured fields `utilities_included` (list), `mandatory_fees` (name+amount), `pet_costs`, `heating_type` (gas|electric|unknown). Fee language is exactly where listings get vague, so the evidence audit ([§10.5](#105-verification-agent)) applies in full.

*Estimation fallback:* non-included utilities draw from `utility_baselines` — metro-level (zip-level rejected: more calls for precision a leasing-office quote overrides anyway), 120-day TTL (self-healing, not churn-driven), populated by one scheduled LLM+search pass per metro over utility-rate sources. `monthly_high` is the winter-weighted peak month — a Midwest January, not an annual average. Electric heat uses the electric-heat winter figure; unknown heating takes the worse of the two and flags it.

*Composition:* `all_in = rent + mandatory_fees + pet_monthly + Σ(estimated non-included utilities)`, every component tagged `actual | estimated | unknown`. **Defaults to conservative** (`monthly_high` for all estimated components): the tool must never make an apartment look cheaper than the worst realistic month. The hunt's `cost_estimate_mode` setting ([§8.2](#82-tables)) can relax to median. Fully unknown utilities → the criterion's `unknown_delta`, never a fabricated number, plus a "fees unverified" badge.

*Fees checklist:* standard fee slots (admin, water/sewer billing, valet trash, parking, pet rent, insurance program) with states extracted / manual / unknown. Any permitted user ([§4.2](#42-roles-and-permissions)) fills slots after a leasing-office call; manual entries carry a person-pencil icon + attribution on hover — unmistakable from agent-sourced values. Unknown slots keep contributing unknown, so an unfilled checklist never silently improves a score.

### 9.6 Overrides and Provenance

Overrides display over extractions with a badge; the original value, its evidence, source, model, and timestamp remain one tap away in the detail panel. Overrides are append-only (history of who changed what). Every reconciled extraction records the `resolution_rule` that selected it — a suspicious score three weeks later is traceable without re-running anything.

---

## 10. Agent Pipeline

### 10.1 Job Lifecycle

```
RECEIVED → PLAN → VALIDATE_URL → DEDUPE → DISCOVER → FETCH
        → VALIDATE → EXTRACT (×source) → VERIFY (×source) → RECONCILE
        → VISION → ENRICH (maps · reviews · safety · utilities)
        → CUSTOM_MATCH → SCORE
        → DONE | FAILED | CANCELLED
   (any stage may pause into WAITING_USER — a checkpoint — and resume)
```

Each stage is a function `(RunState) → RunState` that persists outputs *before* advancing `jobs.current_stage` — this single discipline yields resumability (NFR3), deploy-safety, and cheap checkpoints. Every transition writes a `job_events` row, which powers both the live Tasks view and the permanent History tab (FR10): plan manifest, per-stage timeline, checkpoint Q&A, tier escalations, errors, and actual cost.

Failure semantics: stage retries with backoff (`attempts`); a dead source is skipped and the run continues; hard failure only when zero sources are fetchable. Cancellation is a state flip checked between stages.

### 10.2 Implementation Patterns

"Agent" in this document is vocabulary, not architecture. Every stage resolves to one of four concrete patterns — knowing which one before implementing prevents the classic failure mode of building an autonomous loop where a single function call belongs. **These patterns govern workflow mode — the shipping baseline and critical path.** Agents mode ([§10.11](#1011-agents-mode-learning-track)) deliberately suspends P3's restraint as a flag-isolated learning exercise, judged by evals rather than by this section's rules.

| Pattern | What it is | Stages |
|---|---|---|
| **P1 — Forced-schema call** | One LLM call whose output shape is compelled | VALIDATE, EXTRACT, CUSTOM_MATCH (text), VERIFY check 4, RECONCILE equivalence |
| **P2 — Deterministic code (+ optional tiny call)** | Plain Python; a model appears only for one narrow judgment | PLAN, VALIDATE_URL, VERIFY checks 1–3, RECONCILE ladder, SCORE (no LLM at all) |
| **P3 — Bounded tool loop** | Model iteratively calls tools until it answers or hits a turn cap | DISCOVER; location-type custom criteria in ENRICH — **nothing else** |
| **P4 — Vision call** | P1 with images as input content blocks | VISION |

**P1 — Forced-schema call.** Define one tool whose `input_schema` *is* the desired output schema, and force the model to use it (`tool_choice` pinned to that tool) — the model cannot answer except by emitting schema-shaped JSON. No prose parsing, no "respond in JSON" prompting. The extraction schema is generated at runtime from `criteria_catalog` via dynamic Pydantic model creation (every field `{value, confidence, evidence_quote}`), so the catalog remains the single source of truth and the schema is never hand-maintained. On validation failure: retry once with the validation error appended to the conversation; a second failure is a job error, not another retry. Provider usage fields from every call feed `jobs.cost_actual_usd`.

**P2 — Deterministic code.** VERIFY is the exemplar and the discipline to hold: the evidence audit is a fuzzy substring match (e.g., `rapidfuzz.partial_ratio(evidence_quote, cleaned_text) > threshold`), plausibility is comparisons against the band table, conformance is Pydantic — roughly 150 lines of plain Python wrapping exactly one cheap P1 call (cross-field contradictions). Resist making P2 stages "smarter"; their testability and determinism are the point.

**P3 — Bounded tool loop.** The canonical shape — small enough to specify exactly, and worth specifying because unbounded variants are how agent systems fail:

```
messages = [user_task]
for turn in range(MAX_TURNS):                # budget is not optional
    r = llm(messages, tools)
    if r.stop_reason != "tool_use": return r
    for call in r.tool_calls:
        result = REGISTRY[call.name](**call.input)   # execute
        log_job_event(call, result)                  # observability
    messages += [r.assistant_turn, tool_results]
raise AgentBudgetExceeded                     # a real outcome, handled by the stage
```

Every tool invocation and result is a `job_events` row — this is how the Tasks history later shows "searched X, fetched Y, judged Z."

**Tools.** A custom tool is an async Python function in a name→callable registry; a small `@tool` decorator derives its JSON schema from the signature and docstring, so registry and schemas cannot drift. Planned custom tools: `geocode`, `places_nearby`, `commute_time`, and `fetch_page` — the latter routes through the tier ladder ([§10.7](#107-fetching-subsystem)), so any tool-using agent inherits the adapter registry, rate limits, and politeness for free rather than fetching on its own. Provider-hosted tools (the server-side web-search tool) execute on the provider's side with no local handler and are the right choice for DISCOVER's searching. Tools available to a stage are explicitly allow-listed per stage; extraction stages get **none** — that zero-tool property is a security control ([§16](#16-security-and-privacy)), not an omission.

**The runner.** Stages are async functions `(RunState) → RunState` over one Pydantic state object; the runner walks an ordered list from a resume cursor, and the single load-bearing rule is **persist before advance**:

```
for stage in STAGES[state.cursor:]:
    state = await stage(state)
    persist(state, job)        # ← resumability, deploy-safety, checkpoints
    state.cursor += 1
```

The Phase 0 CLI and the Phase 1+ queue worker are two entry points calling the same `run_job` — the CLI is not throwaway work.

**The client seam.** No pipeline code imports a provider SDK directly. Everything goes through the thin client ([§11.1](#111-provider-seam)) exposing `call_structured(stage, schema, content)`, `call_agent(stage, tools, task)`, and `call_vision(stage, schema, images)` — the one place where prompt caching, per-stage model pinning, cost accounting, and test-fixture record/replay live.

### 10.3 Stage Catalog

| Stage | Purpose | Model | Notes |
|---|---|---|---|
| PLAN | Build run manifest: stages to run, sources to (re)fetch, cache/TTL decisions, cost estimate | tiny LLM assist; mostly deterministic | Manifest persisted as `jobs.plan`. A manifest builder, **not** an open-ended agent — that restraint is deliberate ([§20](#20-decision-log)) |
| VALIDATE_URL | Is the submitted URL worth fetching at all? | none | Deterministic (v2.4): scheme, public host (private/loopback refused — §16), not a binary; normalizes the URL (whitespace/fragments) before anything else sees it |
| VALIDATE | Is this a rental listing page? | small | Runs on the **fetched, cleaned text** of the submitted source — after FETCH (v2.4). Heuristics first (no listing signal → rejected at zero LLM spend), LLM to confirm |
| DEDUPE | Name+address → geocode → match `properties` | small | <100 m AND name-similar → merge; gray zone → checkpoint |
| DISCOVER | Find official site + up to 2 sibling sources | judgment-tier | Third source fetched only if first two disagree ([§15](#15-cost-model-and-optimization)); skipped entirely under `trust_link`, tier-capped by the run's Source Policy ([§10.7](#107-fetching-subsystem)) |
| FETCH | Tier ladder per adapter registry | none | [§10.7](#107-fetching-subsystem) |
| EXTRACT | Full-catalog structured extraction from cleaned text | workhorse | Schema generated from `criteria_catalog`; every field = value + confidence + evidence_quote |
| VERIFY | Per-source audit | workhorse | [§10.5](#105-verification-agent) |
| RECONCILE | Merge sources via resolution ladder | workhorse (equivalence only) | [§10.6](#106-conflict-resolution) |
| VISION | Kitchen modernness, floor/carpet quality from images | vision-tier | Prompt anchored with reference images from real listings Yusuf has rated; reference set versioned with the prompt |
| ENRICH | Maps distances/commutes, Places reviews summary, safety synthesis (low-confidence by design), utility baseline application | small + APIs | Safety data is knowingly weak — do not over-invest ([§17](#17-risks-and-concerns-register)) |
| CUSTOM_MATCH | Match hunt custom criteria per `requires_tool` routing | small | |
| SCORE | Deterministic engine, per floor plan | none | |

### 10.4 Planner

Deterministic-first: TTL lookups, hash checks, refresh-scope resolution, and adapter-registry reads are plain code; a single small-model call handles genuine judgment (ranking >3 candidate sources by trustworthiness). Output is an explicit manifest enabling three things: Tasks UI shows planned-vs-completed, debugging starts by reading the plan, and cost is estimated before spend. Its shape:

```json
{ "job_type": "refresh", "trigger": "ttl:rent_expired",
  "source_policy": "tiers_1_2_3",
  "sources": [
    { "source_id": "…", "action": "fetch", "tier": 1 },
    { "source_id": "…", "action": "skip", "why": "hash_fresh" } ],
  "stages": ["FETCH", "EXTRACT", "VERIFY", "RECONCILE", "SCORE"],
  "skipped": { "VISION": "images_unchanged", "ENRICH": "location_immutable" },
  "est_cost_usd": 0.03 }
```

### 10.5 Verification Agent

Runs per source after extraction. Four checks: **(1) Evidence audit** — every value's `evidence_quote` must fuzzy-match text actually present in the fetched page; unlocatable evidence demotes to `low`. This is simultaneously the anti-hallucination and the primary anti-prompt-injection control ([§16](#16-security-and-privacy)). **(2) Schema conformance** re-checked post-parse. **(3) Plausibility rules** — data-driven bands, not LLM vibes: rent percentile band for the metro, sqft/bed ratio, deposit ≤ ~2× rent, availability not in the past. Bands are **self-derived** from the metro's accumulated listings (rolling percentiles per beds bucket); cold start (<~8 listings in metro) routes out-of-band values to a checkpoint whose confirmed answers seed the band. **(4) Cross-field consistency** — e.g., "in-unit laundry: yes" against a "laundry facility on site" amenity text. Failures demote confidence; gate-relevant criteria escalate to a `confirm_value` checkpoint instead of silently scoring on suspect data.

### 10.6 Conflict Resolution

Deterministic ladder, evaluated top-down per criterion; the LLM's only role is semantic equivalence normalization before comparison ("W/D in unit" ≡ "in-unit laundry"):

1. Manual override always wins (outside the pipeline entirely).
2. Numeric tolerance collapse: within 3% (rent) / 5% (sqft) = agreement; take the official figure.
3. Official source beats aggregators.
4. Same tier: fresher fetch wins.
5. Majority vote at 3+ sources.
6. Higher verification confidence.
7. Still contradictory → official value stored marked `disputed`, all candidates retained in jsonb, confidence low; if the criterion is gate-bearing in any hunt using the property → `resolve_dispute` checkpoint with one-click pick-the-value resolution.

The winning rule is stored on the extraction (`resolution_rule`).

### 10.7 Fetching Subsystem

**Per-domain adapter registry + three-tier ladder.** The registry records what each domain requires; the ladder is climbed once per domain, not once per fetch.

- **Tier 1 — httpx:** plain HTTP with sane headers. Covers most official complex sites; DISCOVER deliberately prioritizes finding these.
- **Tier 2 — Playwright:** realistic-fingerprint headless browser for JS-rendered but unprotected pages. Slow, polite, per-domain rate-limited. Captures the opportunistic screenshot (already rendering — the photo is free).
- **Tier 3 — managed unblocker:** a swappable provider adapter (Bright Data Web Unlocker default; ScrapingBee alternate) for hostile aggregators, **free plans only** — paid escalation requires a new [§20](#20-decision-log) decision, not an env change ([§20](#20-decision-log) 2026-07-07). Fallback, never default: the ladder only reaches tier 3 after tiers 1–2 classify shell/blocked, and tier 3 stays off the ladder entirely until a provider key is configured. Switching provider is one env var (`MANZIL_TIER3_PROVIDER`); adding one is a single adapter entry in `fetching/tier3.py`. The Apify structured-actor variant (aggregator actors returning parsed JSON, bypassing FETCH+EXTRACT with their schema mapped onto ours) remains **deferred** — it is a second data path, not a fetcher, and needs its own decision. When every tier fails, FETCH's error carries a deterministic URL-slug search hint ("try searching *riverfront towers detroit mi* on a fetchable source") — the zero-LLM human stand-in for DISCOVER's sibling-source rescue until P3-5.

**Source Policy (cross-check control).** Every submission carries a Source Policy governing how aggressively the pipeline corroborates the submitted link against other sites. The default is full cross-check — the behavior described everywhere else in this document. The options:

| Policy | DISCOVER | Sibling-source tier cap |
|---|---|---|
| `trust_link` | skipped | — (no siblings; single-source run) |
| `tier_1` | runs | siblings limited to Tier 1 domains |
| `tiers_1_2` | runs | siblings limited to Tiers 1–2 |
| `tiers_1_2_3` **(default)** | runs | no cap — current full behavior |
| `tier_1_plus_official` | runs | sibling aggregators limited to Tier 1; the official complex site fetched at whatever tier it requires |

Semantics, precisely: the policy constrains **discovered sibling sources only — never the submitted URL**, which is always fetched at its registry-required tier (the user brought it; refusing it would make the submission meaningless). "Tier" here is the domain's required fetch tier per the adapter registry — a cost/hostility cap, not a source-quality ranking. A sibling whose domain requires a tier above the cap is not fetched-and-escalated; it is skipped at plan time and recorded in the manifest (`"action": "skip", "why": "policy_tier_cap"`). A sibling that unexpectedly classifies `shell`/`blocked` at the cap is likewise skipped rather than escalated, and the registry still records the outcome so the ladder's self-tuning is unaffected. The §15 source-count discipline (third source only on disagreement) applies *beneath* the cap — policy is an upper bound, not a fetch mandate.

The policy is selected at submit time (FR3), defaulting from `hunts.settings.default_source_policy` (itself defaulting to `tiers_1_2_3`), persisted on the listing (`hunt_listings.source_policy`) so refresh jobs honor the same constraint, and recorded in the plan manifest ([§10.4](#104-planner)). Under `trust_link` the run is single-source: RECONCILE degrades trivially (one candidate per criterion, `resolution_rule: single_source`), and the listing carries a permanent **"single source — not cross-checked"** badge in the table and detail panel, because the cross-source outvoting that backs R3/R4 is absent by the user's explicit choice ([§16](#16-security-and-privacy)). VERIFY and the deterministic truth layer are untouched in every policy — Source Policy narrows *which pages feed the pipeline*, never *what counts as correct*.

**Tier-detection heuristics (fetch outcome classification).** Every fetch is classified `success | shell | blocked | not_listing | error` by layered checks, cheapest first. *HTTP-layer signals:* status 403/429/503, challenge headers and cookies (Cloudflare `cf-chl`/`cf_clearance` flows, PerimeterX `_px` cookies), redirects to captcha paths. *Challenge fingerprints in the body:* "Pardon Our Interruption", "Verify you are human", "Enable JavaScript and cookies to continue", `cf-challenge` markup. *Positive content signals:* cleaned text — which includes the mined `[EMBEDDED DATA]` digest ([§20](#20-decision-log) v2.6) — above a length threshold **and** at least one of: a currency amount pattern, bed/bath tokens, an address fragment, or rental-fact JSON keys (`"priceLow":`, `"bedCount":` — state blobs carry prices as bare numbers); JSON-LD `schema.org` blocks (`ApartmentComplex`, `RealEstateListing`, `Offer`) are a strong positive that also short-circuits doubt. *Negative body signals, checked only after the positives fail:* a body that is nearly all script tags (the JS-shell signature), rendered text under a size floor (~5 KB). Positive content deliberately outranks the JS-shell heuristic: a script-heavy page whose state blob carries the listing's floor plans is a usable page, not a shell — this is what lets tier 1 settle domains (zumper, padmapper) that render an empty DOM but server-ship their data as JSON. Routing: `shell` → escalate one tier; `blocked` → escalate and record in the registry; `not_listing` → the VALIDATE verdict (surface to user); `success` → clean, hash, proceed. Outcomes update `fetch_adapter_registry` so the ladder self-tunes: a previously easy domain that starts failing simply resumes climbing from the next tier.

### 10.8 Vision

Runs on stored property images (≤10, WebP, ~1024px). Per-image detail lands in `property_images.vision_assessment`; the aggregated per-criterion rating (the thing the rubric scores) is written to `extractions` like any other value, with the contributing image paths as its evidence. Prompt is anchored with 3–4 **real reference images per rating level, hand-picked from listings Yusuf has personally rated** — this is the consistency control; the reference set is versioned alongside the prompt and changing it is a reviewed migration (re-run, diff, accept). Skipped entirely when image URLs/hashes are unchanged.

### 10.9 Custom Criteria Routing

`requires_tool` is fixed at authoring time ([§9.2](#92-rubric-system)); at run time CUSTOM_MATCH simply dispatches: `null` → plain text matching, `maps` → ENRICH-style API call, `vision` → appended to the vision pass, `web_search` → scoped search+synthesis. No runtime routing intelligence exists or should be added.

### 10.10 User Checkpoints

Any stage may pause into `WAITING_USER` with a structured prompt `{kind, question, options: [yes, no, other:<input>], default, context_ref}` persisted on the job; the Tasks UI renders the buttons (with the page screenshot beside them when one exists — answering "does $2,450 look right?" without opening the original link); the answer lands in `jobs.payload` and the stage resumes with it. Answerable by the listing's submitter, any Curator, or the Owner.

**Unanswered checkpoints auto-resume after 24 hours** with the declared default — generally "accept the extracted value at low confidence" or the plausibility-leaning option. Auto-resolution writes a permanent `checkpoint_auto_resolved` job event and places an indicator badge (clock glyph) on the listing's table row; the checkpoint can be re-opened from the detail panel, and a late answer replaces the default and triggers a re-score. Checkpoint kinds in use: `confirm_value` (plausibility cold-start, suspect gate values), `resolve_dedupe` (property-merge gray zone), `resolve_dispute` (unresolvable reconciliation on gate-bearing criteria). The kind determines the default applied at the 24 h auto-resume; `resolve_dispute`'s default is an open question ([§21](#21-open-questions)).

### 10.11 Agents Mode (Learning Track)

The pipeline has **two implementations behind one flag** (`--mode=workflow | agents`). They share the RunState/persistence contract, stage semantics, and — non-negotiably — the **deterministic truth layer**: VERIFY checks 1–3, the RECONCILE ladder, and SCORE run identically in both. The invariant in one line: *agents mode may change who does the work, never what counts as correct.* All agents-mode code lives in `worker/src/manzil_worker/agents/` and imports the truth layer; nothing on the critical path imports back.

The named architectures it implements, each chosen because it fits Manzil naturally rather than being bolted on:

- **Orchestrator–workers** (cross-source extraction): an orchestrator receives the URL, decides which sibling sources to check, spawns a parallel extraction worker per source — each with its own context window and the fetch-ladder tools — and hands the structured briefs to the reconciler. Genuinely parallel work, so the benefit observed is real, not simulated.
- **Extractor + critic** (proposer–critic): a critic receives the raw page and the extracted record and hunts for discrepancies before anything is written. The eval question is precise: does the critic catch errors that deterministic VERIFY misses, and at what token cost? Keep or kill on that data.
- **LangGraph graph + Postgres checkpointer**: agents mode implements the pipeline as a LangGraph graph; §10.10's checkpoints map exactly onto interrupt → persist → resume — the strongest natural fit in the whole track, since the design converged on that model before the framework entered the picture. Comparing it against the hand-rolled runner is itself a lesson in what frameworks buy.
- **Explicit triage routing**: a classifier step that grades task difficulty and dispatches the model tier, turning §11.2's implicit workhorse/judgment split into a named, built architecture.
- **Deep-dive investigator** (FR12): a spawnable crew — one worker on reviews and management-company reputation, one on scam signals and cross-listing price checks, one on the area — synthesized by an orchestrator into a brief. New `job_type: investigate`; entirely off the critical path, so its failure modes break nothing.

**Evaluation is the point.** Both modes run against the bench set; the harness compares accuracy, tokens, and latency, and the honest expectation going in is a 5–15× token multiplier for agents mode. Adoption rule: an agents-mode component becomes part of the default path only with eval evidence plus a decision-log entry — the same standard as any design change. The track's final deliverable is a written eval report in `docs/` stating what multi-agent bought and what it cost.

---

## 11. LLM Strategy

### 11.1 Provider Seam

All model calls go through a thin client in `worker/pipeline/llm/` with a per-stage model map in one settings module (`worker/pipeline/llm/config.py` — pinned OpenRouter model slugs, per-stage assignment, cache-control markers). The seam speaks one OpenAI-compatible API via **OpenRouter** (`openai` SDK → `https://openrouter.ai/api/v1`); swapping a stage's model — any vendor — is a config change in `llm/config.py`. Upstream provider pinning (`provider.order` + `allow_fallbacks: false`) keeps routing deterministic and cache hits sticky across calls (§11.3). Structured output uses forced tool use (`tools` + pinned `tool_choice`); explicit `cache_control` on the stable prefix passes through to Anthropic models and is harmless elsewhere. This seam exists so the bench in Phase 0 can settle model choices empirically — it is **not** a mandate to go multi-vendor on day one. A non-Anthropic default pin is adopted only if the bench shows material savings at an equal verification pass-rate (P0-14 + a §20 entry).

### 11.2 Model Roles and Candidates

Baseline plan (all-Anthropic via OpenRouter): **Claude Haiku 4.5** (`anthropic/claude-haiku-4.5`) as the workhorse (extract, verify, reconcile-equivalence, validate, custom-match, plan-assist), **Claude Sonnet 4.6** (`anthropic/claude-sonnet-4.6`) for the taste-tier (vision, DISCOVER same-property judgment).

Alternatives explicitly evaluated per Yusuf's request — indicative list pricing as of mid-2026, **verify before committing** (prices move quarterly). OpenRouter slugs shown; list prices in `MODEL_PRICES` are the cost-tally source of truth:

| Model (OpenRouter slug) | ~$/MTok in / out | Candidate for | Assessment |
|---|---|---|---|
| `anthropic/claude-haiku-4.5` | 1.00 / 5.00 | workhorse (baseline) | Strong structured extraction + evidence fidelity; prompt caching (−90% cached input) via OpenRouter passthrough |
| `anthropic/claude-sonnet-4.6` | 3.00 / 15.00 | vision + judgment (baseline) | Highest-confidence vision assessments |
| `google/gemini-2.5-flash-lite` | 0.10 / 0.40 | VALIDATE, CUSTOM_MATCH, possibly EXTRACT | ~10× cheaper than Haiku on input; supports vision + structured output; the question is evidence-quote fidelity and fee-language extraction quality — bench it |
| `google/gemini-2.5-flash` | 0.30 / 2.50 | VISION replacement | Credible vision at ~⅙ Sonnet price; implicit caching via Google AI Studio |
| Gemini 3 / 3.1 Flash-Lite tier | 0.25–0.50 / 1.50–3.00 | mid-tier alternative | Newer family; only worth it if 2.5 Flash-Lite fails the bench |
| DeepSeek V3.x | ~0.14 in | text-only stages | Cheapest text; no fit for vision; weaker structured-output ergonomics — likely not worth a third provider for pennies |
| GPT-5 Mini / Nano tier | mid/low range | same slots as Gemini Flash | Competitive on paper; adds a provider without a distinct advantage here |

**Recommendation:** start all-Anthropic (Phases 0–2). In Phase 0, run the extraction bench (same 20 listings, same schema) across Haiku 4.5, Gemini 2.5 Flash-Lite, and Gemini 2.5 Flash, measuring verification pass-rate, gate-criterion accuracy, and cost. The realistic upside of a Gemini split is cutting the two biggest LLM lines (EXTRACT and VISION) by 5–10×, taking per-listing cost from ~$0.10 toward ~$0.03 — real money at zero scale is still ~nothing, so quality wins any tie. OpenRouter's ~5.5% platform fee is cents at this scale (§15).

### 11.3 Cross-Cutting Techniques

- **Structured outputs everywhere:** extraction schema generated from `criteria_catalog`; every field `{value, confidence, evidence_quote}` — the evidence requirement measurably suppresses hallucination and feeds VERIFY.
- **Prompt caching:** stable per-stage prefixes (schema, catalog, rules, few-shots; ~3–6k tokens) marked cacheable → ~90% off on hits.
- **Model pinning and migrations:** model IDs pinned in config and recorded per extraction; upgrading a model is a deliberate migration — re-extract from stored cleaned text, diff against prior values, review the diff. Never let a silent model change wobble scores.

---

## 12. External Integrations

| Integration | Used for | Notes |
|---|---|---|
| OpenRouter | All LLM stages | Single gateway (`OPENROUTER_API_KEY`); OpenAI-compatible API; prompt caching passthrough is load-bearing for NFR1; Anthropic Message Batches API unavailable — accepted (§15) |
| Google Maps Platform | Geocoding (dedupe), Places (grocery/mosque proximity, reviews), Routes (commute criteria) | Within monthly free credit at this scale; geocodes and distances cached forever |
| Supabase | Postgres, Auth, Storage (images, cleaned text, screenshots), Realtime | The single stateful system |
| Bright Data (default) / ScrapingBee (alternate) | Tier-3 fetching | **Free plans only** (§20 2026-07-07); provider swap = one env var. Apify structured actors still deferred |
| Render / Cloudflare Pages | Hosting | Blueprints in `infra/` |

---

## 13. Frontend Design

### 13.1 Routes

```
/                       hunt switcher · create hunt
/h/:huntId              Overview — table + detail panel
/h/:huntId/rubric       Rubric (wizard for Owner; read-only for others)
/h/:huntId/tasks        Tasks — Active | History tabs
/h/:huntId/compare      2–4 listing side-by-side
/h/:huntId/settings     Members, roles, invites, colors, hunt settings (§8.2 — Owner-edited,
                        member-viewable), danger zone (Owner)
/invite/:token          Invite acceptance (auth-gated)
```

### 13.2 Key Views (Mantine mapping)

**Overview table** (`mantine-react-table` or Mantine Table + TanStack): score cell with color scale + stacked-layers multi-score indicator + auto-resolved clock badge + stale badge + single-source badge for `trust_link` listings ([§10.7](#107-fetching-subsystem)); columns for name, unit group, rent range, sqft range, all-in cost (estimated portion visually distinct, e.g. `$1,845 (~$210 est.)`), top enabled criteria, rating dots per member color, comment count. Filters include `hide score < N`. The submit-URL control carries a Source Policy `Select` preset to the hunt default — visible but not in the way, since the default is right for most submissions.

**Detail panel** — `Drawer` on desktop, bottom `Drawer`/sheet on mobile: criterion breakdown with evidence quotes and override controls, `Image` gallery with vision assessments, floor plans with pin control, sources with `last_fetched_at` plus the listing's Source Policy (changeable here — relaxing it enqueues a refresh that discovers the newly allowed sources), fee checklist, comments, score history across rubric versions, any open/auto-resolved checkpoints for this listing, and an **Investigate** action (FR12) that enqueues an `investigate` job and renders the returned brief when complete.

**Tasks** — Active tab: live job cards (Realtime on `jobs`/`job_events`) with stage progress, checkpoint prompts rendered inline (screenshot beside the buttons when available), cancel/retry per permissions. **History tab (FR10):** every past run, filterable by listing/member/outcome; expanding a run shows the plan manifest, `Timeline` of stage events, checkpoint Q&A including auto-resolutions, errors, and actual cost.

**Rubric** — `Stepper` wizard on first run; criterion cards with `Switch`, options table with `NumberInput` delta steppers, unknown-delta row, gate toggles revealing set-score inputs; widgets rendered from `value_schema`. Read-only rendering of the identical structure for non-Owners.

### 13.3 Realtime

Supabase channels per hunt on: `hunt_listings`, `scores`, `comments`, `jobs`, `job_events`. Events invalidate TanStack Query caches — one consistency mechanism, no bespoke socket handling. RLS applies to Realtime, so subscription security is automatic.

---

## 14. Caching and Refresh Strategy

| Data class | TTL | Re-runs |
|---|---|---|
| Rent, availability, deposit, fees | 24–48 h | FETCH(official) → EXTRACT → VERIFY → RECONCILE → SCORE |
| Listing details (beds, laundry, pets, sqft) | 14 d | same |
| Images / vision | 30 d or new images | image FETCH → VISION → SCORE |
| Reviews | 30 d | ENRICH(reviews) → SCORE |
| Utility baselines | 120 d | scheduled metro job |
| Location facts (geocode, distances) | immutable | address correction only |

**Content-hash gating is the keystone:** `cleaned_text_hash` compared on every fetch; unchanged content skips EXTRACT+VERIFY entirely, so steady-state refresh cost rounds to a fetch and a comparison. The planner maps "refresh only fields X" to stages via the catalog's `refresh_class`. Hunt-wide refresh fans out one job per listing under a per-domain rate limiter (politeness doubles as bot-detection avoidance).

---

## 15. Cost Model and Optimization

Baseline (all-Anthropic via OpenRouter) per-listing budget, first ingestion, 3 sources, ~8 images — naive: **~$0.26**. With the levers below: **~$0.10–0.12 new · <$0.01 refresh · $0 re-score**, meeting NFR1. A 60-listing hunt with two months of daily refreshes: roughly $8–12 total inference (plus OpenRouter's ~5.5% platform fee — cents at this scale). A Gemini split per [§11.2](#112-model-roles-and-candidates) could roughly triple the headroom; take it only on a quality tie.

Levers, in order of impact:

1. **Prompt caching** on stable stage prefixes → ~40–50% off workhorse input spend.
2. **Content-hash gating** → refreshes stop costing extraction at all; without this, refreshes quietly become 80% of the bill.
3. **Vision discipline:** ≤8 images, ~1024px, skip on unchanged hashes; bench the cheaper vision model with reference-image anchoring.
4. **Source-count honesty:** third source only when the first two disagree.
5. **Global property reuse:** re-adding a known property to a new hunt costs a $0 SCORE plus whatever TTLs say is stale.
6. **Not worth optimizing:** Maps (inside free credit), Postgres-as-queue ($0), and anything requiring new infrastructure — complexity is the real budget.

*Dropped lever — Anthropic Message Batches API (−50% on non-interactive work):* unavailable through OpenRouter. New-listing ingestion is latency-bound (NFR2), so batch never applied there; content-hash gating (lever 2) already zeroes unchanged refreshes; the realistic savings over a full hunt were ~$1–3. NFR1 is met without it.

Fixed monthly: Cloudflare Pages $0 · Supabase $0 (cleaned-text caching + image cap keep free tier viable indefinitely at this scale) · Render API $0–7 · Render worker ~$7 (paid, so jobs never wait on cold starts; Phase 1 may run the in-process loop instead, [§5](#5-system-architecture)) · Maps $0 · Tier-3 services $0 unless the gate opens, then ~$5–30 pay-per-use. **Realistic: $7–14/mo + usage.**

**Learning-track spend is bounded by design:** agents mode runs against bench-set-sized workloads, not the live hunt, so its expected 5–15× token multiplier applies to ~20 listings per eval run (order of a few dollars), not to daily operation. Investigator runs are on-demand and estimated at roughly $0.30–0.80 each. Langfuse makes every trace's cost visible, which is both the budget control and part of the curriculum.

---

## 16. Security and Privacy

- **RLS is the boundary.** Every per-hunt table policy joins through `hunt_members`; global fact tables are client-read-only. API mutations run under the user JWT; only the worker holds the service role.
- **Prompt injection via scraped pages** (untrusted input into prompts): extraction agents have *zero tool access* — worst-case injection is a bad value, not an action; VERIFY's evidence audit rejects values without genuine page evidence; plausibility bands catch absurd numbers; the fields most worth lying about (rent, fees) are exactly the cross-source-reconciled ones. Reduces injection from "compromise" to "one bad field that other sources outvote." A `trust_link` Source Policy ([§10.7](#107-fetching-subsystem)) removes the outvoting layer by explicit user choice; the zero-tool, evidence-audit, and plausibility controls still apply in full, and the permanent single-source badge keeps the reduced assurance visible.
- **Invite tokens:** random, expiring, single-role, revocable; accepting requires an authenticated session.
- **Secrets:** all API keys server-side only (Render env); the frontend holds nothing but the Supabase anon key, which RLS renders safe.
- **PII posture:** the system stores members' emails, names/colors, comments, and searched addresses (commute targets). No listing-agent PII is extracted or stored. Screenshots and cleaned text may embed page content — 30-day screenshot retention bounds this.

---

## 17. Risks and Concerns Register

| # | Risk | Severity | Mitigation / posture |
|---|---|---|---|
| R1 | Anti-bot blocking on major aggregators | High | Tier ladder + registry ([§10.7](#107-fetching-subsystem)); official-site preference; Phase 0 gate decides whether Tier 3 is needed at all. One good source suffices by design |
| R2 | ToS exposure from scraping | Medium | Personal, low-volume, private tool; unblockers outsource the blocking fight, not the legal posture; never becomes a public service |
| R3 | Hallucinated / wrong extractions poisoning decisions | High | Evidence quotes + VERIFY audit + plausibility bands + cross-source reconcile + override with provenance |
| R4 | Prompt injection via listing pages | Medium | See [§16](#16-security-and-privacy) |
| R5 | Dedupe false merges corrupting shared data | Medium | Dual-condition auto-merge; gray-zone checkpoints; `split_property` op from day one |
| R6 | Extraction inconsistency / model drift wobbling scores | Medium | Hash gating; pinned models; migrations as reviewed diffs; versioned vision reference set |
| R7 | Stale data presented as current | Medium | `last_fetched_at` on every row; TTL-based stale badges; conservative all-in defaults |
| R8 | Safety-data quality is inherently poor | Low | Ship as low-confidence synthesis; rely on overrides; do not sink a week here |
| R9 | Supabase/Render free-tier ceilings | Low | KB-scale text artifacts; ≤10 images/property; 30-day screenshot retention; paid worker when Playwright arrives |
| R10 | Scope creep (the real killer of personal projects) | High | [§18](#18-deferred-features-and-backlog) is a parking lot, not a promise; NFR5's new-moving-part rule; phases with exit criteria |
| R11 | Learning track starving shipping ("architecture astronautics") — the sneaky variant of R10, and there is a lease deadline | High | Hard gating rule in [§19](#19-implementation-phases): L-milestones start only after their shipping dependency is green and never delay the next shipping milestone; agents code flag-isolated in one module; eval reports force empirical honesty about what the ambition actually bought |

---

## 18. Deferred Features and Backlog

Explicitly **not** in scope until pulled in deliberately (coding agents: do not implement):

- **Apify actor adapters for hostile aggregators** — gated on Phase 0 findings; may be prioritized up or dropped entirely based on how much inventory actually lives behind hostile domains.
- Automated listing discovery / alerts.
- Off-market detection beyond stale badging.
- Zip-level utility baselines; traffic-window-aware commute times.
- Per-member weighted rubrics / multiple rubrics per hunt.
- CSV/Sheets export; public read-only hunt sharing.
- Screenshot-based extraction as a last-resort path for text-unrecoverable pages.
- Push/email notifications (checkpoint asked, score changed).
- **Buy-domain support (house hunting / purchasing).** The `domain` seams exist ([§8.2](#82-tables)); the engine, pipeline, and collaboration layer are domain-blind, and unit groups degrade gracefully to single-plan houses. What activating it requires: a buy catalog slice (price, taxes, HOA, insurance, roof/HVAC age, lot, schools, price history), a PITI-style cost composer taking hunt-level financing settings (down payment, rate, term — user inputs, not extractions), listing-status transitions (pending/sold, price cuts), and — critically — Tier-3 fetching from day one, since individual homes have no official site and the canonical source *is* the hostile aggregator. Keep `shared/` free of rental assumptions (cost composition behind an interface) so this stays an addition, not a rewrite.

---

## 19. Implementation Phases

**Phase 0 — Prove the pipeline (CLI, no UI, no auth).**
Monorepo scaffold; `shared/` domain models + catalog seed + scoring engine with tests; migrations; CLI `ingest <url>` running VALIDATE_URL → FETCH(T1–T3) → VALIDATE → EXTRACT → VERIFY → SCORE against a hardcoded rubric, printing the breakdown. Run against ~20 real listings, **hand-labeled first**: ground-truth values for every gate-bearing criterion (and rent/fees) per bench listing, stored as `fixtures/bench/labels/` (a **local eval asset** alongside the corpus snapshots it describes — gitignored and backed up, never repo content; [§20](#20-decision-log) v2.8) — accuracy metrics are meaningless without them, and labeling ~20 listings is an evening. The hardcoded Phase 0 rubric is Yusuf's real criteria (2 br, in-unit laundry, balcony, cats allowed, all-in < $2,000 conservative), checked in as a fixture. Also: **Langfuse tracing wired from the first LLM call** (NFR6), the **eval harness skeleton** (FR11 — it doubles as the bench runner), the **model bench** ([§11.2](#112-model-roles-and-candidates)), and the **hostile-domain census** (which target-market sources demand Tier 3?).
*Exit criteria:* extraction verification pass-rate acceptable on gate-bearing criteria; fetch tier requirements known per relevant domain; per-stage model choices settled; per-listing cost measured. **Decision gate:** with the tier-3 fetcher built free-plan-only ([§20](#20-decision-log) 2026-07-07), the census now rules on keeping it, the provider choice, and whether Apify actor work is ever warranted.

**Phase 1 — Replace the spreadsheet (single user).**
API + queue + worker (in-process loop acceptable here); Overview table, detail panel, rubric builder, overrides, fees checklist, Tasks Active tab. Supabase Auth for one user.
*Exit:* Yusuf's real hunt runs here, spreadsheet retired.

**Phase 2 — Collaboration.**
RLS policies + permissions matrix (Curator role), invites, realtime sync, comments, ratings, colors, Tasks History tab.
*Exit:* second real user active; permissions verified at the RLS layer by tests.

**Phase 3 — Full agent system.**
Planner manifests; DISCOVER multi-source + RECONCILE ladder; VISION with reference set; Maps/reviews/safety ENRICH; utility baselines job; custom-criteria routing; checkpoints incl. 24 h auto-resume; refresh TTLs + hash gating; compare view; separate paid worker; mobile sheet polish. Tier-3 adapters if — and only as much as — the Phase 0 gate demands.
*Exit:* NFR1–NFR4 measured and met on the live hunt.

**Learning Track (parallel, never blocking).** Gating rule: an L-milestone starts only after the shipping milestone it depends on is green, and must never delay the next shipping milestone — **the lease deadline wins every conflict** (R11).

- **L0** (inside Phase 0): Langfuse wired; eval harness running the bench set in workflow mode.
- **L1** (after Phase 0 exit): extractor + critic A/B on the bench — measure what it catches beyond deterministic VERIFY; keep or kill on data.
- **L2** (after Phase 1 exit): agents-mode pipeline as a LangGraph graph — orchestrator–workers + triage routing; first full dual-mode eval report.
- **L3** (after Phase 2 exit): checkpoint port to LangGraph interrupt/checkpointer; comparison against the hand-rolled runner written up.
- **L4** (any time after Phase 1): the investigator crew (FR12).

*Track exit:* the written eval report in `docs/` — accuracy, tokens, latency, and a verdict on what multi-agent bought — which is the actual deliverable of the learning objective ([§2.5](#25-learning-objectives)).

---

## 20. Decision Log

Chronological. Dates before 2026-07-01 are reconstructed from the drafting sessions; adjust if memory disagrees.

| Date | Decision | Rationale | Sections |
|---|---|---|---|
| 2026-06-28 | Container object named **Hunt** | Short, thematic, reads well in UI copy | §3 |
| 2026-06-28 | Property-centric data model; per-hunt opinion layer | Cross-hunt reuse; re-add costs ~$0 | §8 |
| 2026-06-28 | Scoring is deterministic and LLM-free; extraction always covers full catalog | Trust, free re-scores | §9.3 |
| 2026-06-28 | Floor plans first-class; Unit Group rows show best score + mandatory multi-score indicator | Honesty without mush | §9.4 |
| 2026-06-28 | Planner = manifest builder, not open-ended agent | Debuggability over generality at this scale | §10.4 |
| 2026-06-28 | VERIFY + RECONCILE as explicit agents; deterministic resolution ladder; `resolution_rule` stored | Traceable trust story | §10.5–10.6 |
| 2026-06-28 | Utilities: metro baselines, 120 d TTL, winter-weighted peak, conservative composition default | Never look cheaper than the worst realistic month | §9.5 |
| 2026-06-28 | Cleaned-text caching instead of raw HTML; opportunistic 30 d screenshots | KB not MB; refetch is the recovery path | §8.2 |
| 2026-06-28 | Checkpoints auto-resume at 24 h with declared default + row badge + reopenable | Nothing strands; nothing hides | §10.10 |
| 2026-06-28 | Tiered fetch ladder + per-domain adapter registry; Tier 3 deferred behind Phase 0 gate | Escalate per domain; spend only if reality demands | §10.7, §19 |
| 2026-06-30 | Middle role named **Curator** (rejected: Editor, Moderator) | Data stewardship, not edit-gatekeeping | §4.2 |
| 2026-06-30 | Vision reference images = real images from listings Yusuf has rated | Representative anchoring | §10.8 |
| 2026-06-30 | Frontend UI library: Mantine | Yusuf's choice; primitives map 1:1 to needed views | §7, §13 |
| 2026-06-30 | FastAPI BackgroundTasks for light post-response work only; pipeline stays on the durable Postgres queue | BackgroundTasks lack durability/retry/isolation for minutes-long browser work | §5 |
| 2026-06-30 | All-Anthropic baseline; Gemini as benched contingency behind a provider seam | One bill and shared caching beat pennies unless the bench says otherwise | §11 |
| 2026-06-30 | Jobs + job_events retained permanently → Tasks History tab | FR10; rows are cheap, institutional memory isn't | §8.2, §13.2 |
| 2026-07-01 | Curator name and permanent retention **confirmed** by Yusuf | — | §4.2, §8.2 |
| 2026-07-01 | v1.1 critique pass: NEEDS_REVIEW consolidated into typed checkpoints; pins scoped per unit group; custom-criterion extractions hunt-scoped via nullable `hunt_id`; extractions declared append-only; rescore is one hunt-level job; API conventions (§5.1) and testing strategy (§6) added | Ambiguity a human glosses over is ambiguity an agent implements wrong | §3, §5.1, §6, §8.2, §9.2, §9.4, §10 |
| 2026-07-02 | v1.2: §10.2 Implementation Patterns added — every stage mapped to one of four patterns (forced-schema call, deterministic code, bounded tool loop, vision call); tool registry + per-stage allow-lists; persist-before-advance runner; client seam made explicit | Demystify "agent" so implementation (human or LLM) never builds a loop where a call belongs | §10.2 |
| 2026-07-02 | v1.3: three data-contract shapes pinned — catalog entry (§8.2), score breakdown (§9.3), plan manifest (§10.4) | Shapes shared across subsystems are design, not implementation; prose invites divergent inventions. Procedural snippets remain excluded | §8.2, §9.3, §10.4 |
| 2026-07-03 | Python packaging corrected to a uv workspace: single root lockfile/venv, not per-package lockfiles | Workspace members share resolution; `shared` imports stay consistent across api/worker | §6 |
| 2026-07-03 | v1.4: `domain` enum added to hunts + catalog; buy-domain support specified in backlog with its true costs (incl. inverted anti-bot posture); `shared/` declared domain-blind | Three cheap columns now vs. a painful migration later; everything else is deliberate YAGNI (R10) | §8.2, §18 |
| 2026-07-03 | v1.5: project codename set to **Manzil** (منزل); concrete folder structure with package naming (`manzil_shared`, `manzil_worker`) added to §6; decision log reordered chronologically with full dates | Codename decided at Phase 0 kickoff; prefix makes future rename mechanical | header, §6, §20 |
| 2026-07-03 | v1.6: Manzil declared a dual-purpose learning project. Agents mode added behind `--mode` flag (§10.11): orchestrator–workers, extractor+critic, LangGraph graph + Postgres checkpointer, triage routing, investigator crew (FR12). Shared deterministic truth layer is invariant across modes. Langfuse tracing day one (NFR6); dual-mode eval harness (FR11); Learning Track with hard gating added to §19; R11 registered | Critical path stays boring; ambition lives where failure is survivable; every learning claim settled by evals, not faith | §2.5, §4, §6, §7, §10.2, §10.11, §15, §17, §19 |
| 2026-07-03 | v1.7: subsection links restored to Table of Contents | They were never there to begin with — omission caught during review | §TOC |
| 2026-07-03 | v1.8: phase-executability audit closed five design-level gaps — seed criteria enumeration (§8.2), scheduler ownership via worker tick (§5), queue heartbeat + 5-min orphan reclaim (§8.2), invites via Supabase Auth email (§9.1), bench ground-truth labeling + hardcoded Phase 0 rubric (§19) | The criteria list had silently died in the draft→v1 rewrite; the rest were "scheduled by whom?" holes a developer would hit within days | §5, §8.2, §9.1, §19 |
| 2026-07-03 | v1.9: IMPLEMENTATION.md v1.0 created at Phase 0 kickoff, per the deferred-until-code plan; DESIGN.md sheds nothing — the sibling adds mechanics (interfaces, tunables, prompt/fixture systems, work plans, runbooks) rather than absorbing design | Three-layer authority now live: DESIGN (intent) > IMPLEMENTATION (mechanics) > code (interfaces) | §1, §6 |
| 2026-07-04 | v2.0 (implementation-start baseline, matching IMPLEMENTATION.md v2.0): seed-set review added parking, cooling, dishwasher, min_lease_months — the climate/logistics blind spot — and documented four deliberate exclusions (base rent, year_built, amenities catch-all, floor level/commute) with rationale | Day-one catalog additions cost schema tokens; month-two additions cost a corpus re-extraction pass — the bar is "plausibly ever scoreable" | §8.2 |
| 2026-07-05 | v2.1: engine + schema semantics settled by P0-3/P0-4 implementation. (a) Non-negotiable "acceptable option" defined: `delta ≥ 0` and not a dealbreaker option; unknown values fire the gate. (b) Floor-plan overlay for plan-scoped criteria with conservative `sqft_min`. (c) Match semantics: inclusive `range`; `lt`/`gt`/`range` on numbers or ISO-date strings; object values compare on `rating`; unmatched known values contribute 0; type mismatches never raise. (d) Migration granularity: enums created by the first migration needing them; catalog vocabulary columns are text + check, not enum types; `extractions.criterion_key` has no FK (custom keys aren't catalog rows) and `extractions.hunt_id` gains its FK in 0002. Also fixed the §9.3 example's arithmetic (total 8.5 → 9.5) | A gate that missing data can satisfy is no gate; conservative plan values enforce the never-look-cheaper principle; enum types would put catalog vocabulary behind migrations for zero safety gain | §3, §8.1, §9.3 |
| 2026-07-06 | v2.2: **Source Policy** added — per-submission cross-check control (`trust_link` \| `tier_1` \| `tiers_1_2` \| `tiers_1_2_3` default \| `tier_1_plus_official`), defaulted from hunt settings, persisted on `hunt_listings`, recorded in the plan manifest. Constrains discovered sibling sources only (the submitted URL is always fetched at its required tier); over-cap siblings are skipped at plan time, never escalated; `trust_link` runs single-source with a permanent badge and a documented R3/R4 posture change. The deterministic truth layer is untouched under every policy | User control over the cost/latency/assurance trade per link; a trusted official-site link shouldn't force aggregator scraping, and the choice must stay visible exactly where it weakens the trust story | §3, §4.1, §5.1, §8.2, §10.3, §10.4, §10.7, §13.2, §16 |
| 2026-07-06 | v2.3: **hunt settings contract pinned** (§8.2) — the four settings the design already implied, gathered into one Owner-edited, API-validated object: `default_source_policy` (§10.7), `cost_estimate_mode` (§9.5), `min_confidence` (§9.3, default `medium`), `proximity_mode` (§8.2 catalog). Edit effects specified per key: scoring inputs (`cost_estimate_mode`, `min_confidence`) reuse the rubric-mutation path — version bump + free rescore; `proximity_mode` triggers a field-scoped location refresh; `default_source_policy` affects future submissions only. "Edit hunt settings" added to the §4.2 matrix (Owner-only); settings panel added to the §13.1 settings route. No speculative settings added — every key is read by machinery already in the design | Four subsystems read this object, so its shape is design, not implementation (the v1.3 pinning standard); routing scoring-affecting edits through `rubric_version` keeps score provenance honest — a stored breakdown is fully explained by its version | §4.2, §5.1, §8.2, §9.2, §9.3, §9.5, §13.1, §20 |
| 2026-07-06 | v2.4: **VALIDATE split in two**, resolving the ordering conflict P0-8/10 implementation surfaced (the old diagram put VALIDATE before FETCH, but "is this a rental listing page?" needs fetched content). **VALIDATE_URL** — deterministic P2, pre-fetch, in the old diagram position: scheme + public host (private/loopback refused, an SSRF guard per §16) + not-a-binary, and the single place URL normalization (whitespace, fragments) happens. **VALIDATE** — the content judgment (heuristics first, LLM confirm), now explicitly after FETCH of the submitted source. Phase 0 spine order pinned: VALIDATE_URL → FETCH → VALIDATE → EXTRACT → VERIFY → SCORE | A URL-shaped sanity check costs nothing and belongs before any fetch; a content judgment cannot precede the content — splitting the stage lets both truths hold instead of picking one | §10.1, §10.2, §10.3, §16, §19 |
| 2026-07-07 | v2.5: **Tier 3 built ahead of the census gate, free plans only.** The 2026-06-28 deferral is partially reversed: the managed-unblocker fetcher exists now (Bright Data Web Unlocker default, ScrapingBee alternate, swappable via `MANZIL_TIER3_PROVIDER`, off the ladder until a key is set), but strictly on vendor free tiers (~5k req/mo Bright Data) — **moving to a paid plan is a new §20 decision**, not a config change. What changed since the deferral: the ladder/registry/classifier infrastructure made the fetcher a half-day adapter; free tiers cover Phase 0 volumes entirely, deleting the per-request-cost argument; the census gains a definitive tier-3 column (`hostile_unfetchable` vs `tier3_ok`), turning the P0-14 gate from "build or not" into "keep, and which provider". The Apify structured-actor path stays deferred (second data path, own decision). Stopgap added alongside: FETCH's `source unfetchable` error now carries a deterministic URL-slug search hint (zero LLM) so a human can find the same property on a fetchable source — the manual stand-in for DISCOVER (P3-5) | The infra investment changed the cost of building it, and free tiers changed the cost of running it; capping at free plans preserves the original economic judgment while removing the census blind spot (we can now *measure* whether unblockers beat the hostile five instead of guessing) | §10.7, §19, §20 |
| 2026-07-07 | v2.6: **Embedded structured data mined into the cleaned text; positive content outranks the JS-shell heuristic.** Corpus reality (16 pages, 10 domains): listing sites server-render their *data* even when they don't render their DOM — JSON-LD blocks plus framework state blobs (`__NEXT_DATA__`, `window.__PRELOADED_STATE__`, bare-JSON state scripts) carry the floor plans, unit prices, sqft and fees that never reached tier-1 cleaned text. A deterministic, zero-LLM miner (`fetching/structured.py`) now parses those script tags and appends a pruned digest under `[EMBEDDED DATA]` in the cleaned text; EXTRACT's contract is unchanged (it still receives one text blob). Pruning is list-driven, drop-before-keep: `similar`/`nearby` subtrees are dropped **first** because they carry *another property's* prices (contamination, not just noise); media/URL bulk is scrubbed; digest capped at `EMBEDDED_DATA_MAX_CHARS` (40k). Classifier consequence: the positive cleaned-text check (now also matching rental-fact JSON keys like `"priceLow":`) runs **before** the JS-shell signature, so empty-DOM-but-data-shipping pages settle at tier 1 instead of escalating. JS object literals (unquoted keys, e.g. zumper's inline state) are unminable by design — no JS evaluation, ever; those sites still contribute via JSON-LD | The data was *right there* in every saved page; mining it is a cleaner concern (the stored artifact is cleaned text, §8.2), costs zero LLM calls, fixes tier-1 pages whose rendered text lacked prices, and demotes shell verdicts that were pure DOM-emptiness artifacts. Rejected alternative: per-site JSON adapters — a schema-mapping treadmill; the generic key-signal pruner is domain-blind and fails soft to the old behavior when nothing parses | §7, §10.7, §20 |
| 2026-07-07 | v2.7: **OpenRouter as sole LLM gateway; direct vendor SDKs dropped.** Supersedes the 2026-06-30 all-Anthropic decision in practice: the Gemini adapter (P0-13 bench prerequisite) had already eroded the "one bill, one SDK" argument. OpenRouter restores it — one `OPENROUTER_API_KEY`, one `openai` SDK, model swaps are config string changes (`anthropic/claude-haiku-4.5`, `google/gemini-2.5-flash-lite`, …). Upstream provider pinning preserves deterministic routing and cache stickiness. What's lost: Anthropic Message Batches API (−50% on non-interactive work) — new-listing ingestion is latency-bound (NFR2), hash gating zeroes unchanged refreshes, realistic hunt savings were ~$1–3; NFR1 still holds. Prompt caching passthrough (`cache_control` on stable prefixes) remains load-bearing. ~5.5% OpenRouter fee is cents at this scale | Operational simplicity wins again, without giving up the bench's ability to sweep Gemini candidates; batch was a future Phase 3 lever that never justified maintaining two direct SDKs | §11, §12, §15, §20 |
| 2026-07-07 | v2.8: **The bench/eval kit is a local asset, never repo content.** `fixtures/corpus/` (scraped listing pages) and `fixtures/bench/labels/` (hand labels about those exact snapshots) are gitignored; only `.gitkeep` placeholders are tracked so fresh clones keep the directories and the corpus sweep test skips cleanly (`corpus_pages()` hardened to return `[]` when the dir is absent). `bench/manifest.md` (methodology, no page content) and the smoke replay fixture stay tracked; other record-mode artifacts are ignored (keyed to local corpus content, carry page evidence quotes). CI provably reads only the committed synthetic `fixtures/pages/`. Consequences accepted and mitigated: bench reproducibility is single-machine, and snapshots of since-delisted or hostile pages are unrecoverable — so the kit gets an explicit backup runbook (IMPLEMENTATION §8) and the P0-11 exit metric is reworded from "committed" to "present locally + backed up"; P1-1's dev-seed retargets the committed synthetic pages. Also **reviewed and reaffirmed unchanged**: the 2026-06-28 cleaned-text retention line (facts in `extractions`, gzipped cleaned text in Storage, raw HTML transient) — facts answer *what we believe*, cleaned text answers *what the page said*, and dropping the text layer would collapse every re-extraction (model migrations, mid-hunt custom criteria, evidence audits) into a refetch against sites that block and listings that vanish. The repo decision is orthogonal to that production layer: test corpus in git vs cleaned text in the user's RLS-scoped Supabase are different content, different stores, different exposure | Saved pages are copyrighted third-party content that embeds vendor API keys and tracking IDs (observed in the saved corpus) — unpublishable in an open repo regardless of size; and the labels are meaningless without the exact snapshots they grade, so they travel together. Keeping the kit out of git costs only single-machine reproducibility, which the backup runbook bounds | §6, §19, §20 |

---

## 21. Open Questions

1. **`resolve_dispute` auto-resume default** — 24 h timeout is settled policy for all checkpoint kinds; the default *action* for reconciliation disputes on gate criteria ("accept official at low confidence" vs "leave unknown") stays open until the first real dispute appears in Phase 0 data.
2. **Public product name** — Manzil is the codename; decide whether it is also the public-facing name before anything user-facing ships (Phase 1).
3. **Agents-mode default?** — whether any agents-mode component graduates into the default path is deliberately unanswerable until the L2 eval report exists; the adoption rule in §10.11 governs.