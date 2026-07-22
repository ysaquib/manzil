# Phase 3 Implementation Plan — Full Agent System

Status: **formally entered 2026-07-18** (Phase 2 exited same day; the §7 table
this plan finalizes at entry is finalized — IMPLEMENTATION 2.0.56, DESIGN §20
2026-07-18). Waves A and B active.
**P3-2 and P3-3 landed 2026-07-12** (ahead of entry, Yusuf-directed; reviews
green — see IMPLEMENTATION §9 2.0.36/2.0.37 and DESIGN §20 2026-07-12).
**P3-4 landed 2026-07-12** (DEDUPE + `resolve_dedupe` + `split_property`;
verifier CONFIRMED — IMPLEMENTATION §9 2.0.41, DESIGN §20 2026-07-12; note the
§20 correction: DEDUPE runs post-EXTRACT, not pre-FETCH as §10.1 once drew). A
security follow-up from P3-3's review was cleared before the live loop (see the
SSRF row in §1). **P3-5 landed 2026-07-21** (OpenRouter native search, exact
same-Property candidate filtering, official link-only persistence, tier/family
slate, Source Policy edits, and reasoned single-source presentation;
IMPLEMENTATION 2.0.70 / DESIGN §20). **P3-5/P3-6 rescoped 2026-07-13**
(DESIGN §20 v3.2 — tier-diverse slate, official site as stored link +
escalation arbiter, syndication-family voting, bounded escalation ladder); §7
and §8 below are rewritten to that decision. Originally written 2026-07-11. Written against
DESIGN.md (working tree, 2026-07-11 — §5, §8.2, §9.5, §10, §11, §12, §14, §15,
§16, §17, §18, §19, §20 v2.9) and IMPLEMENTATION.md §7's Phase 3
implementation-prep draft (2026-07-11), which this plan elaborates and — per the
"entering a phase means revising its table first" rule — finalizes at entry.
Code facts verified against the working tree on 2026-07-11 (Phase 2 batch,
uncommitted).

**P3-SC2 landed 2026-07-21** (unified append-only scoped Extraction,
Source-local Floor Plan identity, centralized current views/effective resolver,
scoped Overrides, authoritative refresh, split/merge/RLS/UI consumers;
IMPLEMENTATION 2.0.71 / DESIGN v3.9). Next scoped task: P3-SC3, then P3-SC4
before the P3-5/P3-SC join at P3-6.

**Security note for execution:** Phase 3 feeds untrusted page content into more
machinery (tool loops, web search, image pipelines) and adds external API
credentials. P3-5 (DISCOVER tool loop), the `fetch_page` tool, and every new
credential surface follow the §16 controls and get security review (the
security-executor role or equivalent) — the zero-tool rule for extraction stages
is a hard invariant, not a default.

## 0. Scope

**In scope (DESIGN §19 Phase 3):** planner manifests; DISCOVER multi-source +
RECONCILE ladder; VISION with the versioned reference set; Maps/reviews/safety
ENRICH; utility-baselines job; custom-criteria routing; checkpoints complete
(incl. the 24 h auto-resume sweep); refresh TTLs + content-hash gating; Compare
view; mobile sheet polish; Tier-3 adapters **only as the Phase 0 census gate
demands**; apartmentratings.com as ratings stage 2.
**Exit:** NFR1–NFR4 measured and met on the live hunt (measurement plan in §14).

**Explicitly out of scope** (per AGENTS.md phase discipline — do not build):
- Everything in DESIGN §18: Apify structured actors, automated discovery/alerts,
  off-market detection, zip-level baselines, traffic-window commutes, weighted /
  multiple rubrics, export/sharing, screenshot-based extraction, general ratings
  sites (Yelp et al. — ratings stage 3), notifications, buy-domain activation.
- Worker process isolation **unless a §5 trigger is observed** (DESIGN v2.9):
  P3-1 stays parked until repeated API memory/restart/502 impact, material
  latency impact, a concurrency requirement, or an always-on scheduling
  requirement is demonstrated.
- Learning track: L1 (extractor+critic) unlocks at **Phase 0** exit, L3
  (LangGraph checkpoint port) at Phase 2 exit — both proceed in track order,
  get their own table in IMPLEMENTATION §7 when they unlock, and never block
  shipping (R11: the lease deadline wins every conflict). No agents-mode code
  lands as part of any P3 task.

**Phase 0 tail:** P0-11..14 remain open at drafting time. They gate pieces of
this phase (entry gates below) but not its start — Waves A/B need neither the
census verdict nor the model pin.

---

## 1. Entry gates (from the §7 prep draft, restated with resolutions)

| Gate | Blocks | Resolution |
|---|---|---|
| Phase 2 human exit (P2-10) | formal entry | Yusuf confirms; update DESIGN §19 / AGENTS.md status lines |
| P0-14 census verdict | P3-14 existence + scope; fetch-tier choice in P3-15 | finish P0-11..14; then retain/rescope/delete P3-14 with a §20 entry |
| P0-14 model-pin verdict | default pins for new LLM stages (§2.6) | baseline Haiku/Sonnet pins stand until the bench says otherwise; changing any pin is a §20 entry + bench rerun |
| Google Maps key (restricted, server-side) | P3-3 and everything downstream of geocode | create the GCP project, restrict the key to Geocoding/Places/Routes, add `GOOGLE_MAPS_API_KEY` to worker env + `infra/.env.example` |
| DISCOVER web-search provider | P3-5 | **cleared 2026-07-21:** native `openrouter:web_search`, capped at three searches and $0.01/search; live passthrough + ten-listing yield bench recorded in §20 |
| Vision reference set (human asset) | P3-7 quality gate | Yusuf hand-picks 3–4 real images per rating level from listings he has rated; versioned per §10.8 before the prompt is validated |
| Worker-isolation trigger | P3-1 | not observed; task stays parked (§0) |
| Fetcher-layer SSRF guard | ~~P3-5 and P3-10~~ — **HTTP path landed 2026-07-12** (DESIGN §20; IMPL 2.0.40): `fetching/ssrf.py` deny-set + tier-1 IP-pinning closes the DNS-rebinding TOCTOU. Two smoke checks before wiring Chromium into a live loop: manual tier-2 browser smoke test + one live-HTTPS fetch confirming the pin's cert path |

