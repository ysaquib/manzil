# Plan — Learning Track (L0 … L4)

**Status:** outline / proposal, expanded 2026-09-11. Nothing here is ratified: DESIGN §19
owns the L-milestone list and its gating rule, §10.11 owns the architectures. This
document is the *sequencing, topology and tooling* layer between them — what to build
first, which agent talks to which, what crosses the wire between them, what already
exists to build it on, and what each step must measure before it counts. No DESIGN §20
entry accompanies it, because it decides nothing new.

**Read first:** DESIGN §2.5 (learning objectives), §10.11 (agents mode), §19 (Learning
Track + gating), FR11/FR12 (§4.1), §16 (tool allow-lists), IMPLEMENTATION §6 (tracing)
and §7 (the L-table placeholder).

**The governing constraint, restated so it is not lost mid-track:** the lease deadline
wins every conflict (R11). An L-milestone starts only after the shipping milestone it
depends on is green and must never delay the next one. Every step below is abandonable at
any point without leaving the critical path broken — a design property, not an accident,
and worth preserving deliberately.

---

## 1. Where the track stands

| | State |
|---|---|
| **L0** | **Done.** Langfuse wired inside the client seam (`llm/client.py`; every call traced with `mode`/`model`/`prompt_version`/`listing_slug`). Harness live: `evals/harness.py` (`run_bench` → `BenchReport`), `evals/labels.py`, `evals/compare.py`, CLI `bench-run` / `bench-compare` / `bench-audit-scoped`. It ran the P0-13 sweep and produced the P0-14 pin. |
| **L1–L4** | **Not started.** `worker/src/manzil_worker/agents/` is an empty package whose docstring says so. Nothing imports it. |
| **Mode plumbing** | **Half-built, correct as far as it goes.** `RunState.mode: Literal["workflow","agents"]` (`state.py:528`), `RunContext.mode` on every span (`llm/client.py:108`), `MANZIL_MODE` read by `cli.py:81` (which *refuses* anything but `workflow`) and `service.py:79` (recorded on `worker_heartbeats`). Nothing branches on it. That refusal is the first line L2 deletes. |
| **Gate for L1** | Phase 0 **exit** — §2 below. The decision gate closed 2026-07-21; the phase exit was never written down. |

---

## 2. The invariant architecture — how the agents work together

This section holds for **every** phase of the track. Read it once; the per-phase sections
below assume it.

### 2.1 Three layers, and only the top one is allowed to change

```
┌─────────────────────────────────────────────────────────────┐
│  AGENT LAYER          mode-specific · lives in agents/      │
│  who fetches, who extracts, who criticises, who routes       │
│  ── swappable, measurable, abandonable ──                    │
├─────────────────────────────────────────────────────────────┤
│  CONTRACT LAYER       identical in both modes               │
│  RunState · SourceResult · SourceClaim · FloorPlanIn ·       │
│  Persistence protocol · checkpoint prompt · StageCtx seams   │
├─────────────────────────────────────────────────────────────┤
│  TRUTH LAYER          invariant, imported, never modified   │
│  VERIFY checks 1–3 · the RECONCILE ladder · SCORE            │
└─────────────────────────────────────────────────────────────┘
```

§10.11's invariant in one line: **agents mode may change who does the work, never what
counts as correct.** Concretely, the truth layer is these three things:

- **VERIFY checks 1–3** (`stages/verify.py`): `_check_evidence` (is the evidence quote
  locatable in the page text), `_check_conformance` (does the value fit the catalog's
  `value_schema`), `_check_plausibility` (sqft/bed, deposit/rent, date sanity). All code,
  no model. Check 4 `_check_consistency` is the one cheap LLM call and is *not* part of the
  invariant layer — it is a model call like any other, and agents mode may reimplement it.
- **The RECONCILE ladder** (`stages/reconcile.py::reconcile_stage`) — see §2.4.
- **SCORE** (`shared/` scoring engine): pure, deterministic, LLM-free. Facts in, points out.

An agent may *propose*. Only the truth layer *decides*.

### 2.2 Agents hand off typed state, never prose

The single most important rule for the crew, and the one that keeps the whole track
debuggable: **every inter-agent hand-off is an existing Pydantic model.** Free text crosses
the boundary *into* a model call and comes back out through forced tool use
(`call_structured` pins `tool_choice`, so the model cannot answer in prose). It never
travels between two agents.

The hand-off types already exist and were built for exactly this shape:

