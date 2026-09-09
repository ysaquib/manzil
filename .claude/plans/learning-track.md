# Plan — Learning Track (L0 … L4)

**Status:** outline / proposal, 2026-09-09. Nothing here is ratified: DESIGN §19 already
owns the L-milestone list and its gating rule, and §10.11 owns the architectures. This
document is the *sequencing and tooling* layer between them — what to build first, what
already exists to build it on, and what each step has to measure before it counts.
No DESIGN §20 entry accompanies it, because it decides nothing new.

**Read first:** DESIGN §2.5 (learning objectives), §10.11 (agents mode), §19 (Learning
Track + gating), FR11/FR12 (§4.1), IMPLEMENTATION §6 (tracing) and §7 (the L-table
placeholder).

**The governing constraint, restated so it is not lost mid-track:** the lease deadline
wins every conflict (R11). An L-milestone starts only after the shipping milestone it
depends on is green and must never delay the next one. Every step below is abandonable
at any point without leaving the critical path broken — that is a design property, not
an accident, and it is worth preserving deliberately.

---

## 0. Where the track actually stands

| | State |
|---|---|
| **L0** | **Done.** Langfuse wired inside the client seam (`llm/client.py`, every call traced, `mode`/`model`/`prompt_version`/`listing_slug` metadata). Eval harness live: `evals/harness.py` (`run_bench` → `BenchReport`), `evals/labels.py`, `evals/compare.py`, CLI `bench-run` / `bench-compare` / `bench-audit-scoped`. It ran the P0-13 sweep and produced the P0-14 pin. |
| **L1–L4** | **Not started.** `worker/src/manzil_worker/agents/` is an empty package whose docstring says so. Nothing imports it. |
| **Mode plumbing** | **Half-built and correct as far as it goes.** `RunState.mode: Literal["workflow","agents"]` (`state.py:528`), `RunContext.mode` on every Langfuse span (`llm/client.py:108`), `MANZIL_MODE` read by `cli.py:81` (which refuses anything but `workflow`) and `service.py:79` (recorded on `worker_heartbeats`). No code branches on it yet. That refusal in `cli.py` is the first line L2 deletes. |
| **Gate for L1** | Phase 0 **exit** — see step 0 below. The Phase 0 *decision gate* closed 2026-07-21; the *phase exit* has never been written down. |

---

## Step 0 — Unlock L1 by recording Phase 0's exit

**Why this is step one.** DESIGN §19 gates L1 on "after Phase 0 exit". Phases 1 and 2
carry explicit `*Exited <date>*` lines; Phase 0 does not. AGENTS.md still says "L1 remains
gated on Phase 0's exit", so the gate is open in fact and shut on paper. Nothing else in
the track can honestly start until that is reconciled.

**The four Phase 0 exit criteria against reality:**

| Criterion | Evidence | Verdict |
|---|---|---|
| Extraction verification pass-rate acceptable on gate-bearing Criteria | Gate accuracy 1.0, Criterion accuracy 0.904 over the ten labels (IMPLEMENTATION 2.0.69) | met |
| Fetch tier requirements known per relevant domain | Census ruled 2026-07-17; all five P3-14 Tier-3 domains confirmed live 2026-08-02 | met |
| Per-stage model choices settled | P0-14 pin + the 2026-07-28 workhorse collapse (DESIGN v3.23) | met |
| Per-listing cost measured | $0.16 / ten listings on the winning pin | met |

**Two honest caveats that belong in the same entry rather than being quietly skipped:**
the bench has **not** been re-run since the workhorse tier collapsed onto
`gemini-3-flash-preview` (IMPLEMENTATION 2.0.86 records this as owed), and P3-21 added an
optional `property_contact` block to the EXTRACT schema after the last run. Separately, the
P3-SC4 scoped-label tail (11 unfinished skeletons) is Owner-waived debt, not passed evidence.

**Do:**
1. Re-run `manzil bench-run` at current pins, record mode, over the ten local labels. This is
   the owed rerun *and* the L1 baseline — one run, two jobs.
2. Append the Phase 0 exit ruling to DESIGN §20, add the `*Exited <date>*` line to §19's
   Phase 0 block, and name the two caveats there.
3. Add the L-table to IMPLEMENTATION §7 — the file explicitly says it appears "when L1
   unlocks, not before" (§7, after the DM table).
4. Update AGENTS.md's Current-phase paragraph.

**Owner call, not an agent's:** phase exits in this project have been Yusuf's sign-off
every time (P1-15, P2-10). The rerun and the drafting are agent work; the ruling is not.

**Done when:** DESIGN §19 says Phase 0 exited, IMPLEMENTATION §7 has an `L` table, and a
current-pin `BenchReport` JSON exists to compare against.

---

## Step 1 — L1: extractor + critic A/B

*Gate: Phase 0 exit. Effort: the smallest real agents-mode component in the track — do it first for that reason.*

**Achieve.** Answer one precise question with numbers: **does an LLM critic catch
extraction errors that deterministic VERIFY checks 1–3 miss, and at what token cost?**
Keep or kill on that data. A "kill" verdict is a successful outcome and must be written up
exactly as enthusiastically as a "keep".

