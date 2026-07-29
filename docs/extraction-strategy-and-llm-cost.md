# Extraction Strategy, LLM Cost, and the ETL/RAG Question

**Status: advisory analysis (2026-07-28).** This document answers three architecture
questions against the pipeline as it exists today. It changes no design. DESIGN.md
remains authoritative; adopting any recommendation below that alters behavior
requires its own §20 Decision Log entry, and anything touching a deferred item
(DESIGN §18) needs an explicit decision first.

The questions:

1. Is Floor Plan / Criterion extraction better done by cleaning the HTML and feeding
   it to an LLM with structured output, or by embedding the HTML into vectors and
   using retrieval (RAG)? Or some other way entirely?
2. What minimizes LLM calls (and therefore cost) while maximizing accuracy, across
   every stage — extraction, discovery, all of it?
3. Would the current setup benefit from an ETL pipeline and/or RAG?

Short verdicts, argued in full below:

1. **Cleaned text + one forced-schema call is the right architecture for this
   problem, and the current implementation is already a strong version of it.**
   Embedding-based retrieval is the wrong tool for whole-document extraction — it
   attacks the smaller half of the cost while structurally reintroducing the exact
   failure mode (silently dropped facts) that the cleaner's guards exist to prevent.
2. Calls are minimized by four disciplines the pipeline already practices:
   deterministic guards in front of every call, batching, content-addressed caching,
   and conditionality. The remaining headroom is small and enumerated in §5.
3. **The pipeline already *is* an ETL pipeline** — with stronger guarantees than a
   generic framework would provide — and **RAG has no load-bearing role** at this
   corpus size and query shape. The first genuinely RAG-shaped feature on the
   horizon is the FR12 deep-dive investigator, which lives in agents mode, off the
   critical path.

---

## 1. What "embedding the HTML into a vector" actually means

Worth pinning down, because the comparison is often framed as if an LLM could "read"
an embedding. It cannot. An embedding is a lossy fixed-size numeric summary used for
*similarity search*, not a representation a model can decode facts from. The
RAG architecture is:

```
chunk the document → embed each chunk → store vectors
→ at question time: embed the query, retrieve top-k similar chunks
→ stuff those chunks (as plain text) into the LLM prompt
```

So the real comparison is not "text vs. vectors" — the LLM reads text either way.
It is:

- **(A) Whole cleaned page in context** — the model sees everything; one call.
- **(B) Retrieved chunks in context** — the model sees the top-k chunks a
  similarity function guessed were relevant.

RAG earns its complexity when the corpus is far larger than a context window and
the task is a *point lookup* — "find the passage that answers this question" across
thousands of documents. Neither condition holds here, per §2.

---

## 2. Why cleaned-text + forced schema wins for this workload

### 2.1 The task is enumeration over one document, not lookup across many

EXTRACT's job (DESIGN §10.2 P1, `worker/src/manzil_worker/stages/extract.py`) is:
given **one** listing page, emit **every** Catalog claim, **every** Floor Plan,
identity, contact, pet costs, utilities, and both fee blocks — value + confidence +
`evidence_quote` each — in a single response validated against a schema generated
from `criteria_catalog` (`stages/schema_gen.py`). That is an *enumeration* task:
completeness over the whole document is the success criterion.

Top-k similarity retrieval has no completeness guarantee. "Retrieve the chunks
relevant to fees" works when fees are one passage; listing pages scatter them
across marketing tables, footers, pet-policy accordions, and `__NEXT_DATA__` JSON
blobs. A retrieval miss is not an error you can catch — it is a **silent absence**.
And the system's verification layer cannot help: VERIFY (checks 1–4,
`stages/verify.py`) audits claims that *were made* — evidence fuzzy-location,
plausibility bands, cross-field consistency. Nothing audits claims that were never
made because the model never saw the text. The only structural guard against missed
facts is giving the model the whole page.

This failure mode is not hypothetical — it is the one already fought and won
*deterministically* in the cleaner (`worker/src/manzil_worker/fetching/cleaner.py`):
trafilatura silently prunes floor-plan cards on rentcafe-style markup, readability
drops fee tables. The response was the price-retention guard (reject any extraction
keeping <50% of rendered price tokens), the fee-table re-render, the floor-plan-card
retention guard, and the `[EMBEDDED DATA]` miner. Swapping in probabilistic chunk
retrieval would make that same class of loss structural and unguardable, since
there is no equivalent of the price-retention check for "did the retriever fetch
every relevant chunk."