| Type | Carries | Defined |
|---|---|---|
| `SourceResult` | one Source's whole extraction: claims, floor plans, identity, pet costs, utilities, fees, heating, contact, `verified`, `verify_flags` | `state.py` |
| `SourceClaim` | one `{criterion_key, value, confidence, evidence_quote, source_id, model, prompt_version, target_scope}` | `state.py` |
| `FloorPlanIn` | plan name, beds/baths, sqft, rent range, availability, unit types | `state.py` |
| `VerifyFlag` | which check fired, on which key, why | `state.py` |
| `RunState` | the whole run, including `plan` (manifest), `sources`, `source_results`, `resolved_claims`, `cursor`, `cost_usd` | `state.py:528` |

New types the track adds (`CriticFinding`, `InvestigationBrief`, …) follow the same rule:
declared as Pydantic models next to the agent that produces them, validated at the seam.

### 2.3 Workflow mode is *already* orchestrator–workers — just deterministic and serial

This is the most useful thing to understand before building L2, and it is easy to miss.
`extract_stage` does this today:

```python
for index, source in enumerate(state.sources):        # ← sequential
    isolated = _empty_source_slice(state, index)      # ← private context per Source
    extracted = await _extract_single(isolated, ctx)
    result = _result_from_state(extracted)            # ← structured brief out
    state.source_results.append(result)
```

`_empty_source_slice` clones run metadata and clears every output belonging to another
Source — that is a *shared-nothing worker context*, built for isolation reasons that have
nothing to do with agents. `verify_stage` does the same thing again over `source_results`,
with `allow_checkpoint=False` so one suspect sibling cannot park the run before RECONCILE
has seen stronger evidence elsewhere.

So the agents-mode orchestrator–workers architecture is not a new shape bolted onto the
pipeline. It is **the same shape with a model making the decisions a `for` loop currently
makes**, and that is precisely why the A/B is clean: the comparator already exists, is in
production, and is free to run.

What the orchestrator gets to decide that the loop does not:
- which slate Sources are worth spending on at all (the loop takes every fetched Source)
- how many to run concurrently, and in what order
- when the evidence is sufficient to stop early
- whether to escalate before RECONCILE asks (workflow escalates only *after* the ladder
  fails, via `_plan_official` / `_plan_sibling_round`)

### 2.4 The RECONCILE ladder — what every worker's output must feed into

Every phase of the track ends up here, so the rungs are worth stating exactly. In order,
per target key, after `_family_dedup` collapses syndicated duplicates:

1. `single_source` — one claim survives dedup; take it.
2. `numeric_tolerance_conservative` — numeric claims within tolerance; take the conservative one.
3. `family_supermajority` — ≥ 2/3 of families agree (`RECONCILE_SUPERMAJORITY = 2/3`), after an LLM *equivalence* pass groups differently-worded-but-same values.
4. `official_arbiter` — the official Source, at ≥ MEDIUM confidence, if policy allows it.
5. `verified_positive_preferred` — non-gate keys with that conflict policy; marked `disputed`.
6. **escalation** — at most one official round, then at most one sibling round, planned into the manifest (`_plan_official`, `_plan_sibling_round`); the stage returns and the runner re-enters after the new Sources are fetched and verified.
7. `family_majority` — > 1/2.
8. `conservative_disputed` — take the conservative value at LOW confidence, mark disputed.
9. `resolve_dispute` **checkpoint** — ask a human; default `Leave unknown` (§20 v3.21).

An agents-mode component may feed this ladder better evidence. It may not re-order,
short-circuit, or replace it.

### 2.5 The runtime facts that decide whether parallelism is real

Three mechanics will determine whether L2's numbers mean anything. Get them right before
running anything.

**(a) `OPENROUTER_MAX_CONCURRENT_CALLS = 1`.** This is the headline. `llm/concurrency.py`
gates every OpenRouter call behind a per-provider Postgres advisory lock with **one slot**,
spanning every worker and API replica sharing the database — "deliberately conservative for
Gemini's shared pool" (`shared/config.py:33`). **As the system stands, spawning five
parallel workers produces five serialised calls.** Wall-clock speedup would be zero, and a
naive L2 latency measurement would report "multi-agent is no faster" when what it actually
measured was the semaphore.

The fix is not to quietly raise it. It is to (i) run the L2 latency comparison with the
gate raised *equally* for both modes so the comparison is like-for-like, (ii) record the
slot count in the `BenchReport` alongside the model pins, and (iii) treat any production
change to the gate as its own decision with its own §20 entry, because it is a
rate-limit-safety change, not a learning-track change.