**Build.** `worker/src/manzil_worker/agents/critic.py` — a proposer–critic pass that
receives the cleaned page text plus the EXTRACT record and returns structured
discrepancies `{catalog_key, claim, why, evidence_quote, severity}`. It runs *after*
EXTRACT and *beside* VERIFY; in L1 it writes nothing to the state that scoring reads.

**Use:**
- `llm/client.py::call_structured` with a new stage key `critic`; add it to `STAGE_MODELS`
  and price its model in `MODEL_PRICES` (`model_for_stage` refuses an unpriced override by
  design). Prompt goes in `llm/prompts/` through `prompt_loader` so it gets a version number.
- `evals/harness.py` — `_run_listing` already runs EXTRACT → VERIFY against a frozen corpus
  page and grades against a `BenchLabel`. Add the critic as a third graded step and extend
  `BenchReport.summary` with `critic_caught` / `critic_false_positives` / `critic_cost_usd`.
- `evals/compare.py::_ROWS` — one row per new metric, and the A/B is then just two
  `bench-run` reports through the existing `bench-compare`.
- Record/replay (`MANZIL_LLM_MODE=record|replay`, `llm/recording.py`) so the graded run is
  repeatable at zero tokens. Recording keys include the model, so a pin change re-keys.
- `worker/tests/fixtures/corpus/` + `fixtures/bench/labels/` — **local, gitignored assets**
  (DESIGN §20 v2.8). Every L-measurement run happens on Yusuf's machine; CI keeps seeing
  only the committed synthetic `fixtures/pages/` in replay.

**The metric that matters.** Not "did the critic find something" — VERIFY's deterministic
checks 1–3 already find plenty. The measurement is the *set difference*: discrepancies the
critic raised that (a) the label confirms are real and (b) checks 1–3 did not flag. Divide
by tokens spent. Everything else is decoration.

**Traps:**
- The critic gets **zero tools**. It is an extraction-family stage and §16 is not negotiable;
  `llm/tools.py::_enforce_allow_list` will refuse it anyway, and that refusal should stay.
- The critic must not change what counts as correct. VERIFY checks 1–3, the confidence
  threshold, and SCORE are the invariant truth layer (§10.11). A critic finding is *evidence
  about* an extraction, never a demotion of one — not in L1.
- Nothing on the critical path may import `agents/`. In L1 the only importer is the harness.

**Done when:** a `docs/` write-up states catch-rate-beyond-VERIFY, false-positive rate, and
$/listing, with a keep/kill verdict — plus a DESIGN §20 entry if the verdict is "keep" and
anything moves toward the default path.

---

## Step 2 — L2: the LangGraph pipeline, orchestrator–workers, triage routing

*Gate: Phase 1 exit (met 2026-07-10). This is the bulk of the track — treat it as four sessions, not one.*

**Achieve.** A second, complete implementation of the pipeline behind `--mode=agents`, and
the **first full dual-mode eval report**: same bench, same labels, two modes, three axes
(accuracy, tokens, latency). §10.11's stated expectation going in is a 5–15× token
multiplier for agents mode; measuring it honestly is the point, including if it is worse.

**2a — one dispatch seam.** Delete the `cli.py:81` refusal and route on `state.mode` at
exactly **one** place — the entry to `run_job`. One branch, one import edge, one thing to
delete if the track is abandoned. `queue.py` already carries `mode` through to
`worker_heartbeats`; give the queue the same single branch, not a scattering of them.

**2b — the graph.** `agents/graph.py`: the pipeline as a LangGraph graph whose state is
`RunState` and whose nodes call the *same* stage callables from `stages/`. `runner.py`'s
`INGEST_STAGES` / `STAGE_REGISTRY` are the node list; `StageCtx` is the injected world and
does not change shape. Add `langgraph` as a `worker` **optional-dependency extra** (`agents`),
so the shipping install stays boring per NFR5 — §10.11 already justifies the dependency, so
this needs no new ruling, only the extras group.

**2c — orchestrator–workers.** The honest parallelism case is the multi-Source fan-out.
Workflow mode does it as the P3-6 second `FETCH`/`EXTRACT` entries in `INGEST_STAGES`;
agents mode gives an orchestrator the slate and spawns a worker per Source, each with its
own context window, handing structured briefs to the deterministic RECONCILE ladder — which
it imports and does not touch. This is the one architecture in the track where the parallel
benefit is real rather than simulated, so it is the one worth building carefully.

**2d — triage routing.** A classifier node grading task difficulty and picking the model
tier, versus `llm/config.py::STAGE_MODELS`'s static pins. The comparison is cheap and the
result is likely "the static pins win" — that is still a finding, and it is the finding
§11.2's implicit workhorse/judgment split has never been tested against.

**2e — dual-mode harness.** `run_bench(..., mode=)`, `mode` on `BenchReport`, a mode row in
`compare_table`. Per IMPLEMENTATION §6 the harness reads spend and latency **from Langfuse
traces**, not ad-hoc accounting — the `mode` metadata is already on every span, so the
dual-mode split is a query, not new plumbing.