---

## 2. Cross-cutting decisions

### 2.1 Manifest-driven runner (the cursor problem, solved once)

`runner.py:40-47` walks a fixed `PHASE0_STAGES` list with an **integer cursor**
(`state.py:126-152`). Phase 3 inserts stages before, between, and after the
existing six (PLAN, DEDUPE, DISCOVER, RECONCILE, VISION, ENRICH, CUSTOM_MATCH)
— an index cursor would silently mis-resume every parked or in-flight job the
moment the list changes shape.

Decision: **the plan manifest becomes the runner's stage list.** PLAN (P3-2)
writes `state.plan.stages` (the §10.4 pinned shape); the runner walks
`state.plan.stages[state.cursor:]` by **stage name**, resolving names through a
registry dict. A RunState with `plan is None` (every pre-P3 snapshot, and
Phase 3 jobs that predate PLAN in the walk) falls back to the legacy list —
old parked jobs resume exactly as before. This also makes skip decisions
first-class: a stage the planner skipped is simply absent from the run's list,
recorded under `plan.skipped` with its reason, and visible in the Tasks UI.
Persist-before-advance is untouched.

### 2.2 Tool registry + DISCOVER's search (landed)

P3-3/P3-5 built the §10.2 mechanics exactly as pinned: a name→callable registry
with a small `@tool` decorator deriving JSON schemas from signatures
(`llm/tools.py`), per-stage **allow-lists** (extraction stages get zero tools —
§16 hard invariant), the turn-budgeted loop shape from §10.2 verbatim
(`AgentBudgetExceeded` is a real outcome), and every tool call/result logged as
a `job_events` row. `fetch_page` routes through the existing tier ladder so
tool-using stages inherit the registry, rate limits, and politeness — and it
runs the VALIDATE_URL host checks first, so a tool loop cannot be steered into
fetching private/loopback targets (SSRF posture identical to submission).

**Search provider:** landed as OpenRouter's current native
`openrouter:web_search` server tool on the pinned Anthropic route — zero local
handler, maximum three searches, five results/search and twelve total/turn,
$0.01/search at landing. The older OpenRouter `web` plugin is deprecated and
was not used; no new search credential was added. Provider-hosted events flow
through the same Job Event sink as local tools. When OpenRouter's compatible
response omits its native search count/citations, one opaque search event is
recorded for the DISCOVER turn; provider-reported total cost remains
authoritative. Search snippets are untrusted input and candidate identity is
filtered before persistence (DESIGN §16/§20 2026-07-21).

### 2.3 Maps: three tools, forever-cache in existing columns, no new tables

`geocode`, `places_nearby`, `commute_time` are custom tools (P3-3) in one
module (`worker/src/manzil_worker/enrich/maps.py`) behind `httpx` — no Google
SDK (NFR5; the client seam rule covers LLM SDKs, this extends the spirit:
one thin module owns the HTTP surface). Caching uses what the schema already
has: geocode results land on `properties.place_id/lat/lng` (columns exist,
unwired — §20 2026-07-09 audit closes here), and computed
distances/commutes/ratings land as ordinary `extractions` rows
(`refresh_class` `location` is immutable, `reviews` is 30 d — §14 owns
re-computation, so a separate cache table would duplicate the extraction
store). A geocode with `place_id` already set is a no-op read — that is the
"cached second geocode is $0" done-when.

### 2.4 Scheduler tick — one mechanism, three duties, landed incrementally

DESIGN §5 pins scheduling as a ~5-minute tick inside the worker loop: SQL
queries answer "what is due", inserts/updates follow. `run_worker_loop`
(`queue.py:581-629`) gains a `scheduler_tick()` called when the last tick is
>5 min old (tunable `SCHEDULER_TICK_SECONDS` in `shared/config.py`, flat-caps
convention). Duties arrive with their owning tasks: checkpoint 24 h sweep
(P3-11, first consumer — builds the scaffold), TTL refresh scan (P3-12),
utility-baseline 120 d job + 30 d screenshot retention cleanup (P3-9/P3-7).
Missed ticks catch up on restart; nothing is minute-critical.

### 2.5 Refresh jobs: "own" semantics extend, no schema change