**(b) Context propagation under `asyncio.gather`.** Both the run context and the cost tally
are `ContextVar`s (`llm/client.py:111`, `costs.py:116`). A task created by `gather` copies
the current context, so child workers *inherit* the ambient `CostTally` object and mutate
the same instance — spend is captured correctly for free. But a worker that opens its own
`cost_tally()` rebinds the var inside its own context and its spend becomes invisible to
the parent unless it is merged back. `CostTally.merge` exists and `_run_stage` already uses
it exactly this way across retries; parallel workers must do the same. Same story for
`RunContext`: inherit it and every worker's spans land on the right job session; rebind it
per worker (to attribute spans to a Source) and you must re-set the job_id yourself.

**(c) Budgets are per-loop, not per-run.** `AGENT_MAX_TURNS = 8`; DISCOVER runs tighter
(`DISCOVER_MAX_TURNS = 6`, `DISCOVER_MAX_SEARCHES = 3`, `DISCOVER_MAX_FETCH_PAGE_CALLS = 4`).
`ToolContext` budgets characters so one turn cannot become a crawl. An orchestrator that
spawns N workers multiplies the *run's* budget by N — so a run-level ceiling has to be
enforced by the orchestrator, because no existing mechanism does it.

### 2.6 Failure semantics: a worker dying is not the job dying

Workflow mode's contract is `StageRetryable` → backoff → retry (3 attempts) →
`StageFatal` → job failed, with `CheckpointRaised` → `WAITING_USER`. Agents mode inherits
this at the *stage* boundary but needs one addition at the *worker* boundary: a worker that
fails on one Source should degrade the run to the remaining Sources, not fail it —
`verify_stage`'s `allow_checkpoint=False` is the existing precedent for exactly this
reasoning. `AgentBudgetExceeded` is "a real outcome the calling stage handles"
(`tools.py`), not an error to swallow.

### 2.7 Tracing identity, per agent

IMPLEMENTATION §6 pins trace naming `{job_type}/{stage}`, session = `job_id`, with `mode`
on every span. For multi-agent runs, extend *metadata*, never the naming scheme: add
`agent_role` (orchestrator / worker / critic / triage) and `source_url` where it applies.
The harness reads spend and latency from traces, not from ad-hoc accounting — so a span
missing `mode` or `agent_role` is a hole in the eval report, not merely untidy logging.

---

## 3. Step 0 — unlock L1 by recording Phase 0's exit

**Why this is step one.** DESIGN §19 gates L1 on "after Phase 0 exit". Phases 1 and 2 carry
explicit `*Exited <date>*` lines; Phase 0 does not. AGENTS.md still says "L1 remains gated
on Phase 0's exit", so the gate is open in fact and shut on paper.

| Exit criterion | Evidence | Verdict |
|---|---|---|
| Extraction verification pass-rate acceptable on gate-bearing Criteria | Gate accuracy 1.0, Criterion accuracy 0.904 over ten labels (IMPLEMENTATION 2.0.69) | met |
| Fetch tier requirements known per relevant domain | Census ruled 2026-07-17; all five P3-14 Tier-3 domains confirmed live 2026-08-02 | met |
| Per-stage model choices settled | P0-14 pin + the 2026-07-28 workhorse collapse (DESIGN v3.23) | met |
| Per-listing cost measured | $0.16 / ten listings on the winning pin | met |

**Two caveats that belong in the entry rather than being quietly skipped:** the bench has
**not** been re-run since the workhorse tier collapsed onto `gemini-3-flash-preview`
(IMPLEMENTATION 2.0.86 records it as owed), and P3-21 added an optional `property_contact`
block to the EXTRACT schema afterward. Separately, the P3-SC4 scoped-label tail (11
unfinished skeletons) is Owner-waived debt, not passed evidence.

**Do:**
1. Re-run `manzil bench-run` at current pins, record mode, over the ten local labels — the
   owed rerun *and* the L1 baseline, one run.
2. Append the Phase 0 exit ruling to DESIGN §20; add the `*Exited <date>*` line to §19's
   Phase 0 block; name the two caveats there.
3. Add the `L` table to IMPLEMENTATION §7 (the file says it appears "when L1 unlocks").
4. Update AGENTS.md's Current-phase paragraph.

**Owner call, not an agent's:** phase exits have been Yusuf's sign-off every time (P1-15,
P2-10). The rerun and the drafting are agent work; the ruling is not.

**Done when:** §19 says Phase 0 exited, §7 has an `L` table, and a current-pin
`BenchReport` exists to compare against.

---

## 4. L1 — extractor + critic

*Gate: Phase 0 exit. Size: ~2 sessions. The smallest real agents-mode component — do it first for that reason.*