### 2.2 Context scarcity — RAG's reason to exist — does not apply

A cleaned listing page runs roughly 3–15k tokens after the cleaner's 5–10× reduction
(DESIGN §7). The workhorse model (`google/gemini-3-flash-preview`) has a context
window three orders of magnitude larger. RAG is a workaround for documents that
don't fit; these fit with room for a hundred more. The corpus is also small in
absolute terms — a hunt is tens of listings, ~≤3 Sources each — and each extraction
is strictly per-document (per-Source isolation is a *design invariant*: Source-local
claims, Source-local Floor Plan identity, per-Source VERIFY). There is no
cross-document question at extraction time for retrieval to answer.

### 2.3 The cost math points the wrong way for RAG

Per EXTRACT call at current pins (`llm/config.py`: $0.50/MTok in, $3.00/MTok out,
Gemini implicit cache reads at 25%):

| Component | Typical size | Cost |
|---|---|---|
| Stable prefix (prompt + rules; schema rides in `tools`) | ~3–6k tok, largely cache-served | ~$0.001–0.003 |
| Page content (cleaned text + embedded-data digest) | ~3–15k tok | ~$0.002–0.008 |
| Output (full claim set, `STAGE_MAX_TOKENS["extract"] = 8192`) | ~2–4k tok | ~$0.006–0.012 |

**Output is the largest or co-largest line, and retrieval cannot shrink it by one
token** — the full catalog of claims must be emitted regardless of how the page
text arrived. Best case, RAG halves the middle row: ~$0.003 saved per call, call it
a cent per listing, in exchange for an embedding model, a vector store, a chunking
policy, recall risk on exactly the vague-fee language §9.5 identifies as the
adversarial surface, and a new component to version and test. DESIGN §15's own
lever 6 names the budget correctly: complexity is the real cost. This trade fails
it decisively.

### 2.4 The evidence audit couples extraction quality to full-page visibility

Every claim carries an `evidence_quote` that VERIFY check 1 must fuzzy-locate in
the fetched page (the anti-hallucination *and* anti-injection control, DESIGN
§10.5/§16). The guarantee "fact absent from page → claim demoted" holds because
the model's input *is* the page. Feed it chunks and the audit still passes for
what was claimed — but the system-level property quietly degrades from "the
extraction reflects the page" to "the extraction reflects what the retriever
sampled." For a tool whose §2.3 prime directive is *never make a listing look
cheaper than it is*, a missing mandatory fee is the worst possible defect. The
architecture should keep the property, not trade it for pennies of input tokens.

### 2.5 What the current design already gets right, named

It is worth stating that the existing pipeline is not merely "fine" — it already
implements the pattern the industry converged on for this problem shape:

- **Deterministic retrieval with 100% recall intent.** The cleaner *is* the
  "retrieval" step: rule-based, guard-checked, testable, and it degrades toward
  keeping more (trafilatura → readability → script-stripped visible text) rather
  than silently keeping less.
- **Schema-first, forced tool use.** The model cannot answer except in schema shape
  (DESIGN §10.2 P1); no prose parsing; validation-failure retry exactly once with
  the error *leading* the content, then a hard job error.
- **Verification as a separate, mostly-deterministic stage.** Checks 1–3 are plain
  code; only cross-field consistency spends a call.
- **Structured data mined before the LLM.** JSON-LD / `__NEXT_DATA__` / preloaded
  state land in `[EMBEDDED DATA]`, so the model reads the site's own database
  export instead of guessing from prose — cheap accuracy the average RAG stack
  never sees.

---

## 3. The "some other way" survey

Alternatives that a redesign conversation should actually weigh, with verdicts:

