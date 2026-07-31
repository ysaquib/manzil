## Executive summary

   Question                 Current state                                                                                                      Recommendation
  ━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Retry one stage          Automatic retries exist for retryable failures inside the current stage. No user-selectable stage retry.           Fix existing retry/cancel correctness first. Then add a new reprocess Job with dependency-aware downstream
                                                                                                                                               invalidation—not arbitrary stage-only execution.
  ───────────────────────  ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────  ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
   Retry from a stage       Not supported. The existing Retry resumes the failed/cancelled Job at its persisted cursor.                        Never manually rewind cursor; stale downstream state would remain in the snapshot.
  ───────────────────────  ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────  ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
   Delete a Job’s output    No. Listing “delete” only archives. Some outputs have job_id, but most global facts are shared or upserted and     Provide guarded rebuild and Property-purge operations, not generic rollback-by-Job.
                            cannot safely be attributed exclusively to one Job.
  ───────────────────────  ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────  ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
   Refresh a Listing        Full refresh is designed but not implemented. Only special enrich and discover refresh scopes exist.               P3-12 should be prioritized; it is also the largest remaining cost optimization.
  ───────────────────────  ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────  ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
   Reduce LLM cost          Rescore is free, but the designed cheap refresh path does not exist yet.                                           Implement P3-12/hash gating; then tune Source Policy, cache hits, and model pins from bench evidence.
  ───────────────────────  ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────  ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
   Classifier confusion     The current evidence primarily shows malformed batch/hash responses, not measured classification inaccuracy.       Separate protocol reliability from accuracy, eliminate the two-hash output contract, then run the already-
                                                                                                                                               labeled 294-image bench.

  There are also two important current working-tree conflicts:

  - DESIGN.md and IMPLEMENTATION.md pin IMAGE_CLASSIFY to Gemini 3 Flash Preview and VISION to Sonnet 4.6.
  - The uncommitted worker/src/manzil_worker/llm/config.py:29 instead assigns both to google/gemini-3.6-flash. That slug is absent from MODEL_PRICES, so cost accounting—and likely the calls themselves—will fail rather than merely classify poorly.
  - The same uncommitted file changes DISCOVER from Haiku to openai/gpt-5.6-luna without the required recorded model decision.

  That conflict needs an explicit resolution before treating current live behavior as conforming to the design.

  ## 1. Retrying only a specific Stage

  There are two retry mechanisms today.

  ### Automatic Stage retries

  The runner catches StageRetryable, applies exponential backoff, and tries the same Stage again. STAGE_RETRIES = 3, so this is the initial attempt plus up to three retries. See worker/src/manzil_worker/runner.py:113.

  Only these paths currently raise StageRetryable:

  - FETCH transport/error outcomes
  - DISCOVER malformed final JSON
  - IMAGE_FETCH Storage upload failure

  EXTRACT also has its own one-time corrective retry for schema validation, but a second invalid response becomes a Job failure rather than entering the generic retry loop.

  ### Manual Job retry

  The API exposes POST /jobs/{id}/retry, but only for failed or cancelled Jobs. It resets queue attempts and requeues the same row; it does not accept a Stage. See api/src/manzil_api/jobs/service.py:137.

  Because the persisted RunState contains the cursor, this normally resumes at the Stage that did not advance. It is “retry this Job from its current durable boundary,” not “retry an arbitrary Stage.”

  ### A correctness bug in manual Retry

  The API resets the database row’s state and error, but does not reset payload.run_state.status or payload.run_state.error. The worker reconstructs the state directly from that snapshot at worker/src/manzil_worker/queue.py:244.

  Consequences after a failed Job is retried:

  - The first successful Stage save can write failed back into the Job row temporarily.
  - The stale error can reappear.
  - The Job may eventually reach done, but retain the old error, because the runner only changes status to done; it never clears state.error.

  The existing API test only checks the immediate row update. It does not dispatch the retried Job end-to-end.

  Cancellation has a related problem: design says cancellation is checked between Stages, but the runner has no cancellation check. A running worker can overwrite the API’s cancelled state on its next persistence save.

  These should be fixed before expanding retry functionality.

  ### Should stage-selectable retry be implemented?

  Yes, but the product operation should be called “Reprocess from Stage,” not “retry only this Stage.”

  A Stage’s output feeds downstream truth. Rerunning EXTRACT alone while retaining old VERIFY, RECONCILE, and SCORE output would be invalid. The system should compute the downstream closure automatically:

   Requested starting Stage    Minimum work that must be invalidated/rerun
  ━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   PLAN                        New Job and new plan
  ──────────────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────
   FETCH                       VALIDATE → EXTRACT → relevant identity/discovery → VERIFY → RECONCILE → image path as needed → SCORE
  ──────────────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────
   EXTRACT                     DEDUPE when primary identity may change → VERIFY → RECONCILE → SCORE
  ──────────────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────
   DISCOVER                    sibling FETCH/VALIDATE/EXTRACT/VERIFY → RECONCILE → SCORE
  ──────────────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────
   VERIFY                      RECONCILE → SCORE
  ──────────────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────
   RECONCILE                   SCORE
  ──────────────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────
   IMAGE_FETCH                 IMAGE_CLASSIFY → VISION → SCORE
  ──────────────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────
   IMAGE_CLASSIFY              VISION → SCORE
  ──────────────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────
   VISION                      SCORE
  ──────────────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────
   ENRICH or CUSTOM_MATCH      SCORE
  ──────────────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────
   SCORE                       SCORE only; this already maps naturally to a rescore Job

  DEDUPE should not be a casual user-facing starting point because it can change global Property identity. Keep it inside a full rebuild or an admin identity operation.

  The safest representation is a new Job with:

  - parent_job_id
  - trigger = user:reprocess
  - requested_start_stage or, preferably, requested field/classes
  - a fresh manifest
  - explicit cache-bypass controls
  - an audit event identifying the source Job

  Do not mutate the old Job’s cursor; Job History should remain immutable.

  ## 2. Retrying a Listing from a specific Stage

  This is not supported today.

  Manually editing payload.run_state.cursor would be unsafe because the snapshot contains all prior and later Stage-owned fields: sources, claims, Floor Plans, resolved claims, images, selected targets, scores, warnings, and checkpoint state. Rewinding
  only the cursor does not clear any of them.

  Potential failure modes include:

  - New EXTRACT claims mixed with old resolved claims.
  - New classifier output feeding old VISION targets.
  - Old sibling sources remaining after rerunning DISCOVER.
  - An old canonical property_id combined with a rerun of pre-DEDUPE work.
  - Old warnings, error, checkpoint answer, and cost being carried forward.
  - A long-delayed retry using fetched text frozen in the Job snapshot even though the Source is now stale.

  Each Stage therefore needs either:

  1. A declared “owned fields” reset function, plus invalidation of downstream owners; or
  2. Preferably, a new Job reconstructed from durable database/cache inputs instead of cloning arbitrary in-memory state.

  The latter is substantially easier to reason about.

  ## 3. Deleting everything produced by a Job

  There is no such operation.

  The API’s DELETE /listings/{id} is a misleading legacy route: it sets hunt_listings.status = archived. Nothing is destroyed. See api/src/manzil_api/listings/service.py:93. The UI correctly calls this “Archive.”

  A rollback-by-Job is also not generally well-defined:

  - Extractions have a nullable job_id, but they are append-only global Property facts.
  - Floor Plans have no producer Job ownership.
  - Property Sources are upserted and shared.
  - Property images are content-addressed and reused.
  - Floor Plan/image associations have producer provenance but may remain valid independently.
  - Scores and human artifacts live on the Listing.
  - Another Hunt may already use the same Property facts.
  - Deleting the newest Extraction rows could make older, stale rows current again.
  - FETCH updates the adapter registry, and IMAGE_FETCH can upload bytes before the terminal database projection. Those side effects are not wholly represented by job_id.

  ### Recommended operations

  Provide three distinct controls:

  1. Archive Listing — already present and reversible.
  2. Rebuild Property data — a new authoritative Job that:
      - bypasses freshness caches;
      - refetches selected/all Sources;
      - re-extracts, verifies, reconciles, reclassifies images, and rescrores;
      - appends not-found/retirement observations only after complete successful Source refreshes;
      - preserves append-only history;
      - preserves Listing opinions by default: Overrides, comments, ratings, pins, fees, and Interest Status.

     This is the normal “start over computationally” operation.

  3. Hard purge Property — guarded admin operation, with a dry-run impact report:
      - Require no other active Listing referencing the Property, unless an explicit force acknowledgement names all affected Hunts.
      - Cancel/finish all active Jobs first.
      - Delete the global Property row so database cascades remove Sources, Floor Plans, Extractions, images, and associations.
      - Separately delete unreferenced Storage objects.
      - Delete or recreate the Listing association and enqueue a fresh ingest.
      - Record an immutable operator audit entry outside the deleted Job tree.

  The existing manzil purge-images is narrower: it only removes non-current, unassociated, uncited images. It is not a Property or Job reset.

  I would not implement “delete output of Job X.” Implement compensating/rebuild semantics and a guarded whole-Property purge.

  ## 4. Refreshing a Listing

  A general Listing refresh does not currently exist.

  DESIGN.md specifies:

  - POST /listings/{id}/refresh
  - POST /hunts/{id}/refresh
  - TTL-driven scheduled refresh
  - field-scoped refresh
  - stale badges
  - content-hash gating

  But P3-12 explicitly says those endpoints were never built; see .claude/plans/phase-3-agent-system.md:635.

  Only two interim refresh scopes exist:

  - scope=enrich: hunt-level Maps/location recomputation.
  - scope=discover: runs when Source Policy is widened; discovers Sources but does not refetch or rescore the full Listing.

  Any other scope fails with “full refresh lands P3-12” in worker/src/manzil_worker/queue.py:1560.

  ### Staleness risks today

  Re-adding/retrying is not a safe substitute for refresh.

  The current ingest PLAN skips the network for a Source considered fresh, but it still leaves EXTRACT and VERIFY in the manifest. Thus the full design promise “unchanged hash skips EXTRACT+VERIFY” has not landed.

  More seriously, the terminal projection loops over all state.sources and sets last_fetched_at and last_success_at to now(), including a Source loaded from cache rather than fetched. See worker/src/manzil_worker/queue.py:531. Repeated cache-skipping
  ingests can therefore renew the apparent freshness timestamp without observing the page.

  Other risks:

  - A retried old Job never replans around elapsed TTLs.
  - No stale badge tells the user that current rent/availability may be old.
  - Sources found by DISCOVER may remain link-only indefinitely.
  - Price/availability history cannot become useful until routine refresh exists.

  The append-only lifecycle does correctly protect against destructive partial refresh: silence only retires facts, Floor Plans, or associations after successful complete Source work. That foundation is good. The missing problem is orchestration.

  ### What P3-12 should implement

  Prioritize it before convenience-level stage retry:

  - A new refresh Job, never reuse an old ingest Job.
  - Replan from current Source timestamps and requested field classes.
  - Fetch first, then compare cleaned_text_hash.
  - Only a real network result updates fetch/success timestamps.
  - Unchanged hash skips EXTRACT and VERIFY.
  - fields=pricing maps to pricing-producing Sources and downstream RECONCILE/SCORE.
  - Source-local complete/partial authority remains intact.
  - Hunt refresh fans out per Listing with per-domain rate limiting.
  - Add stale badges from the tightest relevant TTL.
  - Manual “force refresh” bypasses TTL but not safety or Source Policy.

  ## 5. Reducing LLM costs

  The largest lever is finishing P3-12. The design estimates $0.10–0.12 for a new Listing, under $0.01 for refresh, and $0 for rescore, but the cheap refresh path is not currently available.

  Priority order:

  1. Implement genuine content-hash refresh gating. Without it, refreshes eventually dominate the bill.
  2. Do not re-ingest or retry to refresh. Current “hash fresh” ingestion still reruns LLM work and can renew timestamps incorrectly.
  3. Use Source Policy intentionally.
      - trust_link: cheapest, but explicitly removes cross-Source corroboration.
      - tier_1 or tiers_1_2: reasonable for lower-risk Listings.
      - tiers_1_2_3: keep for Gate-sensitive or hostile pages.

     This is an accuracy/assurance tradeoff, not a free optimization.

  4. Prefer Overrides and rescore for human corrections. Rubric edits, Override changes, utility corrections, and generalized-vision policy changes enqueue deterministic rescoring with no LLM call.
  5. Measure cost by Stage in Langfuse. The Job History already shows cost_actual_usd; use trace-level totals to identify whether DISCOVER, EXTRACT, or VISION is actually dominating before tuning.
  6. Audit prompt-cache hit rates. Stable prompt/schema prefixes only save money when byte-stable. EXTRACT recordings show substantial cache reads, so this is already working to some degree.
  7. Keep Source escalation decision-relevant. The current RECONCILE ladder already does this correctly: official/sibling escalation is only bought for unresolved decision-relevant fields.
  8. Condition VISION on real demand. Consider having PLAN skip kitchen classification/quality when no Hunt using the Property enables kitchen_quality. This is a material design choice because the current system intentionally extracts the whole Catalog
     for global reuse. Bench the savings against later reprocessing costs.

  9. Do not add RAG. The repository’s own analysis is correct: listing extraction is full-document enumeration, output tokens are a large part of the bill, and RAG introduces silent omission risk for fees. See docs/extraction-strategy-and-llm-cost.md:1.
  10. Resolve the current model-pin conflict. Do not use gemini-3.6-flash merely because it may be cheaper until it is priced, routed successfully, benchmarked, and recorded in the Decision Log.

  ## 6. Image-classifier confusion and deferred benches

  ### What is actually failing

  The evidence does not yet show that the classifier is semantically inaccurate. The strict bench aborts earlier because every model violated the response identity contract:

  - Gemini 3 Flash Preview: 29/30 returned.
  - Gemini 3.1 Flash Lite: duplicate record.
  - Gemini 2.5 Flash Lite: one missing and one unknown.
  - Sonnet 4.6: duplicate record.

  The current production path tolerates up to two missing/surplus anomalies and records them as warnings, but the benchmark deliberately remains strict.

  There is a particularly confusing identity contract:

  - Each image block is authenticated by the SHA-256 of the generated thumbnail.
  - Its label contains target:<original-property-image-hash>.
  - The model must output the thumbnail hash, not the original hash.

  The diagnostic run where all 30 were “missing” and all 30 outputs “unknown” is consistent with the model returning the original hashes from the labels instead of the thumbnail hashes. This is protocol confusion created by our interface, not necessarily
  visual confusion.

  The classifier then selects only images marked:

  - high confidence;
  - kitchen assessable;
  - not irrelevant;
  - not a diagram;
  - usable framing.

  See worker/src/manzil_worker/stages/image_classify.py:250. This is conservative but can cause false negatives if the model uses medium confidence liberally.

  ### Recommended classifier contract

  Stop asking the model to copy SHA-256 values.

  Use short per-call IDs such as img_01…img_30, and generate a dynamic schema whose output ID is constrained to that exact enum. Map the short ID to the original hash deterministically after parsing. Keep both hashes in trusted application state, not in
  the model’s output contract.

  That should remove the largest protocol failure mode without weakening content-addressed caching.

  ### Better benchmark structure

  The existing suite is a strong foundation, but it currently conflates protocol compliance with accuracy. Split it into four reports:

  1. Protocol reliability
      - Missing, duplicate, and unknown IDs.
      - Batch sizes 10, 20, and 30.
      - Multiple orderings/runs.
      - Latency and cost.
      - Strict pass/fail remains visible.

  2. Classification/selection accuracy

     Apply the production reconciliation/tolerance and still compute:
      - selected-kitchen precision ≥95%;
      - Property kitchen recall ≥90%;
      - zero selections on no-kitchen Properties;
      - zero selected diagrams;
      - duplicate-cluster violations;
      - assessable precision;
      - confusion by scene, framing, and confidence.

  3. Slice analysis

     Explicitly report open-plan kitchens, partial kitchens, dark/low-resolution photos, renderings, amenity kitchens, diagrams, repeated gallery photos, and images containing both living and kitchen areas.

  4. Kitchen-quality rating bench

     Separate from routing. Yusuf rates holdout targets before seeing model output. Report exact agreement, within-one agreement, unknown rate, confusion by level, cost, latency, and confident ratings on irrelevant/non-kitchen images.

  ### What is already labeled

  The local classifier kit has:

  - 294 images
  - 10 Properties
  - 74 kitchen-visible images
  - 68 kitchen-assessable images
  - 17 Floor Plan diagrams
  - 65 irrelevant images
  - duplicate groups recorded for 158 images

  So the kitchen classifier does not need more labeling before the next bench. Fix the identity contract and run it.

  The blank fields are:

  - flooring_visible: 294 missing
  - bathroom_visible: 294 missing

  Those can remain deferred because flooring and bathroom VISION are disabled and design requires their own Catalog decision, references, quality bench, quota activation, and Decision Log entry.

  ### Other explicitly deferred or waived evidence

  - External kitchen-quality bench: still owed; current kitchen scoring was released through an Owner override, not accuracy evidence.
  - P3-SC4 canonical-ten scoped labels: current audit has 10 gradeable legacy labels and 11 unfinished skeletons, but all exact/all/select/unspecified/negative/missing/shared-plan and diagram coverage is missing.
  - P3-SC6/SC7 labels: all required human cases are missing for walk-in closets, pantry, disposal, fireplace, ceiling fans, stainless appliances, and flooring materials.
  - P3-6 reconciliation-specific model comparison: waived as a prerequisite but still owed.
  - Flooring/bathroom classifier and quality benches: deliberately deferred because those features are disabled.
  - P3-SC5 visual evidence: light mode/mobile modal inspection and real-page full_size_url behavior remain unproven, though these are visual validation tasks rather than model benches.

  ### Fastest labeling plan

  1. Back up the gitignored eval kit first.
  2. Do not relabel the 294 kitchen images.
  3. Fix the classifier ID contract and run vision-classifier-bench.
  4. For scoped text labels, use the 11 unfinished skeletons as a candidate pool but choose a canonical set of exactly ten cases. Run bench-audit-scoped --label … after every labeling session.
  5. Build a deterministic helper that surfaces likely evidence snippets and Floor Plan names for each missing coverage cell. It may accelerate navigation, but the human must confirm the label; never copy model output into ground truth.
  6. Target the coverage matrix, not every possible field on every page. A set-cover-style choice of pages will be much faster than fully annotating all 21.
  7. For kitchen quality, create a small blind holdout sheet from selected targets outside the 25 anchors, rate them 1–5/unknown, then run the quality model. This is probably a few hours, not another 294-image pass.
  8. Leave flooring and bathroom columns blank until those features are intentionally pulled forward.

  The repository’s existing estimate of 6–10 human hours for the scoped canonical ten plus 2–4 hours to run and interpret the current-pin baseline remains plausible. The classifier labeling itself is already complete; its immediate blocker is the response
  contract, not lack of labels.