### 4.1 The question

**Does an LLM critic catch extraction errors that deterministic VERIFY checks 1–3 miss, and
at what token cost?** Keep or kill on that data. A kill verdict is a successful outcome and
gets written up as enthusiastically as a keep.

### 4.2 Topology

```
              cleaned_text (one Source)
                       │
                       ▼
        ┌────────── EXTRACT ──────────┐      unchanged, deterministic entry
        │ zero tools · forced schema  │
        └──────────────┬──────────────┘
                       │  SourceResult
           ┌───────────┴───────────┐
           ▼                       ▼
   ┌──── VERIFY ────┐      ┌───── CRITIC ─────┐   agents/critic.py
   │ 1 evidence     │      │ zero tools       │
   │ 2 conformance  │      │ sees page + the  │
   │ 3 plausibility │      │ extracted record │
   │ 4 consistency  │      └────────┬─────────┘
   └───────┬────────┘               │
           │ VerifyFlag[]           │ CriticFinding[]
           └──────────┬─────────────┘
                      ▼
        harness set-difference, graded against the bench label:
        findings the label confirms that checks 1–3 did not raise
```

### 4.3 Agent roster

| Agent | Input | Output | Tools | Model tier |
|---|---|---|---|---|
| `critic` | `(cleaned_text, SourceResult)` | `CriticFinding[]` = `{catalog_key, target, claimed_value, verdict: agree\|suspect\|contradicted, why, evidence_quote, severity}` | **none** | start on the workhorse pin; sweep later |

One agent, one call, no loop. The critic is a *proposer–critic* second opinion, not a
conversation — if it needs a second turn it needs a better prompt.

### 4.4 Build

- `worker/src/manzil_worker/agents/critic.py`.
- `llm/client.py::call_structured` with a new stage key `critic`. Add it to `STAGE_MODELS`
  and price its model in `MODEL_PRICES` — `model_for_stage` refuses an unpriced override by
  design, so cost accounting never guesses.
- Prompt in `llm/prompts/` through `prompt_loader`, so it gets a version number that lands
  in `BenchReport.prompt_versions` and in every span's metadata.
- Harness: `_run_listing` already runs EXTRACT → VERIFY against a frozen corpus page and
  grades against a `BenchLabel`. Add the critic as a third graded step; extend
  `BenchReport.summary` with `critic_caught`, `critic_false_positives`, `critic_cost_usd`,
  `critic_tokens`.
- `evals/compare.py::_ROWS` — one row per new metric. The A/B is then two `bench-run`
  reports through the existing `bench-compare`; no new CLI surface.
- Record/replay (`MANZIL_LLM_MODE=record|replay`) so the graded run repeats at zero tokens.
  Recording keys include the model, so a pin change re-keys the fixtures.

### 4.5 The metric that matters

Not "did the critic find something" — checks 1–3 already find plenty, and a critic that
re-reports them looks impressive and adds nothing. The measurement is the **set
difference**, three buckets:

| Bucket | Meaning |
|---|---|
| **Caught-beyond-VERIFY** | critic raised it, label confirms it is wrong, checks 1–3 did not flag it → the entire value of the critic |
| **Redundant** | critic raised it, checks 1–3 already flagged it → free, worthless |
| **False positive** | critic raised it, label says the extraction was right → the cost of the critic, in human attention |

Divide bucket 1 by tokens spent. Everything else is decoration. A useful secondary read:
*which* criteria land in bucket 1 — if they are all one catalog key, the answer is a better
EXTRACT prompt, not a critic.

### 4.6 Traps

- **The critic gets zero tools.** It is an extraction-family stage and §16 is not
  negotiable; `_enforce_allow_list` will refuse it anyway, and that refusal must stay —
  absence from `STAGE_TOOLS` *is* the control.
- **The critic must not change what counts as correct.** In L1 a finding is evidence
  *about* an extraction, never a demotion of one. No writes to `source_claims`, no
  confidence changes, no new `VerifyFlag`s. If the verdict is "keep", promoting it to a
  real demotion is a *separate* change with eval evidence and a §20 entry.
- **Nothing on the critical path imports `agents/`.** In L1 the only importer is the
  harness. Add the one-line import test now (§8.1) while the rule is trivially true.
- **Grade over the same listings.** The P0-12 checkpoint-as-error bug (2.0.69) biased a
  whole model sweep by silently dropping 4–5 of 10 listings per model. The critic introduces
  a second way to drop a listing — a critic call that fails must not remove that listing
  from VERIFY's own numbers.

### 4.7 Done when