| Approach | What it is | Verdict for Manzil |
|---|---|---|
| **Deterministic embedded-data fast path** | When `[EMBEDDED DATA]` carries complete floor-plan/fee JSON, map it to claims in code and skip (or shrink) the EXTRACT call | The only near-term idea with real upside: zero-hallucination values at zero token cost on the sites that ship state blobs. But it is a **second data path** — the same reason the Apify structured-actor variant was explicitly deferred (DESIGN §10.7). Needs eval-harness evidence that code-mapped claims match LLM-extracted ones, plus a §20 decision. Measure first, on the bench corpus. |
| **LLM-writes-the-scraper-once** | Have a model author a per-domain deterministic extractor, cache it, run code thereafter; re-invoke the LLM only when the parser breaks | The known scaling endgame for high-volume scraping (thousands of pages/domain). At tens of listings across dozens of long-tail domains, parser authorship + breakage detection costs more than it saves. Revisit only if volume grows ~100×. |
| **Two-pass extraction** (cheap model locates spans → strong model structures) | Split locate/structure across model tiers | Solves a quality problem the bench says doesn't exist: the single flash-tier call scores 0.904 criterion accuracy (P0-13). Adds a call per Source. No. |
| **Fine-tuned small model** | Tune an open-weight model on labeled extractions | The 10-listing labeled set is ~two orders of magnitude short of a training set, and the schema churns with the Catalog. No. |
| **Raw HTML into the LLM, no cleaner** | Skip cleaning; modern contexts are big | Pays 5–10× input tokens for *worse* accuracy (boilerplate dilutes attention; nav/footer noise breeds spurious claims) and breaks the evidence-audit economics. The cleaner is the highest-ROI component in the pipeline. No. |
| **RAG over listing pages** | Chunk/embed/retrieve per §1 | Rejected per §2. |

---

## 4. Where embeddings *would* legitimately fit — and why they still don't, today

Being precise, because "no vector DB" should not read as "embeddings are useless":

- **DEDUPE similarity.** Property matching is geocode `<100 m` + name similarity
  with a checkpoint for the gray zone (DESIGN §10.3). Name embeddings could soften
  string matching, but the geocode gate already carries the discrimination and the
  checkpoint absorbs ambiguity. No gap to fill.