**Traps:**
- Persist BEFORE advance is a contract, not a workflow-mode implementation detail. The
  LangGraph nodes must satisfy it too, or resumability quietly differs between modes and
  the comparison is invalid.
- Stage idempotency likewise: a re-run stage must stay harmless in both modes.
- Cost tallies (`costs.py::CostTally`, `state.record_stage_cost`) must keep working through
  the graph, or the token axis of the report is fiction.

**Done when:** `MANZIL_MODE=agents manzil ingest <url>` scores a real listing end to end,
and `bench-compare` prints a workflow-vs-agents table over the same ten labels.

---

## Step 3 — L3: checkpoints on LangGraph interrupt + Postgres checkpointer

*Gate: Phase 2 exit (met 2026-07-18).*

**Achieve.** Port §10.10's checkpoints onto `interrupt()` + a Postgres checkpointer, then
write up what the framework bought against the hand-rolled runner. §10.11 calls this the
strongest natural fit in the track, because the design converged on interrupt → persist →
resume before LangGraph entered the picture — which is exactly why it is the fairest test
of what a framework adds once you have already solved the problem.

**Use:** `langgraph-checkpoint-postgres` against the same Supabase instance; the existing
`CheckpointRaised` → `WAITING_USER` → `jobs.payload` → resume path in `runner.py` as the
comparator; the `Persistence` protocol (`persistence.py`, `postgres_persistence.py`) as the
boundary the checkpointer must not cross.

**Trap, and it is the whole risk of this step:** the `jobs` row stays the source of truth.
The API, the Tasks UI, the 24 h auto-resume sweep, and the checkpoint-prompt shape
(`{kind, question, options, default, context_ref}` — a pinned contract) all read Postgres
directly. A LangGraph checkpointer that becomes a second, divergent store of run state is
how agents mode would start silently affecting the product. Keep it strictly additive.

**Done when:** an agents-mode job parks on a checkpoint, is answered through the ordinary
Tasks UI, and resumes correctly — plus the written comparison.

---

## Step 4 — L4: the investigator crew (FR12)

*Gate: any time after Phase 1. Deliberately last: it is the only step that ships a user-visible feature, and it is the one with no deterministic comparator.*

**Achieve.** A new `job_type: investigate` producing a structured brief — reviews and
management reputation, scam signals and cross-listing price checks, area context — from a
spawnable crew synthesized by an orchestrator. Slow, costly, or occasionally dumb is
acceptable here by design (FR12); nothing downstream depends on it.

**Use:** `llm/tools.py::run_agent_loop` with a new per-stage allow-list in `STAGE_TOOLS`
(turn- and char-budgeted like every other loop); the ENRICH Maps/Places seams in
`stages/base.py` for area and ratings context; DISCOVER's OpenRouter native-search pattern
for the reputation legs; the drawer's **Investigate** action, which DESIGN §13.2 already
specifies.

**Needs before it lands:** a `job_type` enum value + migration (per AGENTS.md's migration
versioning rule), a §16 tool allow-list decision, and a §20 entry — a new job type reaching
the UI is a material change even off the critical path.

---

## Step 5 — Track exit: the written report

The actual deliverable of the learning objective (§2.5, §19): a written eval report in
`docs/` — accuracy, tokens, latency, and a verdict on what multi-agent bought and what it
cost, per component. Not a summary of what was built; a judgment, with the numbers that
support it and the ones that undercut it.

**Adoption rule, in force the whole way through (§10.11):** no agents-mode component
becomes default behavior without eval-harness evidence **and** a §20 Decision Log entry.
Neither half alone is sufficient.

---

## Cross-cutting rules for every step

1. **Isolation is structural.** All track code in `worker/src/manzil_worker/agents/`; that
   package imports the truth layer and the RunState/persistence contract, and nothing on the
   critical path imports back. Enforceable with a one-line import test — worth adding at L1.
2. **The truth layer is invariant.** VERIFY checks 1–3, the RECONCILE ladder, SCORE. Agents
   mode may change *who does the work*, never *what counts as correct*.
3. **Every LLM call is traced, both modes, from the first call** (NFR6). An untraced call is
   a bug, and here it is also a hole in the report.
4. **No live LLM calls in CI, ever.** Track tests run in replay against committed synthetic
   fixtures; graded runs happen locally against the gitignored corpus and labels.
5. **Provider SDK imports stay inside `llm/`.** LangGraph is not a provider SDK, but anything
   it wants to call a model with must still go through `call_structured` / `call_agent` /
   `call_vision`.
6. **A negative result is a result.** The track's deliverable is earned judgment. "We built
   it, measured it, and it was not worth it" is the most valuable sentence the report can
   contain, and the one most likely to be true of at least one component.

---

## Suggested first three sessions

1. **Bench rerun + Phase 0 exit paperwork** (step 0). No new code; unblocks everything.
2. **`agents/critic.py` + harness integration** (step 1, build half). Replay-testable, no
   product surface, ~one focused session.
3. **Critic A/B run + write-up + keep/kill** (step 1, measure half). First real answer the
   track produces.

Then decide whether L2 gets its four sessions now or waits for Phase 3's tail to clear.