A `docs/` write-up states catch-rate-beyond-VERIFY, false-positive rate, and $/listing,
with a keep/kill verdict — plus a §20 entry if anything moves toward the default path.

---

## 5. L2 — LangGraph graph, orchestrator–workers, triage routing

*Gate: Phase 1 exit (met 2026-07-10). Size: ~4 sessions. The bulk of the track.*

### 5.1 The question

Three, actually, and they should be reported separately because they have different
answers: (a) what does expressing the pipeline as a **graph** buy over the hand-rolled
runner, (b) what does an **orchestrator** buy over the sequential fan-out loop, (c) what
does **triage routing** buy over static model pins? §10.11's stated expectation going in is
a 5–15× token multiplier for agents mode; measuring it honestly is the point, including if
the answer is worse.

### 5.2 Topology

```
    ┌────────┐   manifest (§10.4 pinned shape) — both modes
    │  PLAN  │
    └───┬────┘
        ▼
   ┌──────────┐   slate: official + siblings, tier/family capped
   │ DISCOVER │   (already a bounded tool loop in workflow mode)
   └───┬──────┘
       ▼
 ┌──────────────────────┐
 │     ORCHESTRATOR     │   agents mode only · no tools of its own
 │  decides: which of   │   reads: slate + Source Policy + what is already
 │  the slate to spend  │          verified
 │  on, how many at     │   writes: worker assignments (typed), nothing else
 │  once, when to stop  │
 └──────┬───────────────┘
   ┌────┴─────┬──────────┬──────────┐
   ▼          ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐   one private context window each
│worker A│ │worker B│ │worker C│ │  ...   │   (= today's _empty_source_slice)
│ triage │ │        │ │        │ │        │   ← per-page model-tier choice
│ FETCH  │ │        │ │        │ │        │
│ EXTRACT│ │        │ │        │ │        │   zero tools (§16) inside extraction
│ VERIFY │ │        │ │        │ │        │   checks 1–3 code, 4 one call
└───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘
    │ SourceResult (verified=True, verify_flags[])
    └──────────┴──────────┴──────────┘
                    ▼
        ┌───────────────────────────┐
        │        RECONCILE          │  ← DETERMINISTIC. imported, not rebuilt.
        │ family dedup → tolerance → │    §2.4's nine rungs, unchanged.
        │ supermajority → official → │
        │ escalation → majority →    │
        │ conservative → checkpoint  │
        └─────────────┬─────────────┘
                      ▼
                   SCORE (pure)
```

The dashed boundary to keep in your head: **everything above RECONCILE is negotiable;
RECONCILE and below is not.**

### 5.3 Agent roster

| Agent | Role | Input | Output | Tools | Budget |
|---|---|---|---|---|---|
| `orchestrator` | decide the work | slate (`state.sources`), Source Policy, `source_results` so far | `WorkerAssignment[]` = `{source_url, reason, priority}` + a stop decision | none | run-level ceiling it enforces itself (§2.5c) |
| `source_worker` | do the work | one `RunState` slice (`_empty_source_slice`) | `SourceResult` | none inside extraction (§16) | per-Source token cap |
| `triage` | pick the tier | page size, tier used, family, a cheap difficulty signal | `{tier: lightweight\|workhorse\|judgment, why}` | none | one call, cheapest model |

Three roles, and note what is *absent*: there is no "reconciler agent" and no "scorer
agent". Those are the truth layer. An agent that proposes a resolution is a design error in
this track, not a feature.

### 5.4 Build order — four sessions

**5a · One dispatch seam.** Delete the `cli.py:81` refusal. Route on `state.mode` at
exactly **one** place: the entry to `run_job`. One branch, one import edge, one thing to
delete if the track is abandoned. `queue.py` already carries `mode` through to
`worker_heartbeats`; give it the same single branch, not a scattering of them. Ship this
with the import test and an agents-mode run that simply calls the workflow path — a no-op
graph that proves the seam before anything interesting rides on it.

**5b · The graph.** `agents/graph.py`: the pipeline as a LangGraph graph whose state is
`RunState` and whose nodes call the *same* stage callables from `stages/`.
`runner.py::INGEST_STAGES` / `STAGE_REGISTRY` are the node list; `StageCtx` is the injected
world and does not change shape. Add `langgraph` as a `worker` **optional-dependency
extra** (`agents`) so the shipping install stays boring per NFR5 — §10.11 already justifies
the dependency, so this needs no new ruling, only the extras group.