- **RECONCILE semantic equivalence** ("W/D in unit" ≡ "in-unit laundry").
  Embedding-similarity clustering could replace the LLM here — but look at the
  implementation (`stages/reconcile.py::_equivalence_keys`): it fires **only** when
  non-numeric values genuinely conflict after canonicalization, batches every
  conflicted claim into **one** structured call, and falls back to exact matching
  on any protocol violation. That is at most one cheap call per job. An embedding
  service (model choice, threshold tuning, infra) costs more than it saves and is
  *less* accurate at the boundary (embeddings are notoriously loose about negation
  and scope: "washer/dryer hookups" sits embarrassingly close to "in-unit washer/
  dryer" in embedding space — a distinction this domain must not blur).
- **Image near-duplicate detection.** Already solved deterministically with a
  64-bit difference hash at Hamming ≤5 (DESIGN §10.8) — cheaper, reproducible, and
  cache-keyable in ways CLIP-style embeddings are not.
- **Corpus-level question answering** — "what do reviews across the web say about
  this management company?" This is the first *real* RAG shape in the product's
  future: the FR12 deep-dive investigator (DESIGN §10.11), which is agents-mode,
  off the critical path, and judged by evals. If retrieval infrastructure ever
  enters this codebase, it enters there — never under EXTRACT.

---

## 5. Minimizing LLM calls: the principles and the per-stage audit

### 5.1 The four disciplines (all already in force)

1. **Deterministic guards in front of every call.** Heuristics reject before models
   confirm (VALIDATE's zero-spend rejection; fetch-outcome classification; VERIFY
   checks 1–3 in code; RECONCILE's ladder where the LLM only normalizes phrasing).
2. **Batch N judgments into one call.** IMAGE_CLASSIFY sends ≤30 labeled thumbnails
   in one call; VISION sends all rating sheets + targets in one; equivalence sends
   every conflicted claim in one; EXTRACT itself is the pattern's exemplar — the
   *entire* Catalog in one call rather than per-criterion calls (a naive
   per-criterion design would be ~40× the calls for the same information).
3. **Content-addressed caching.** `cleaned_text_hash` gating is the keystone
   (DESIGN §14): unchanged page → no EXTRACT, no VERIFY; steady-state refresh cost
   rounds to a fetch and a hash compare. Image classification caches by content
   hash + model/prompt; quality reruns only on target-digest change; Places is
   cached forever; global Property reuse makes re-adding a known Property to a new
   hunt a $0 SCORE.
4. **Conditionality.** A call happens only when a genuine judgment exists:
   plan-assist only when DISCOVER yields >3 same-Property candidates; equivalence
   only on semantic conflict; escalation fetches only for unresolved
   decision-relevant fields, bounded to one official fetch + one sibling round.

Plus two cost multipliers on top: **prompt caching** on stable per-stage prefixes
(`cache_control` applied in `llm/client.py`; Anthropic reads at 10%, Gemini at 25%)
and **bench-driven model-tier assignment** (P0-13/14: the workhorse pair moved to a
model 63% cheaper *and* more accurate — the rare free lunch, but only visible
because the eval harness existed).

### 5.2 Per-stage call audit (first ingestion, default policy, ~3 Sources)

| Stage | LLM calls today | What bounds it | Remaining headroom |
|---|---|---|---|
| PLAN | 0–1 (`plan_assist`, only >3 candidates) | deterministic-first planner | none worth taking |
| VALIDATE_URL | 0 | pure code | — |
| VALIDATE | 1/Source | heuristics reject free | **skip the confirm call when deterministic positives are overwhelming** (JSON-LD `ApartmentComplex`/`Offer` block present — already a "strong positive that short-circuits doubt" in fetch classification, §10.7). Small, real, low-risk; measure false-accept rate on the corpus first |
| FETCH | 0 | tier ladder, registry | — |
| EXTRACT | 1/Source (+≤1 schema-retry) | one call for the whole Catalog; hash gating on refresh | **(a)** audit prompt-cache hit-rate in Langfuse — the prefix only pays if it is byte-stable across calls; **(b)** the embedded-data fast path (§3), eval-gated |
| DEDUPE | 0 | geocode + name similarity; checkpoint for gray zone | — |
| DISCOVER | 1 bounded loop (≤6 turns, ≤3 searches, ≤$0.04 reserved) | turn/search caps; skipped under `trust_link`; candidate pool persisted for escalation reuse | refresh jobs already re-plan rather than re-discover; nothing cheap left |
| VERIFY | 1/Source (check 4 only) | checks 1–3 are code; early-return when no claims | marginal: could skip check 4 when ≤1 claim survives — not worth the special case |
| RECONCILE | 0–1 (equivalence, conflict-gated) | ladder is deterministic; single-Source short-circuits | none |
| IMAGE_FETCH / IMAGE_CLASSIFY | 0 / 1 batched vision call (≤30 thumbs) | content-hash cache; `plan.skipped.VISION` when unchanged | none |
| VISION | 1 anchored call (≤8 targets + 5 sheets) | deterministic selector, quotas, independent digests | none |
| ENRICH | 1 (review synthesis) + free-tier APIs | Places cached forever; baselines on a 120-day scheduler tick | none |
| CUSTOM_MATCH | per custom Criterion (text = 1 forced-schema call; location = bounded tool loop) | `requires_tool` fixed at authoring time | if text custom Criteria ever number more than a couple per hunt, batch them into one call — same pattern as equivalence |
| SCORE | 0 | pure engine, by design | — (re-score is $0; this is why Rubric edits are free) |

Totals: a first ingestion is roughly **13–15 calls** (~$0.10–0.12, DESIGN §15);
an unchanged-content refresh is **~0**; a re-score is **0**. The structural point:
the expensive stages are already one-call-per-unit-of-work, the cheap stages are
already guarded or free, and escalation — the only mechanism that multiplies calls —
is bounded and rare by construction (worst case ~7 extractions, §10.6).

The honest conclusion is that **call count is no longer where the leverage is.**
The remaining cost levers are hit-rate levers (cache-prefix stability, hash-gating
coverage) and model-pin levers (bench evidence), not architectural ones.

### 5.3 Accuracy is bought elsewhere than calls

Maximizing accuracy in this pipeline has never meant more calls — it means:

- **Better input** — the cleaner's retention guards and embedded-data mining did
  more for extraction accuracy than any model swap could (the facts must survive
  to be extracted).
- **Verification and reconciliation as a truth layer** — evidence audit,
  plausibility bands, family-deduped voting, conservative tie-breaks. A wrong value
  gets demoted, outvoted, or checkpointed; the model doesn't have to be perfect,
  only auditable.
- **The eval harness** — the only legitimate arbiter for model/prompt changes
  (AGENTS.md: eyeballing is not validation). Every recommendation in this document
  that touches behavior routes through it.

---

## 6. Would an ETL framework help?

The pipeline already **is** an ETL system, stage for stage:

| ETL concept | Manzil implementation |
|---|---|
| Extract | FETCH (tier ladder, adapter registry, outcome classifier) |
| Staging / raw zone | raw HTML → `CleanedPage` with `text_hash`, persisted before use |
| Transform | EXTRACT → VERIFY → RECONCILE (LLM + deterministic code) |
| Load | persist-before-advance into Postgres, append-only extraction lineage |
| Orchestration | plan-manifest runner with resume cursor (`§10.2 The runner`) |
| Incremental processing | content-hash gating + TTL classes (§14) |
| Lineage / audit | `job_events`, `resolution_rule`, candidate-provenance joins |
| Dead-lettering | job errors, `WAITING_USER` checkpoints with 24 h auto-resume |

What Airflow/Dagster/Prefect would add: a DAG UI, a scheduler, and distributed
executors. The first two exist (Tasks history; the scheduler tick), the third is
unneeded at one in-process worker, and the price is an orchestration runtime to
operate — against §15's "not worth optimizing: anything requiring new
infrastructure." dbt-style SQL transforms don't fit either: the transforms here
are LLM calls and Python, not SQL models.

There is also a property the generic frameworks would actively obscure:
**persist-before-advance is load-bearing for checkpoints** (`WAITING_USER` pausing
*mid-run* into a user question and resuming with the answer). That interaction
pattern maps awkwardly onto batch-DAG orchestrators; the hand-rolled runner
expresses it in five lines. Verdict: no framework. Keep borrowing ETL *practices*
(staging, idempotency, lineage — all present) without the machinery.

---

## 7. Would RAG help the system anywhere?

Consolidating §2 and §4: **not on the critical path.**

- **Extraction:** rejected on accuracy grounds (recall over enumeration), cost
  grounds (output tokens dominate; retrieval only shrinks input), and design
  grounds (the evidence audit presumes full-page visibility).
- **Retrieval over extracted facts:** already exact. Facts land as structured rows
  in Postgres; the "retrieval layer" is SQL through PostgREST/RLS, which is
  deterministic and free. Embedding structured facts to search them
  probabilistically would be strictly worse.
- **Discovery:** DISCOVER's problem is *finding pages on the open web*, served by
  provider-hosted web search — a corpus nobody local can embed. Not a RAG shape.
- **The one future fit:** the FR12 investigator (reviews, reputation, scam
  signals across many fetched pages) is a genuine chunk-retrieve-synthesize
  workload. It belongs to agents mode (`worker/src/manzil_worker/agents/`, judged
  by the eval harness, never imported by the critical path), and any vector
  infrastructure should arrive there or not at all.

---

## 8. Recommendations, ranked

**Keep (no action):**

1. Cleaned-text → single forced-schema EXTRACT per Source. No RAG, no vector
   store, no ETL framework, no raw-HTML extraction.
2. The four call-minimization disciplines and the truth layer exactly as they are.

**Cheap, measurable, worth doing (each needs eval evidence; behavior changes need
§20):**

3. **Audit prompt-cache hit-rates in Langfuse** for the workhorse stages. The
   cacheable prefix only pays when byte-stable across calls; a silent prefix
   instability (e.g., anything interpolated per-run into the prompt file) would be
   invisible except in the cache-read token counts. Pure observation first; fix
   only if hits are missing.
4. **VALIDATE deterministic-positive skip:** when the fetch classifier already
   found JSON-LD rental schema blocks, skip the confirm call. Bench the
   false-accept rate on the corpus before enabling. Saves ~1 call/Source — small
   money, but it is the only stage where a call still fires on evidence code has
   already judged.

**Measure-first experiment (explicitly a second data path — treat like the
deferred Apify decision):**

5. **Embedded-data fast path:** on pages whose `[EMBEDDED DATA]` digest contains
   complete floor-plan/fee structures, compare code-mapped claims against
   LLM-extracted claims across the bench corpus. Adopt only on harness evidence +
   a §20 entry. Upside: zero-cost, zero-hallucination values on state-blob sites.
   Risk: schema drift per site family, and divergence between two extraction paths.

**Don't build (revisit triggers noted):**

6. Per-domain cached extractors (LLM-authored or hand-written) — revisit at ~100×
   listing volume.
7. Embedding-based equivalence/dedupe — revisit only if the equivalence call or
   dedupe checkpoint rate becomes a measured problem.
8. Fine-tuning — revisit if a labeled corpus ~100× the current bench ever exists.
9. Vector infrastructure of any kind on the critical path — the only sanctioned
   entry point is the FR12 investigator in agents mode.