The Phase 2 rule (own listing = `hunt_listings.added_by`; hunt-level jobs are
Owner-managed) covers refresh unchanged: `POST /listings/{id}/refresh` creates
a listing-scoped job (owned by the listing's adder, manageable per §4.2);
`POST /hunts/{id}/refresh` fans out one listing-scoped job per listing under
the per-domain rate limiter, enqueued by Owner/Curator-permitted mutation. The
Phase 2 plan deferred `jobs.created_by` to "if Phase 3 needs it" — it does not:
no Phase 3 flow needs to know who *clicked* refresh beyond what listing
ownership already answers. RLS: the existing `jobs` INSERT policy (any member
of the hunt) already admits refresh rows; no migration needed beyond the enum
value `refresh` that `job_type` has carried since 0002.

### 2.6 New LLM stages ride existing pins; every change is benched

`llm/config.py` already pins `discover`, `vision`, `reconcile_equivalence`,
`custom_match`, `plan_assist` (baseline: Haiku workhorse, Sonnet for
vision/discover judgment). Phase 3 turns those pins live but does not choose
models — if P0-14's bench argues for a swap, that is its own §20 entry and a
bench rerun (the §5 testing rule). Every new prompt (discover judgment,
equivalence normalization, vision, review synthesis, safety synthesis, routing
classification) enters the record/replay fixture system from its first test.

### 2.7 Cost honesty: persist the tally

`jobs.cost_actual_usd` exists and is never written — RunState tallies
`cost_usd` in memory and the History tab renders a column of zeros. P3-2 makes
the terminal-state projection write the tally (and PLAN's `est_cost_usd` makes
the manifest's estimate visible beside it). NFR1 is *measured*, per-run, from
this column plus Langfuse — not asserted.

### 2.8 Multi-source state and identity ordering

`RunState.sources` is already a list (single-element today). P3-4..P3-6 keep
the wave-B order — DEDUPE (canonical identity) before DISCOVER (siblings)
before fan-out/RECONCILE — because merging properties *after* multi-source
extractions exist multiplies the split problem. RECONCILE finally writes
`extractions.resolution_rule` (column exists, never written; single-source runs
write `single_source` **from RECONCILE**, per the 2026-07-09 audit note that
the projection must not forward-implement it). Disputed values follow §10.6's
final rung (ladder v2, §20 2026-07-13): conservative value stored `disputed`,
candidates retained in jsonb, the listing derives the Problematic badge, and
the gate-bearing case raises `resolve_dispute` — whose auto-resume default is
DESIGN's **open question #1**: the first real dispute decides it, recorded in
§20 (until then the sweep leaves `resolve_dispute` parked rather than guessing
a default; `confirm_value`/`resolve_dedupe` defaults are declared per §10.10).

### 2.9 Images and screenshots: Storage buckets, existing columns

P3-7 wires what the schema has waited for: `property_images` rows +
`property_sources.image_urls`/`screenshot_path` (all present, unwired).
Supabase Storage gains two buckets — `property-images` (WebP, ≤10/property,
~1024 px) and `screenshots` (opportunistic tier-2 captures, 30 d retention via
the §2.4 tick). Buckets are private; reads go through short-lived signed URLs
minted by the API (RLS posture: images are global facts like extractions —
readable by any authenticated member, written only by the worker).

### 2.10 Frontend deltas already banked

Two prep-table assumptions are already shipped and drop out of P3-5/P3-13
scope: the submit control's Source Policy `Select`
(`SubmitUrlControl.tsx:54-61`, persisted through POST /listings) and the mobile
bottom-sheet drawer (`ListingDetailDrawer.tsx:108,189`). Inert badge slots
(`ListingBadges.tsx:4-13` — Stale / AutoResolved / SingleSource return null)
were built as sockets; Phase 3 tasks fill them rather than adding new cells.

---

## 3. Task table (revises IMPLEMENTATION §7's prep draft at entry)

Waves per the prep draft: **A** foundations → **B** identity/sources →
**C** evidence/enrichment → **D** lifecycle/UX → **E** conditional sources.
Full task detail in §4–§13; every task below carries its what/why.

| # | Wave | Task | Why |
|---|---|---|---|
| P3-1 ⚠ | — | Optional worker isolation | parked; §5 trigger only (DESIGN v2.9) |
| P3-2 | A | Planner v1 (ingest manifests) + manifest-driven runner + cost persistence | resumable multi-stage runs need a stage list that travels with the job; debugging and NFR1 need the plan and the bill visible |
| P3-3 | A | Maps tools + tool registry + forever-cache | geocode is the substrate for DEDUPE, ENRICH, and Places ratings; the tool registry is the §10.2 mechanics everything P3 shares |
| P3-4 | B | DEDUPE + `resolve_dedupe` + `split_property` | shared global facts are only safe if two URLs for one building become one property — and a wrong merge must be reversible (R5) |
| P3-5 ✅ | B | **Landed 2026-07-21:** DISCOVER official-link capture + tier-diverse slate + candidate pool + Source Policy enforcement + reasoned single-source badge | cross-source outvoting is the core trust mechanism (R3/R4); tier/family diversity is what makes the votes independent; policy caps keep the user in control of the cost/assurance trade |
| P3-6 | B | Multi-source fan-out + RECONCILE ladder v2 + bounded escalation | conflicting sources need a deterministic, recorded resolution — this is where `resolution_rule`, `disputed`, and the escalation ladder become real |
| P3-7 | C | Images + VISION with versioned reference set | kitchen/flooring quality are rubric criteria only vision can score; reference anchoring is the consistency control (R6) |
| P3-8 | C | ENRICH: proximity, commute, Places ratings (priority slice), safety | location and reputation criteria are the remaining unscoreable catalog rows; Places is near-free and covers almost every complex |
| P3-9 | C | Utility baselines job + full all-in composition | the all-in number is the tool's core promise; winter-weighted estimates make unlisted utilities honest instead of invisible |
| P3-10 | C | Custom criteria authoring + CUSTOM_MATCH dispatch | the catalog can't anticipate every hunt's dealbreaker; authoring-time routing keeps run-time dumb and cheap |
| P3-11 | D | Checkpoints complete: screenshot UI, 24 h sweep, reopen/re-score | checkpoints only work if ignoring them costs nothing — auto-resume with a visible badge means nothing strands and nothing hides |
| P3-12 | D | Refresh: TTLs, hash gating, field-scoped partial, planner refresh mode | fresh data without re-paying extraction; hash gating is the single biggest cost lever after caching (§15) |
| P3-13 | D | Compare view + mobile polish | FR9 — the decision endgame is comparing finalists, and it happens on phones |
| P3-14 ⚠ | E | Tier-3 adapters per census verdict | spend on hostile domains only where the census proves inventory lives behind them |
| P3-15 | E | Ratings stage 2: apartmentratings.com | renter-specific signal Places lacks; lands as a second provenance-carrying extraction, RECONCILE owns disagreement |

---

## 4. P3-2 — Planner v1 + manifest-driven runner (Wave A)

**What/why:** build the PLAN stage that emits the §10.4 manifest for ingest
jobs, convert the runner to walk the manifest's stage list (§2.1), and persist
`jobs.plan` + `jobs.cost_actual_usd` (§2.7). This is the substrate every later
stage insertion rides on — without it, each new stage is a resume-breaking
change; with it, skips and costs become visible in the Tasks UI.

**Files:** `worker/src/manzil_worker/stages/plan.py` (new);
`runner.py` (manifest walk + legacy fallback); `state.py` (plan already a
field — type it to the pinned shape); `queue.py` (ingest dispatcher runs PLAN
first; terminal projection writes `plan` + `cost_actual_usd`);
`shared/config.py` (planner tunables). Deterministic-first per §10.4: TTL
lookups, hash checks, registry reads are plain code; the single `plan_assist`
LLM call (already pinned) fires only for genuine judgment (ranking >3
candidate sources) — Phase 3 ingest of a brand-new property has ≤3 sources, so
most manifests cost zero LLM.

**Scope guard:** ingest manifests only. Refresh-mode planning (TTL/refresh-
scope resolution) completes in P3-12, which builds the inputs it reads. The
manifest for a Phase-3-early ingest is honest about what exists: stages list =
the live stage set at that moment.

**Done when:** ingest of an already-known property plans `action: skip,
why: hash_fresh` for its unchanged source; the Tasks history renders the
manifest (the P2-7 slot already renders `plan` when non-null); a completed
job's `cost_actual_usd` matches the Langfuse session total; a pre-P3 parked
job (fixture) still resumes through the legacy fallback.

## 5. P3-3 — Maps tools + tool registry (Wave A)

**What/why:** implement the §10.2 tool mechanics (`@tool` registry, allow-
lists, budgeted loop, `call_agent`) and the three Maps tools with forever-
caching (§2.3). Pulled ahead of its consumers because DEDUPE and ENRICH both
read geocode, and the registry is shared plumbing for DISCOVER and location
custom criteria.

**Files:** `worker/src/manzil_worker/llm/tools.py` (registry + decorator +
loop); `llm/client.py` (`call_agent` implemented; per-stage allow-lists
enforced here, not in stage code); `enrich/maps.py` (geocode / places_nearby /
commute_time via httpx; retries + quota-aware backoff);
`infra/.env.example` (`GOOGLE_MAPS_API_KEY`). Every tool call and result →
`job_events` (the vocabulary gains `tool_called` — one migration extending the
check constraint). Record/replay: Maps responses get the same fixture
treatment as LLM calls so CI never touches Google.

**Security:** key server-side only; `fetch_page` tool applies VALIDATE_URL's
host checks (§2.2); tool loops exist for DISCOVER and location custom criteria
— nothing else (AGENTS.md hard rule, enforced by the allow-list table having
exactly two non-empty rows).

**Done when:** second geocode of the same property is $0 and instant
(`place_id` short-circuit); a tool loop over budget raises
`AgentBudgetExceeded` and the job fails cleanly with its events intact;
extraction stages provably resolve to an empty allow-list (test asserts).

## 6. P3-4 — DEDUPE + split (Wave B)

**What/why:** name+address → geocode → match against `properties` (<100 m AND
name-similar → auto-merge; gray zone → `resolve_dedupe` checkpoint), plus the
`split_property` admin operation. Global fact sharing (one property, many
hunts) is only correct if identity is; and because wrong merges poison shared
data (R5), the unmerge path ships the same day as the merge path.

**Files:** `stages/dedupe.py` (new; consumes `property_identity` from the
P1-era EXTRACT block — the input DEDUPE was designed to read);
`worker/.../ops/split_property.py` + a CLI verb `manzil split-property`
(admin-only, service-role; re-points sources/extractions/images to a new
property row and re-scores affected hunts); name similarity via rapidfuzz
(already a dependency from VERIFY). Gray zone raises the pinned
`CheckpointPrompt` with `kind=resolve_dedupe`, default = "keep separate" (the
conservative default: a false split is recoverable by re-merge, a false merge
is the expensive direction).

**Done when:** a seeded near-duplicate pair (same building, two aggregator
URLs, slightly different names) → checkpoint; answering "merge" produces one
property with both sources; `split-property` restores two clean properties and
both hunts' scores recompute.

## 7. P3-5 — DISCOVER + Source Policy enforcement (Wave B)

**Landed 2026-07-21** — implementation truth is DESIGN v3.8 and
IMPLEMENTATION 2.0.70. The canonical ten-listing live search-seam bench found
the correct official URL for 10/10 and at least one sibling for 10/10, without
fetching an official site; this validates discovery yield, not P3-6 extraction
or reconciliation quality.

**What/why (rescoped 2026-07-13, DESIGN §20 v3.2):** the bounded tool loop
that (a) finds the **official site and stores it as a link only** —
`property_sources.is_official`, displayed in the drawer's sources section,
never fetched by default (official pages are the least standardized extraction
surface; they enter later as escalation's arbiter, §10.6), and (b) builds the
**slate**: the submitted URL plus one same-property sibling per permitted
census fetch tier (other than the submitted domain's), each from a distinct
**syndication family**, plus a **ranked candidate pool** that P3-6's
escalation round draws from without re-searching (this pool is what finally
activates §10.4's >3-candidate planner judgment call). Tier/family diversity
is what makes reconciliation votes independent — the census aggregators
cluster into feed-sharing networks (Zillow/Trulia/HotPads; CoStar's
Apartments.com/ForRent), and three echoes of one feed must not read as a
majority. Plan-time Source Policy enforcement stays exactly as pinned in
§10.7: `trust_link` removes DISCOVER entirely; a tier above the cap
contributes no slot (`skip: policy_tier_cap`); the tier-3 slot also requires a
configured provider key (census gate); a missing tier substitutes from the
next cheaper one, recorded in the manifest.

**Prerequisite (cleared):** the fetcher-layer SSRF guard landed 2026-07-12 and
both required live smoke checks passed 2026-07-17 before DISCOVER was wired.
The browser check found and closed the redirect-chain gap; the accepted residual
tier-2 DNS-rebinding window is recorded in DESIGN §20.

**Files:** `stages/discover.py` (P3 pattern — search tool + `fetch_page`,
turn-budgeted, `DISCOVER_MAX_TURNS` tunable; emits slate + official link +
ranked candidate pool into RunState); `stages/plan.py` (policy caps as above;
pool ranking via the pinned `plan_assist` call when >3 candidates);
`docs/hostile-domain-census.csv` gains a **`syndication_family`** column
(slate-building never picks two same-family sources; RECONCILE counts one
vote per family); search provider per §2.2 (§20 entry at landing); frontend:
fill the `SingleSourceBadge` slot (`ListingBadges.tsx`) — three recorded
reasons, `trust_link` ("not cross-checked — by choice"),
`discover_exhausted` ("only one site lists this property"), and
`discover_failed` (discovery was unavailable or exhausted its bounded budget)
— and the drawer's
sources section gains the policy (changeable — relaxing enqueues a refresh
that discovers newly allowed sources, per §13.2) plus the always-shown
official link. The submit `Select` already ships (§2.10).
`property_sources.is_official` finally gets written (DISCOVER classifies it;
the 2026-07-09 audit named this the arrival point) — with `last_fetched_at`
null until escalation ever fetches it.

**Done:** official link stored + displayed for 100% (10/10) of the local bench
complexes **with zero fetches of it**; the slate holds one sibling per
permitted tier with no syndication family twice; `trust_link` run has zero
DISCOVER job events and wears the permanent badge; a DISCOVER that finds no
siblings completes single-source with reason `discover_exhausted`; an
over-cap sibling appears in the manifest as skipped; the census-named hostile
domains are *not* fetched at sibling positions when the policy caps below
their registry tier. Synthetic, persistence, API-permission, and refresh tests
pin those mechanics. A prefaced fenced-JSON response seen live is accepted only
when the fenced body is itself one valid object; arbitrary brace scraping stays
forbidden.

## 8. P3-6 — Multi-source fan-out + RECONCILE ladder v2 (Wave B)

**What/why (rescoped 2026-07-13, DESIGN §20 v3.2):** FETCH/EXTRACT/VERIFY run
per slate source; RECONCILE merges via the rewritten §10.6 ladder (LLM only
for semantic equivalence), stamping `resolution_rule` on every reconciled
extraction and handling `disputed` + `resolve_dispute`. Ladder v2, per
criterion: override → conservative-in-band tolerance collapse (3% rent / 5%
sqft) → supermajority (≥2/3 of **family-deduped** votes; freshest fetch
speaks for its family) → *escalation, decision-relevant fields only* —
official-site fetch+extract as arbiter (medium-or-better verified confidence
settles; once per job, policy-tier-permitting), then **one** sibling round (≤3
new pool sources, tier-diverse, family-distinct; rungs re-run over the
widened votes) → majority >50% (ties: higher verify confidence, then fresher
fetch) → conservative value stored `disputed` with candidates in jsonb.
Decision-relevant = gate-bearing in any using hunt, any option/unknown delta
< 0, or an all-in component. Round sources extract the full catalog
(append-only, reusable) but vote only on still-unresolved fields — settled
fields never reopen within a run. Worst case: ~7 extractions (~$0.20) against
the ≤3 baseline.

**Escalation mechanics:** RECONCILE appends the round's stages to
`plan.stages` and records it under `plan.escalation` (trigger fields, sources
added, rung reached) — persist-before-advance, so an escalated run resumes
mid-round and the Tasks UI shows what the run bought and why. Escalation state
(rounds used, sources tried) lives in RunState. Tunables:
`ESCALATION_MAX_SIBLING_ROUNDS` (1), `RECONCILE_SUPERMAJORITY` (2/3), numeric
tolerances.

**Files:** `stages/reconcile.py` (new; ladder as plain code;
`reconcile_equivalence` LLM call already pinned); `runner.py`/`stages/fetch.py`
/`extract.py`/`verify.py` (per-source iteration — RunState.sources already a
list; each source carries its own cleaned text, extractions, verify flags);
projection writes reconciled values + rule + `disputed` candidates jsonb;
frontend: `ProblematicBadge` derived from any `disputed` field (table row +
drawer), drawer provenance shows the winning rule and candidates.
Single-source runs emit `resolution_rule: single_source` from RECONCILE
(§2.8), both reasons.

**Done when:** a conflicting fixture pair resolves per the tolerance/
supermajority rungs with the rule recorded; a fabricated no-supermajority case
on a gate-bearing field escalates official-first, then exactly one sibling
round, then raises `resolve_dispute` with one-click candidates and the
Problematic badge; settled fields provably keep their round-1 resolution when
round sources disagree; a worst-case run shows ≤7 extractions and its
`plan.escalation` record in the Tasks history; the detail drawer shows the
winning rule in provenance.

## 9. P3-7 — Images + VISION (Wave C)

**Status 2026-07-13:** P3-7a deterministic substrate landed; P3-7b remains
fail-closed on the human reference asset. See
`docs/p3-7-vision-guide.md` for the exact completion and rollout gates.

**What/why:** download listing images (≤10, WebP, ~1024 px) into Storage,
wire `property_images` + screenshot capture/retention (§2.9), and run the P4
vision call anchored by the versioned reference set — because
`kitchen_quality`/`flooring_quality` are catalog criteria nothing else can
score, and un-anchored vision ratings drift (R6).

**Files:** `stages/image_fetch.py` + `stages/vision.py` + `enrich/images.py`
(discover, SSRF-screened download, hash, convert, cap); `llm/client.py`
`call_vision` implemented (images as content blocks,
same record/replay discipline — fixtures store image hashes, not bytes);
reference set under `worker/prompts/vision_refs/` (versioned with the prompt;
changing it is a reviewed migration: re-run, diff, accept); tier-2 fetcher
writes `screenshot_path`; scheduler tick (once P3-11 lands the scaffold)
deletes screenshots >30 d. Per-image detail → `property_images
.vision_assessment`; the aggregated per-criterion rating → `extractions` with
contributing image paths as evidence. Frontend: drawer gains the image gallery
with per-image assessments (§13.2).

**Skip discipline:** IMAGE_FETCH compares the complete set of normalized-byte
hashes after FETCH. Equality → the manifest's `skipped.VISION =
images_unchanged`, which the runner honors before dispatch/cost; stable URL with
changed bytes reruns, changed URL with identical bytes skips. That, not prompt
cleverness, is the cost control (§15 lever 3).

**Done when:** two consecutive runs with unchanged images → zero vision spend
(manifest shows the skip); vision ratings for a bench property land within ±1
of Yusuf's own rating on the anchored scale; gallery renders with assessments.

## 10. P3-8 — ENRICH: proximity, commute, ratings stage 1, safety (Wave C)

> **Landed 2026-07-18 ◐** (IMPLEMENTATION 2.0.58) with one deviation from this
> section, ruled in DESIGN §20 2026-07-18: `location_safety` ships as an
> **override-first A+..F placeholder** (no web-search synthesis; the assessor is
> the deferred P3-17 safety module). The interim proximity-flip path is a
> `refresh` job (`scope: enrich`) re-running the location slice only — zero LLM
> spend, as the done-criterion requires. ◐ pending one live Detroit-metro run.

**What/why:** the remaining catalog criteria go live — `grocery_proximity`
(honoring `settings.proximity_mode`, edit → field-scoped location refresh),
`management_reviews` via **Google Places rating + one small-model review
synthesis** (the §10.12 priority slice — near-free, near-universal coverage,
and the gate for P3-15), and `location_safety` as an explicitly low-confidence
synthesis (R8: ship it labeled, don't sink a week). Reputation and location
are decision-relevant criteria the rubric already knows how to weigh; this
task just feeds them.

**Files:** `stages/enrich.py` (deterministic dispatch over enrichable
criteria; Maps tools from P3-3; Places Details call geocode-keyed);
`prompts/` review-synthesis + safety-synthesis (record/replay from first
test); hunt-settings edit path: `proximity_mode` flip enqueues the
field-scoped location refresh (needs P3-12's field-scope plumbing only for
the *scoped* variant — until P3-12 lands, the flip enqueues a full ENRICH
re-run, cheap because Maps responses are cached and that interim is recorded
in the task notes, not silently). Safety renders with a confidence label in
the drawer, never as bare fact.

**Done when:** Places rating populates `management_reviews` with provenance;
proximity-mode flip re-enriches with zero LLM spend (cached geocodes, Maps
calls only); safety shows its confidence framing in the UI; a Detroit-metro
bench property scores its location criteria end-to-end.

## 11. P3-9 — Utility baselines + full all-in composition (Wave C)

> **Landed 2026-07-18 ◐** (IMPLEMENTATION 2.0.59, DESIGN §20 2026-07-18). As
> this section required, P3-9 landed the scheduler-tick scaffold (P3-11/P3-12
> add duties) and the §20 entry records the jobs-vs-tick distinction. Deltas
> ruled at landing: search-less baselines pass; P3-5 now exposes shared search
> plumbing, but adopting it here remains a separate output-affecting follow-up; graduated
> unknown rule (no-baselines metro → v1 slice + badge; partial coverage →
> withheld total); billed fee suppresses the matching estimate; metro =
> `properties.city`; composition detail on `hunt_listings.all_in_components`.
> ◐ pending the first live baselines pass + the owed bench re-run.

**What/why:** the scheduled metro-level baselines job (one LLM+search pass per
metro over utility-rate sources, 120 d TTL, winter-weighted `monthly_high`)
and the completion of §9.5 composition: `all_in = rent + mandatory_fees +
pet_monthly + Σ(estimated non-included utilities)`, every component tagged,
conservative by default. Composition v1 (rent + pet costs) shipped 2026-07-10;
this closes the gap between "the number we show" and "the number you'll pay" —
the tool's core promise.

**Files:** `worker/.../enrich/utility_baselines.py`. The baseline pass is
**not a `jobs` row** — `jobs.hunt_id` is NOT NULL (migration 0005) and this is
global, hunt-less maintenance. The scheduler tick spawns it directly as a
guarded asyncio task (one per due metro, lock-protected, writing
`utility_baselines`); if it dies, the next tick retries — a 120 d cadence
needs no queue durability. Record this jobs-vs-tick distinction in the P3-9
§20 entry, since it's the first tick duty that isn't a job insert;
`stages/pet_costs.py` grows into the full composer (mandatory fees from the
extraction block that already exists; baseline application per `heating_type`
— electric heat uses the electric-heat winter figure, unknown takes the worse
and flags it; `occupants` scaling gets its reserved reader);
`settings.cost_estimate_mode` flip already rides the rescore path. Frontend:
all-in cell renders the estimated portion visually distinct
(`$1,845 (~$210 est.)` per §13.2) + "fees unverified" badge; drawer shows the
component breakdown with tags.

**Done when:** a listing with no stated utilities shows a winter-weighted
estimate, tagged `estimated`, overrideable; mode flip conservative→median
rescores without any refetch; a fully-unknown utility contributes
`unknown_delta` and a badge, never a number.

## 12. P3-10 — Custom criteria authoring + dispatch (Wave C)

**What/why:** the §9.2 authoring flow — name → description → one cheap LLM
routing classification (`requires_tool`) → **user confirms the routing with
one click** → options like any criterion — and CUSTOM_MATCH's dumb dispatch
(`null`→text, `maps`→ENRICH-style call, `vision`→vision pass,
`web_search`→scoped search). Custom criteria are how the catalog stays small
while every hunt's idiosyncratic dealbreaker (floor level, commute to a
specific address) still scores; authoring-time confirmation is what catches
misroutes when they're free to fix.

**Files:** API `rubric/` (custom_def rows already accepted by PUT —
`rubric/service.py:70-108`; adds routing-classification endpoint + validation
that `requires_tool` was human-confirmed); `stages/custom_match.py` (dispatch
only — "no runtime routing intelligence exists or should be added", §10.9);
custom values land as hunt-scoped extractions (`hunt_id` set — the leak-proof
namespace from §8.2, whose RLS policy P2-1 already scoped); frontend rubric
editor gains the authoring flow (`rubricDraft.ts` has carried the dormant
`custom_def` field since Phase 1). Location-type customs run through the
bounded tool loop (the second of exactly two allowed loops).

**Done when:** a commute-to-address criterion authored in the UI (address →
`maps` routing, confirmed) scores end-to-end on the live hunt; a text custom
("mentions EV charging") extracts and scores with zero tools; custom values
provably invisible to other hunts (existing RLS matrix case extends).

## 13. Wave D + E tasks

### P3-11 — Checkpoints complete

**What/why:** the checkpoint contract's second half — screenshot beside the
buttons (path exists once P3-7 writes it), the 24 h auto-resume sweep (first
scheduler-tick consumer, §2.4), the clock badge on auto-resolved rows, and
reopen-with-re-score from the drawer. A checkpoint system where silence
strands jobs punishes exactly the collaboration Phase 2 built; auto-resume
with visible provenance means nothing waits on a vacation.

Sweep semantics: `waiting_user` older than `CHECKPOINT_TIMEOUT_HOURS` (=24,
tunable exists) → apply the prompt's declared `default`, write
`checkpoint_auto_resolved` (event type already in the check constraint),
re-queue. `resolve_dispute` is exempt until open question #1 is settled by
the first real dispute (§2.8). Late answers replace the default and re-score.
Frontend fills the `AutoResolvedBadge` slot; `CheckpointPromptCard` gains the
screenshot (its line-3 comment has named this task since Phase 1).
**Done when:** an ignored `confirm_value` auto-resolves at 24 h (clock badge,
event row); reopening + answering re-scores; `resolve_dispute` provably does
not auto-resolve.

### P3-12 — Refresh: TTLs, hash gating, field-scoped partial

**What/why:** the §14 machinery — TTL classes from the catalog's
`refresh_class`, content-hash gating (unchanged `cleaned_text_hash` skips
EXTRACT+VERIFY entirely), field-scoped partial refresh, refresh endpoints
(`POST /listings/{id}/refresh`, `POST /hunts/{id}/refresh` — designed in §5.1,
never built), the TTL scan in the scheduler tick, stale badges, and the
planner's refresh mode (closing P3-2's deliberate scope cut). Without hash
gating, refreshes quietly become 80% of the bill (§15 lever 2); with it,
steady state rounds to a fetch and a comparison.

Refresh jobs honor the listing's persisted `source_policy` (§8.2) and the
per-domain rate limiter on hunt-wide fan-out. Frontend fills the `StaleBadge`
slot from `last_fetched_at` vs TTL class and adds refresh actions to the
drawer + table row menu.
**Done when:** unchanged-page refresh costs a fetch + hash compare only
(manifest proves it); `fields=pricing` refresh runs exactly
FETCH(official)→EXTRACT→VERIFY→RECONCILE→SCORE; the stale badge appears when
pricing TTL lapses and clears on refresh.

### P3-13 — Compare view + mobile polish

**What/why:** FR9 — 2–4 listings side-by-side at criterion granularity,
reachable from Overview selection state; plus the mobile pass (bottom-sheet
already ships; this is ergonomics: filter bar collapse, compare on small
screens, tap targets). The endgame of a hunt is comparing three finalists on
a phone in a parking lot; the table optimizes finding candidates, not
choosing between them.

Route `/h/:huntId/compare` (router comment has reserved it since Phase 1);
selection via Overview checkboxes → query param. Columns = listings, rows =
enabled criteria in rubric order with per-listing matched-option/delta/evidence,
gates called out, all-in row with tags. Reads ride existing hooks
(listings/scores/extractions) — no new API.
**Done when:** 3-listing compare is usable on a phone viewport (vitest for the
row model; manual pass for feel); deep-link with listing ids renders directly.

### P3-14 ⚠ — Tier-3 per census verdict (conditional)

**What/why:** the fetcher exists (free-plan-only, off the ladder without a
key); what remains is whatever the P0-14 verdict names — enabling the provider
key posture, per-domain registry pins for census-named hostile domains, and
possibly nothing at all. Scope is *only* the named domains: the census exists
precisely so hostile-domain spend follows measured inventory, not vibes.
**Done when:** census-named domains fetch successfully through the configured
provider on the live hunt — or the task is deleted with a one-line §20 note.

### P3-15 — Ratings stage 2: apartmentratings.com

**What/why:** the §10.12 second rung — property lookup on the site, fetch at
the census-appropriate tier, a small ratings extraction landing as a second
provenance-carrying `management_reviews` row. Places tells you the star
average; renter sites tell you whether maintenance answers the phone —
disagreement between them is signal, and RECONCILE (P3-6) already owns it, so
no blending formula gets invented.
Starts only after P3-8's Places slice is live (the ladder's own rule).
**Done when:** a bench property with both sources shows two provenance-carrying
rating extractions and one reconciled value with its rule.

### P3-1 ⚠ — Optional worker isolation (parked)

**What/why:** move the worker loop to its own process/service and disable the
API's in-process loop — **only** when a DESIGN §5 trigger is observed (repeated
API memory/restart/502 impact, material latency impact, concurrency need,
always-on scheduling need). The durable queue makes this a low-risk migration
whenever evidence arrives; doing it speculatively is a second paid service for
a two-person hunt (DESIGN v2.9 said no).
**Done when (if triggered):** one claimant before/after cutover; a browser job
completes in the isolated worker; API stays healthy; orphan-recovery and
rollback drills pass per the §8 runbook.

---

## 14. Sequencing

```
            ┌── P3-2 planner/runner ──┐
 (entry) ───┤                          ├──► P3-4 DEDUPE ──► P3-5 DISCOVER ──► P3-6 RECONCILE
            └── P3-3 maps/tools ──────┘         │                                   │
                                                ▼                                   ▼
                              P3-7 vision · P3-8 enrich · P3-9 utilities · P3-10 custom   (Wave C, parallel)
                                                │
                                                ▼
                              P3-11 checkpoints ──► P3-12 refresh ──► P3-13 compare/mobile (Wave D)
                                                                          │
                                       P3-14 tier-3 (census-gated) · P3-15 ratings-2 (after P3-6+P3-8)
```

Wave A tasks are independent of each other; B is strictly ordered (identity →
siblings → merge); C parallelizes behind its named inputs (P3-7 needs the
reference set; P3-8 needs P3-3; P3-9 needs metro identity from geocode; P3-10
needs P3-2's dispatch); D follows the stages whose outputs it schedules,
displays, or re-plans. P3-11 lands the scheduler-tick scaffold that P3-9 and
P3-12 extend — if P3-9 finishes first, it lands the scaffold instead (whoever
is first builds it; the other two add queries).

---

## 15. Testing & CI

- **Stage tests stay fixture-based** — saved cleaned text + recorded LLM/Maps
  responses; no live LLM or Google calls in CI, ever. New prompts enter
  record/replay from their first test; Maps fixtures follow the same
  hash-keyed naming.
- **Golden manifests:** planner tests assert exact manifest JSON for the
  canonical cases (new property, known-property re-add, trust_link, policy
  tier-cap, unchanged-hash refresh, **escalation append with its
  `plan.escalation` record**, missing-tier substitution) — the manifest is a
  pinned contract (§10.4), so it gets golden treatment like score breakdowns.
- **Resume tests:** every new stage gets the park/resume test (kill after
  stage N, resume, assert no re-run) — persist-before-advance is only true if
  tested per stage; plus the pre-P3 snapshot fallback case (§2.1).
- **Ladder/RECONCILE:** table-driven tests over the v2 ladder with synthetic
  source sets; equivalence-normalization cases recorded; family-dedup cases
  (three same-family sources = one vote, never a supermajority);
  settled-field immunity (round sources cannot reopen a settled field);
  escalation-order cases (official arbiter before the sibling round;
  non-decision-relevant fields skip the spend rungs entirely).
- **Tool-loop discipline:** tests assert extraction stages have empty
  allow-lists, budgets raise `AgentBudgetExceeded`, and every tool call left a
  `job_events` row.
- **Bench reruns owed:** any EXTRACT/VERIFY prompt or pin change (P0-14
  fallout, P3-6's per-source changes if they touch prompts) re-runs the Phase 0
  bench per the standing rule. The 2.0.25 owed rerun is still outstanding and
  should clear with P0-11..13 before Wave B.
- **Frontend:** vitest for compare row model, badge logic (stale/auto-resolved/
  single-source), composition display tags, custom-criteria authoring widgets;
  no snapshots (convention).
- **CI shape unchanged:** synthetic `fixtures/pages/` only; the local eval kit
  stays a local asset (§20 v2.8).

---

## 16. Exit criteria (DESIGN §19: NFR1–NFR4 measured and met, live hunt)

- **NFR1 (cost):** per-listing ingest cost from `jobs.cost_actual_usd` +
  Langfuse over ≥10 real submissions: <$0.15 new, <$0.01 refresh, $0 re-score.
- **NFR2 (latency):** submit-to-score <3 min single-source and <5 min
  baseline-slate multi-source (escalated runs exempt but visible in the
  manifest), measured on live submissions (`started_at`→`finished_at`); UI
  updates via Realtime only.
- **NFR3 (resumability):** kill-mid-run drill on a live multi-source job:
  resume completes with no stage re-run and no duplicate rows; deploy during a
  running job loses nothing.
- **NFR4 (provenance):** spot-audit on the live hunt: every displayed value
  traces to source + timestamp + model + confidence + (where reconciled)
  `resolution_rule`; disputed values show their candidates.
- All Wave A–D done-whens green; P3-14/P3-15 resolved per their gates (done or
  deleted with §20 notes).
- DESIGN §20 entries recorded at minimum for: manifest-driven runner, DISCOVER
  search provider, `resolve_dispute` default (when settled), tier-3 verdict
  application, and any model-pin change. Phase 4 does not exist — §19 ends
  here, so exit review decides what, if anything, is next.