*The contract that must survive the port:* persist BEFORE advance. `run_job` saves state,
then moves the cursor, then saves again — deliberately, so a crash between the two re-runs
an idempotent stage rather than skipping it. If the graph's node boundaries do not
reproduce that, resumability quietly differs between modes and every comparison downstream
is invalid.

**5c · Orchestrator–workers.** The orchestrator receives the slate and spawns a worker per
assigned Source. Each worker owns a private `RunState` slice and returns a `SourceResult` —
i.e. `_empty_source_slice` → `_extract_single` → `_result_from_state`, the functions that
already exist, now driven by a model instead of `enumerate()`. Workers run under
`asyncio.gather`, which makes §2.5's three mechanics load-bearing: raise the OpenRouter gate
for *both* modes or measure nothing, inherit-or-merge the cost tally, and cap the run-level
budget in the orchestrator because nothing else will.

**5d · Triage routing + the dual-mode report.** A classifier node per worker choosing the
model tier, against `STAGE_MODELS`'s static pins. The comparison is cheap and the likely
result is "the static pins win" — that is still a finding, and it is the one §11.2's
implicit workhorse/judgment split has never been tested against. Then:
`run_bench(..., mode=)`, `mode` + `openrouter_slots` on `BenchReport`, a mode row in
`compare_table`. Per IMPLEMENTATION §6 the harness reads spend and latency from Langfuse —
`mode` is already on every span, so the dual-mode split is a query, not new plumbing.

### 5.5 What the report must separate

Reporting "agents mode cost 7× and was 1.3× more accurate" is not a finding; it is three
findings blended into mush. Break it out:

| Axis | Workflow comparator | Honest reading |
|---|---|---|
| Graph vs runner | `run_job`'s cursor walk | expect ~0 accuracy delta — this is an *ergonomics* result, report it as one |
| Orchestrator vs `for` loop | `extract_stage`'s sequential fan-out | accuracy delta comes from *source selection*; latency delta is meaningless unless the gate was raised for both |
| Triage vs static pins | `STAGE_MODELS` | cost delta at equal accuracy is the only interesting cell |

### 5.6 Traps

- **The OpenRouter gate is 1** (§2.5a). If you take one thing from this document into L2,
  take that.
- **Stage idempotency in both modes.** A re-run stage must stay harmless; the orchestrator
  re-entering after an escalation round depends on it.
- **Cost tallies through `gather`** (§2.5b) — or the token axis is fiction.
- **`_mirror_primary_result`.** Both EXTRACT and VERIFY mirror the primary Source's result
  onto top-level `RunState` fields for the single-source path. An agents-mode graph that
  skips the mirror will look correct through RECONCILE and then break the drawer.
- **Don't let the orchestrator touch `resolved_claims`.** Proposing is above the line;
  resolving is below it.

### 5.7 Done when

`MANZIL_MODE=agents manzil ingest <url>` scores a real listing end to end, and
`bench-compare` prints a workflow-vs-agents table over the same ten labels with the three
axes of §5.5 separated.

---

## 6. L3 — checkpoints on LangGraph interrupt + Postgres checkpointer

*Gate: Phase 2 exit (met 2026-07-18). Size: ~1–2 sessions.*

### 6.1 The question

§10.11 calls this the strongest natural fit in the whole track, because the design
converged on interrupt → persist → resume *before* LangGraph entered the picture. That is
exactly what makes it the fairest test of what a framework adds once you have already
solved the problem yourself. The write-up is the deliverable; the port is just how you earn
the right to write it.

### 6.2 How the human becomes a node

```
   agents-mode graph
        │
        ▼
   ┌─────────┐  a gate-relevant value at low confidence
   │ VERIFY  │──────────────┐
   └────┬────┘              │
        │                   ▼
        │           ┌───────────────┐
        │           │  interrupt()  │  ← LangGraph
        │           └───────┬───────┘
        │                   │  the SAME pinned prompt shape:
        │                   │  {kind, question, options, default, context_ref}
        │                   ▼
        │           ┌───────────────┐
        │           │   jobs row    │  ← STILL THE SOURCE OF TRUTH
        │           │ WAITING_USER  │     Tasks UI reads Postgres directly
        │           └───────┬───────┘
        │                   │ answer lands in jobs.payload
        │                   ▼
        │           ┌───────────────┐
        └───────────│    resume     │  from that exact Stage boundary
                    └───────────────┘
```

Three checkpoint kinds are live and all three participate in the 24 h auto-resume sweep:
`confirm_value` (default `yes`), `resolve_dedupe` (default `keep_separate`),
`resolve_dispute` (default `Leave unknown`). The port must handle all three or it has not
been ported.

### 6.3 Use

`langgraph-checkpoint-postgres` against the same Supabase instance; the existing
`CheckpointRaised` → `WAITING_USER` → `jobs.payload` → resume path in `runner.py` as the
comparator; the `Persistence` protocol (`persistence.py`, `postgres_persistence.py`) as the
boundary the checkpointer must not cross.

### 6.4 The trap, which is the whole risk of this step

**The `jobs` row stays the source of truth.** The API, the Tasks UI, the 24 h auto-resume
sweep, the `checkpoint_auto_resolved` event, the Overview clock-glyph badge, and the
reopen-from-drawer correction path all read Postgres directly. A LangGraph checkpointer
that becomes a second, divergent store of run state is precisely how agents mode would
start silently affecting the product — the one thing the whole isolation design exists to
prevent. Keep it strictly additive: the checkpointer may hold graph-internal resumption
detail; it may not hold the answer, the state, or the truth about whether a job is waiting.

### 6.5 What to actually write up

Not "LangGraph worked". The comparison worth recording is mechanical and specific:

| Concern | Hand-rolled (`runner.py`) | LangGraph |
|---|---|---|
| Resume granularity | stage cursor, persist-before-advance | node boundary + checkpointer |
| What a crash costs | re-run one idempotent stage | ? |
| Where "waiting" lives | `jobs.state` — one place | two, unless disciplined |
| Adding a stage | one list entry in `INGEST_STAGES` | ? |
| Debugging a stuck run | read the `jobs` row | ? |
| Lines of code to own | ~240 | ~0 + a dependency |

Fill the question marks from experience, not from the docs.

### 6.6 Done when

An agents-mode job parks on each of the three checkpoint kinds, is answered through the
ordinary Tasks UI, and resumes correctly — plus the written comparison.

---

## 7. L4 — the investigator crew (FR12)

*Gate: any time after Phase 1. Deliberately last: the only step that ships a user-visible feature, and the only one with no deterministic comparator.*

### 7.1 What it is

A new `job_type: investigate` producing a structured brief — reviews and management
reputation, scam signals and cross-listing price checks, area context — from a spawnable
crew synthesized by an orchestrator. "Slow, costly, or occasionally dumb is acceptable here
by design" (FR12); nothing downstream depends on it. This is the one place in the whole
project where the ambition is allowed to be visible to a user, precisely because its
failure mode is a mediocre paragraph rather than a wrong score.

### 7.2 Topology

```
        Investigate action (listing drawer, §13.2) → investigate Job
                            │
                            ▼
                 ┌──────────────────────┐
                 │     INVESTIGATOR     │  orchestrator · no tools of its own
                 │  scopes the question │  spawns ≤ 3 workers, fans in once
                 └───┬──────┬──────┬────┘
          ┌──────────┘      │      └──────────┐
          ▼                 ▼                 ▼
   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
   │ reputation  │   │  integrity  │   │    area     │
   │ reviews,    │   │ scam        │   │ transit,    │
   │ management  │   │ signals,    │   │ amenities,  │
   │ company     │   │ cross-      │   │ context     │
   │             │   │ listing     │   │             │
   │ web_search  │   │ price check │   │ maps/places │
   │ fetch_page  │   │ fetch_page  │   │ (no search) │
   └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
          │ Finding[]       │                 │
          └─────────────────┼─────────────────┘
                            ▼
                  ┌──────────────────┐
                  │   SYNTHESIZER    │  one structured call, no tools
                  └────────┬─────────┘
                           ▼
                  InvestigationBrief  → persisted → rendered in the drawer
```

Each worker has its **own** tool allow-list, and they are deliberately different: the area
worker never needs web search (Maps seams suffice), the integrity worker never needs Maps.
Allow-lists that differ per worker are the point — a single shared list would hand every
worker the union of the crew's powers.

### 7.3 Agent roster

| Agent | Tools (new `STAGE_TOOLS` rows) | Turn budget | Output |
|---|---|---|---|
| `investigator` (orchestrator) | none | n/a — one structured call | `WorkerBrief[]` (which workers, what question each) |
| `investigate_reputation` | `web_search` (server), `fetch_page` | ≤ 6 | `Finding[]` |
| `investigate_integrity` | `fetch_page` | ≤ 6 | `Finding[]` |
| `investigate_area` | `geocode`, `places_nearby`, `commute_time` | ≤ 4 | `Finding[]` |
| `investigate_synthesis` | none | one call | `InvestigationBrief` |

`Finding` = `{claim, confidence, source_url, quote, kind}`. The brief cites its findings;
a sentence in the brief without a `Finding` behind it is a hallucination surface, and the
UI should be able to expand any claim to its source.

### 7.4 Use

`llm/tools.py::run_agent_loop` via `call_agent(stage, task, tools, max_turns)`; the ENRICH
Maps/Places seams in `stages/base.py` (`nearby_places`, `commute_minutes`, `place_details`)
for the area leg; DISCOVER's OpenRouter native-search pattern for reputation; the drawer's
**Investigate** action, which §13.2 already specifies.

### 7.5 Needs before it lands

- A `job_type` enum value + migration (AGENTS.md's migration-versioning rule: continue the
  `20260901` sequence until 2026-09-01, actual timestamps after — as of today, use
  `supabase migration new`).
- Four new `STAGE_TOOLS` rows — which is a §16 change. Today the table has **exactly two**
  non-empty rows and its comment says so, because that table *is* the enforcement of
  AGENTS.md's "only DISCOVER and location-type custom criteria may run a tool loop" rule.
  Adding agents-mode rows means amending that rule's wording to scope it to workflow mode.
  **That needs a §20 entry and is the single most security-relevant change in the track** —
  do not let it ride in quietly on a feature commit.
- A §20 entry for the job type itself: a new job type reaching the UI is material even off
  the critical path.

### 7.6 Traps

- **No comparator exists.** There is no deterministic investigator to A/B against, so the
  eval has to be human judgment on a rubric — pick the rubric *before* reading any briefs.
- **Cost ceiling.** Three workers × 6 turns × a judgment-tier model is the most expensive
  thing in the product by an order of magnitude. Cap it, show the cost in the UI, and make
  the action explicitly opt-in per listing.
- **Scam signals are a claim about a real business.** The brief must present findings as
  cited quotes, never as adjudication, and the UI copy should make that distinction visible.

---

## 8. Track exit and cross-cutting rules

### 8.1 The six rules that hold for every step

1. **Isolation is structural.** All track code in `worker/src/manzil_worker/agents/`; it
   imports the truth layer and the contracts, and nothing on the critical path imports
   back. Enforce with a one-line import test at L1, while it is trivially true.
2. **The truth layer is invariant.** VERIFY checks 1–3, the RECONCILE ladder, SCORE. Agents
   may propose; only the truth layer decides.
3. **Typed hand-offs only** (§2.2). Prose between agents is how a multi-agent system becomes
   unfalsifiable.
4. **Every LLM call traced, both modes, from the first call** (NFR6). Here an untraced call
   is not just a bug — it is a hole in the report.
5. **No live LLM calls in CI, ever.** Track tests run in replay against committed synthetic
   `fixtures/pages/`; graded runs happen locally against the gitignored corpus and labels
   (DESIGN §20 v2.8). Every number in the final report comes off Yusuf's machine.
6. **A negative result is a result.** "We built it, measured it, and it was not worth it" is
   the most valuable sentence the report can contain, and the one most likely to be true of
   at least one component.

### 8.2 The adoption rule, in force throughout

No agents-mode component becomes default behavior without eval-harness evidence **and** a
§20 Decision Log entry. Neither half alone is sufficient (§10.11).

### 8.3 Track exit

The written eval report in `docs/` — accuracy, tokens, latency, and a verdict on what
multi-agent bought and what it cost, per component and per question, not blended. Not a
summary of what was built: a judgment, with the numbers that support it and the ones that
undercut it. That report is the actual deliverable of the learning objective (§2.5, §19).

---

## 9. Suggested session sequence

| # | Session | Output |
|---|---|---|
| 1 | Bench rerun + Phase 0 exit paperwork | §19 exit line, §20 entry, §7 `L` table, current-pin baseline report |
| 2 | `agents/critic.py` + harness integration + import test | replay-testable critic, no product surface |
| 3 | Critic A/B run + write-up | first real answer the track produces; keep/kill |
| 4 | L2a: the one dispatch seam, no-op agents path | `MANZIL_MODE=agents` runs the workflow path end to end |
| 5 | L2b: LangGraph graph over existing stage callables | agents mode scores a listing through the graph |
| 6 | L2c: orchestrator + workers (gate raised for both modes) | parallel fan-out with honest latency numbers |
| 7 | L2d: triage + dual-mode report | first full workflow-vs-agents table |
| 8+ | L3, then L4 | as scoped above |

Sessions 1–3 are the ones worth committing to now. Decide whether L2 gets its four sessions
after the critic verdict is in — if the critic is a clear kill, that is itself evidence
about how much of the rest of the track will pay.
