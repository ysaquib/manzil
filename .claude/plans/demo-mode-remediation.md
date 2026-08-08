# Demo Mode remediation — procedure

Date: 2026-08-06
Branch: `worktree-demo-mode`
Inputs: two fresh-context adversarial verifications of the Phase A–H work.
Both returned **REFUTED**. Findings are `F1`–`F11` (frontend/replay) and
`R1`–`R9` (database/API).
Status: **revision 2 — answering a REVISE verdict from security review**

Revision 2 changes, each closing a named blocker:
- **S1** the "prove it was light first" rule now governs **every negative
  assertion**, not only darkness checks, and `check_rpcs` is tightened — it
  currently passes with `assert_not_demo` deleted.
- **S2** F1's prompt source is replaced: both sources named in revision 1 are
  provably empty for the only Job the exporter accepts.
- **S2** the privacy allow-list becomes recursive over the whole bundle; a
  docstring is no longer offered as a control.
- **S6** R6 no longer claims to remove the serialization surface, and R8's
  expression is given literally to keep a keyed caller off the reserved global
  bucket.
- **Contract** fail-first now applies to all six slices, not three.

## What the verifications actually established

The **SQL is sound.** The database verifier could not construct any read or
write a demo token should not have, and independently reproduced every Phase A–D
control: `demo_identity()` correct across six configurations, all eight
restrictive tables returning zero rows when `dark`, `42501` on every write path,
exact ceilings under 60-way concurrency, storage scoping over real HTTP, no
regression for ordinary users. Mutation testing confirmed the new SQL tests are
not vacuous.

What is broken is **the evidence, and the replay feature.** Two failures of the
same kind: a test that cannot fail, and a feature that has never run.

- **`R1` is the most serious finding on this branch.** DM-8's headline C1 checks
  pass against a database in which C1 has been **fully reintroduced**. The
  verifier restored the exact fail-open predicate, ran the harness, and got
  `All 32 checks passed`. A security test that green-lights the vulnerability it
  exists to detect is worse than no test, because it is trusted.
- **`F1`–`F4` mean the replay has never worked.** It was built and tested against
  a hand-written fixture the exporter cannot produce. `manzil export-demo-capture`
  raises on every invocation (`F3`), and had it run, the demo would dead-end at
  the checkpoint (`F1`), never advance the pipeline track (`F2`), and crash the
  Overview on completion (`F4`).

Both root causes are mine and they are the same mistake: **I verified against
what I had written rather than against what the system produces.**

## Ordering

Slice 1 first and alone. Until the harness can fail, no other slice's evidence
means anything — including the evidence that the remaining slices worked.

---

## Slice 1 — Make the harness capable of failing (`R1`, `R3`, `R4`)

**Owns:** `scripts/dm8_adversarial.py`, `docs/demo-mode-dm8-evidence.md`

**`R1` — the darkness checks are vacuous.** `main()` mints one token at
generation N (`:797`). `check_realtime` toggles the switch twice (`:512`, `:525`),
and `set_demo_enabled` bumps `demo_generation` unconditionally
(`20260901000006:377`), so by `check_kill_switch_and_identity` (`:812`) the token
is already `dark` on the *generation* branch — before `demo_identity()` ever
looks at `demo_accounts`. Both marker checks are true for the wrong reason.

**The rule is general, and revision 1 scoped it too narrowly.** Security review
found the same vacuity in the *refusal* checks, and one of them passes today with
the control deleted:

> `check_rpcs` (`:376`) accepts `status_code in (401, 403, 400, 404)`, and two of
> the four calls pass a random `uuid4()` job id (`:359`, `:367`) which yields
> 400/404 for **any** caller. Delete `private.assert_not_demo`'s body and the
> check still passes. The file already rejects exactly this looseness twenty
> lines earlier (`:317-319`).

So the fix is stated once, over every negative assertion in the harness:

1. **No negative assertion without a positive control.** Each check block
   re-mints at the *current* generation and first asserts the token is `scoped`
   — a non-zero scoped read — before asserting the refusal or the darkness. A
   failed precondition reports **FAIL**, never PASS. This removes the dependence
   on ordering rather than restoring an assumption about it, which is why
   re-minting alone is insufficient: `check_gotrue` (`:448`) and `check_writes`
   (`:319`) would otherwise keep passing for a token that is dark, expired, or
   structurally invalid — the exact state `R1` shows the harness drifts into.
1a. **The induced darkness must be attributable to the branch under test.**
   Revision 2's rule was still not enough, and this is the third instance of the
   same defect class. `demo_identity()` has *two* independent darkness branches:
   `not coalesce(v_enabled,false)` (`20260901000006:130`) and stale generation
   (`:137-140`). Because `set_demo_enabled` rotates the generation on every
   toggle, any check that darkens by **toggling the switch** darkens for the
   generation reason too — so deleting `or not coalesce(v_enabled, false)`
   entirely leaves `check_realtime`'s disabled half (`:513-524`) and
   `check_kill_switch_and_identity` step 3 still passing. The precondition rule
   cannot catch it: the precondition genuinely held. Therefore any check that
   darkens via a configuration toggle must **re-mint at the post-toggle
   generation** before asserting darkness, so `enabled=false` is the only
   remaining inconsistency. This branch is DESIGN §16 control 5 and the whole
   premise of "disabling is a revocation" (`DESIGN.md:1032`).
2. **`check_rpcs` must require `403` *and* `42501` in the body**, as
   `check_writes` does. **The stated root cause in revision 2 was wrong**:
   `answer_job_checkpoint` is called with `p_job_id, p_answer, p_event_detail`
   (`:357-361`) but its signature is `(p_job_id uuid, p_payload jsonb, p_detail
   jsonb)` (`20260715000000_submit_listing.sql:53-54`), so **no overload matches
   and PostgREST answers 404 for every caller**, guard or not — independent of
   the random job id. Under the tightened rule that call can never go green.
   So: **every RPC in `check_rpcs` must be invoked with its actual signature,
   verified against `supabase/migrations/`, with real ids.** Dropping an RPC
   from the set, or loosening the assertion, is **not** an acceptable
   resolution — all four RPCs named in §16 control 4 (`DESIGN.md:1031`) must
   stay covered.
3. Do not toggle the switch inside `check_realtime` without re-establishing token
   validity afterwards.
4. **A self-test the harness runs on itself**, before the security checks: hand
   it a deliberately-wrong token (valid signature, stale generation) and assert
   the darkness assertion reports it dark — proving the instrument can
   distinguish states at all.

**`R3`** — the evidence artifact reports "32 of 32 passed" for a run where five
FastAPI checks were skipped; skips are dropped from the denominator. Report
`passed / attempted (+N skipped)` and make any skip visible in the headline.

**`R4`** — the disabled half of the Realtime check substitutes a PostgREST read.
Re-open a real websocket subscription after the switch flips and after a
generation rotation, per R2 H6.

**Also in scope (found by security review, same file, same defect class):** the
harness's own boundedness check (`:633-657`) uses 25 **distinct** keys, so 26 new
rows against a `<= 30` threshold passes for a one-row-per-key design — the
identical tautology `R5` fixes in the API test. Reformulate with a single key, or
with more keys than the 4096-bucket domain.

**Acceptance — three demonstrations, each red before green:**
- with `private.demo_identity()` mutated to drop the `not v_marked or v_count <> 1`
  darkness test (C1 reintroduced), the harness **FAILS**;
- with `private.assert_not_demo` mutated to a no-op, `check_rpcs` **FAILS**;
- handed a deliberately expired token, every refusal check **FAILS its
  precondition** rather than reporting PASS.

Then revert every mutation and regenerate the evidence file with the API plane up.

---

## Slice 2 — Make the Replay Capture real (`F1`–`F4`, privacy)

> **DEFERRED from this execution round (Owner decision, 2026-08-06).** Security
> review found that revision 2's F1 fix would publish free text to a
> **world-readable build artifact**: `capture.json` is imported at build time
> (`useDemoCapture.ts:21`), not served to demo sessions, and checkpoint prompts
> can embed a *different* Property's name, address and UUID
> (`dedupe.py:190-203`) or model-authored prose derived from Source text that
> §16 keeps service-role-only (`verify.py:402-407`). No prompt text is exported
> today, so this would open a hole rather than close one. This slice goes to its
> own security review before any of it is executed. Slices 1, 3, 4, 5 and 6 are
> unaffected and proceed now.

**Owns:** `worker/src/manzil_worker/ops/export_demo_capture.py`,
`frontend/src/features/demo/replay/capture.ts`, tests for both.

**`F3` — the exporter cannot run.** It selects `p.locality`, which does not
exist; the column is `properties.city` (plus `state`, `county`). Fix and audit
*every* column the module names against `supabase/migrations/`.

**`F1` — the checkpoint prompt is unreachable, and revision 1's fix was wrong.**
`postgres_persistence.py:144-149` writes `{"question": state.checkpoint.question}`
— and `CheckpointPrompt.question` is a **plain string**
(`shared/src/manzil_shared/models.py:572-579`). The event therefore carries
neither `kind`, `options` nor `default`, so adding `question` to `_DETAIL_KEYS`
would still not let the UI render an answer control.

Revision 1 said to source the prompt from `jobs.payload`. **Security review
showed both of those sources are empty for the only Job the exporter accepts:**

- `api/src/manzil_api/jobs/service.py:297` sets `run_state["checkpoint"] = None`
  before the RPC, and `20260715000000_submit_listing.sql:76` replaces
  `jobs.payload` wholesale with that nulled version;
- `20260818000000_p3_11_checkpoint_corrections.sql:68-69` nulls it again and
  strips `auto_resolved_checkpoint` on the correction path;
- `auto_resolved_checkpoint.prompt` survives **only** for checkpoints never asked
  of a human — the opposite of a DM-9 capture, which parks and is answered.

So revision 1's "fail loudly if neither source yields a prompt" would have failed
on *every* valid candidate: a dead-end traded for a hard error.

**Fix: record the whole prompt where it is asked.** Widen
`postgres_persistence.py:144-149` to emit the full pinned §10.10 shape —
`kind`, `question`, `options`, `default`, `context_ref` — into the
`checkpoint_asked` event, and have the exporter read `capture.checkpoint` from
that event, falling back to `auto_resolved_checkpoint.prompt` for runs that were
never asked of a human. This **does not reshape `CheckpointPrompt`**, which is a
pinned contract (AGENTS.md, §10.10) — it serializes the existing shape into the
event that already exists to announce it. It is still a recording per DESIGN §3:
the prompt really was asked, in those words, with those options.

Consequence to state plainly: existing Jobs carry no such detail, so the shipping
capture must come from a **future** run. That is already true for other reasons —
the real capture needs an Owner-run paid ingest, which is a standing non-goal
here — so this costs nothing that was not already owed.

`_DETAIL_KEYS` gains the prompt fields and **loses `answer`** (see Privacy).

**`F2` — ingest Jobs emit no `started` events.** `_emit` writes only
`completed`/`failed`/`checkpoint_asked`; only `rescore`/`refresh` write `started`
(`queue.py:1680,1784`). `jobAt()` counts `started` for `stage_index`, so it is
permanently 0 and `PipelineTrack` never marks a phase done. Fix in the
**replayer**, not the exporter: derive progression from the events that exist —
`stage_index` as the count of distinct stages seen so far, state transitions
driven by `completed`/`checkpoint_asked`/`failed`. Do **not** synthesize
`started` events into the bundle: a Replay Capture is a recording (DESIGN §3),
and manufacturing events it never contained is the one thing that contract
forbids.

**`F4` — the finished Listing crashes the Overview.** `unitGroups.ts:58`
iterates `listing.property.floor_plans` unguarded, and the exported payload has
no `floor_plans` and no `sources`. The bundle's listing must match the shape
`useListings` produces (`LISTING_SELECT`, `features/listings/types.ts:284-301`):
`hunt_id`, `property_id`, `added_by`, `status`, `pins`, `unavailable_at`,
`all_in_components`, `move_in_components`, `property` **with** `floor_plans` and
`sources`, and `scores`.

**Privacy — and revision 1 was too weak here.** `_DETAIL_KEYS` keeps `answer`,
and `checkpoint_answered` details carry `{"answer": body.answer}` which may hold
a Curator's free-typed text (§10.10 `other:` form), contradicting the module's
own "deliberately not exported: anything about a person". Drop `answer`.

But security review is right that revision 1's allow-list reached only
`events[].detail`, leaving the largest free-form fields in a bundle **served to
anonymous visitors** governed by nothing but a docstring. A docstring is not a
§16 control. Required instead:

- **The allow-list assertion is recursive over the entire bundle**, not just
  event detail. Any key not named is a test failure.
- `job.plan` is narrowed to `{stages: [...]}` — verified to be the only thing the
  UI reads (`pipelinePhases.ts:104,189` access `plan.stages` and nothing else).
- `job.warnings` is narrowed to `{stage, code, message}`; the free-form `detail`
  is dropped (`JobWarnings.tsx` renders no more than those three).
- `scores.breakdown` is asserted against the pinned §9.3 score-breakdown schema
  rather than passed through.
- `single_source_reason` is asserted to be one of the three enum values
  (`trust_link | discover_exhausted | discover_failed`), not free text.
- `canonical_address`, `lat`, `lng` and `city` **stay**, with the reason recorded:
  they are Property facts, and showing Properties is what the demo is for. That
  is a decision, not an oversight.

**Acceptance:** inject a synthetic marker key into `jobs.plan`, `jobs.warnings`
and `scores.breakdown` in the fixture; the exporter must strip it or refuse.
Demonstrate the marker survives into the bundle **before** the fix.

**Acceptance — this is the part that was missing and matters most.** A test that
builds a capture from a **real Job in the database** (the seed/e2e fixtures
create one) and drives the replay to completion, asserting: the checkpoint
renders with a usable prompt and answer control; `PipelineTrack` advances past
the first phase; the run reaches `done`; and the published Listing is consumable
by `buildRows`/`unitGroups` without throwing. A fixture the exporter cannot
produce must not be the only input any replay test ever sees.

---

## Slice 3 — Finish the M5 inventory (`F5`–`F8`)

**Owns:** `frontend/src/features/visits/api.ts`, `features/invites/*`,
`frontend/tests/demoMode.test.ts`

- **`F5`** `useCreateVisit` (`visits/api.ts:145-150`) — `VisitCreatePage.tsx:185`
  `await mutateAsync(...)` then reads `visit.id`. Reachable by the demo Curator;
  throws, unhandled, from a `void submit()` click handler.
- **`F6`** `useCreateInvitationLink` (`invites/api.ts:79-89`) —
  `InvitationLinksSection.tsx:221` reads `link.link`.
- **`F7`** `InviteAcceptPage.tsx:14` — `if (accept.data)` never becomes truthy,
  so the page spins forever. Give it the treatment `InvitationLinkJoinPage` got:
  say plainly that invitations cannot be accepted in the demo.
- **`F8`** the structural test is near-vacuous. Its glob is `**/*.ts`, which
  **does not match `.tsx`**, and it asserts the *file* contains the string
  `demoResult` rather than the hook. Fix all three: glob `**/*.{ts,tsx}`, scope
  the assertion to the mutation that dereferences, and extend detection beyond
  `onSuccess` to `mutateAsync`, `.then()`, and `mutation.data`.

**Acceptance:** the corrected structural test, run against the *pre-fix* tree,
flags `F5`, `F6` and `F7`. Demonstrate that before fixing them.

---

## Slice 4 — Repair the timing model (`F9`–`F11`)

**Owns:** `frontend/src/features/demo/replay/replayTiming.ts` and its tests.

- **`F9`** once the dominant gap clamps at `maxGapMs`, water-filling hands its
  surplus to the rest by weight until they clamp too. With `maxGapFraction` 0.25,
  **any capture with ≤4 scheduled gaps is a perfect metronome** — and offsets
  `[0,400,60_400,150_400,152_400]` produce a schedule byte-identical to
  all-zeros. This is precisely the failure the module's header says it prevents.
- **`F10`** `minGapMs` is not a floor: the post-jitter `correction` rescale
  (`:154-160`) multiplies already-clamped gaps below it. 1371 violations in 3000
  fuzzed captures.
- **`F11`** with `targetMs` below the floor budget the replay runs *shorter*, not
  longer as documented, because `maxGapMs = targetMs * 0.25` falls under
  `minGapMs`. `NaN` offsets propagate unguarded.

Required invariants, each with a test — property-based/fuzzed, not example-based:

1. **Order-preserving**: a larger recorded gap never yields a smaller playback
   gap. (This is the honest formulation of "relative shape survives"; it holds
   even when clamping binds.)
2. **Floor respected after every transformation**, jitter and rescale included.
3. `maxGapMs` is never allowed below `minGapMs`.
4. Total ≥ the floor budget; the documented "runs longer than asked" holds.
5. Schedule strictly monotonic; no `NaN`/`Infinity`/negative delay for any input
   including single-event, all-zero, one-enormous-gap, backwards and `NaN`
   offsets.

Existing tests that hid these (notably the floor test's 100ms slack) must be
tightened, not preserved.

---

## Slice 5 — Cover what is claimed but untested (`R2`, `R5`)

- **`R2`** no test touches `PATCH /v1/admin/demo`; `grep -rn "admin/demo" api/tests/`
  returns nothing. The existing test asserts Postgres savepoint semantics and
  passes against the *pre-fix* two-pool-call implementation. Add route-level
  tests for **both** halves of the deliberate asymmetry: enabling with a failing
  audit insert leaves `demo_enabled` false; **disabling with a failing audit
  insert still disables** and logs.
- **`R5`** the boundedness test uses 200 *distinct* keys and asserts `<= 201`,
  which a one-row-per-request design also satisfies. Use one key 200 times and
  assert `<= 2`.

---

## Slice 6 — Hardening (`R6`–`R9`)

- **`R6` — do not claim to remove the serialization surface; it cannot be
  removed here.** Revision 1 said moving the lock would fix the flood path.
  Security review showed it would not: the disabled path still calls
  `private.demo_count`, which upserts the single row `(window, -1)` on **every**
  request (`20260901000007:83-94, :171-173`), so unauthenticated traffic still
  contends on one tuple's row lock and still writes a dead tuple and a WAL record
  per request. Moving the advisory lock relocates the contention rather than
  ending it. Therefore:
  - **State the hot global counter row as the accepted, named residual.** The
    real remedy is the edge limiter already specified in
    `docs/production-deployment-render-supabase.md` §7.0.1, owed at deploy time;
    reference it rather than re-solving it in SQL.
  - Where the lock *is* held, the enabled path must **re-read `site_settings`
    after acquiring it**. Reading `demo_enabled` before the lock and not again
    under it widens the issue-vs-disable race, which today is survivable only
    because the stale generation renders the minted token `dark`
    (`20260901000006:137-140`) — a second control compensating for a first one's
    gap is not a design to leave undocumented.
- **`R7`** `can_read_property_image` reads `(storage.foldername(name))[2]` without
  pinning `[1]`, so `zzz/<uuid>/x.webp` authorizes identically. Security review
  independently confirmed this is **not exploitable today** — the only
  `authenticated` policies on `storage.objects` are SELECT
  (`20260723000000:25-26`, `20260901000008:77-82`), so there is no client write
  path to place such an object. Pin `[1] = 'properties'` as defence in depth.
- **`R8` — the remedy must be given literally, or it opens a worse hole.**
  `abs(hashtextextended(...))` raises `22003` on `bigint` min. But "use `mod`"
  as loosely phrased in revision 1 yields −4095..4095, because Postgres `%` and
  `mod()` preserve the dividend's sign — and `-1` is the **reserved global
  bucket** (`20260901000007:69-80, :180-186`). A key hashing to `-1` would take
  the sentinel branch, escape the per-key ceiling entirely, and double-count the
  global row. Use exactly:

  ```sql
  ((hashtextextended(p_client_key, 0) % c_buckets) + c_buckets) % c_buckets
  ```

  plus `check (client_bucket >= -1)` on the table and an in-function assertion
  that a keyed bucket is `>= 0`.
- **`R9`** `/demo/config`'s cache and `reset_config_cache()` are per-process; the
  docstring implies a global reset. Correct the wording — behaviour is fine, RLS
  is authoritative.

---

## Non-goals

Unchanged from the Phase A–H plan, and **not** to be attempted here: the real
Replay Capture (needs an Owner-run paid ingest), the pre-captured map stills, and
the hosted-Auth run (no hosted project exists). Slice 2 makes the exporter
*capable*; it does not produce the shipping bundle.

## Verification contract

**Fail-first applies to every slice, without exception.** Revision 1 demanded it
for Slices 1–3 only, which is how `R5` — a test the procedure itself describes as
passing against the pre-fix implementation — was scheduled to be replaced by
another test with no red run behind it. Each item below names the mutation or
pre-fix state to demonstrate against, and each slice's evidence must record a red
run before a green one:

| Item | Demonstrate it fails against |
|---|---|
| S1 `R1` | `demo_identity()` with the `not v_marked or v_count <> 1` test removed |
| S1 `R1` | `assert_not_demo` mutated to a no-op (`check_rpcs` must fail, with 404 not accepted) |
| S1 `R1` | `demo_identity()` with `or not coalesce(v_enabled, false)` removed — the switch-off checks must fail |
| S1 precondition | a deliberately expired token (every refusal check fails its precondition) |
| S1 boundedness | a counter design that appends one row per distinct key |
| S2 `F1`–`F4` | the current exporter, against a real Job — it raises today |
| S2 privacy | a marker key injected into `plan`, `warnings`, `breakdown` |
| S3 `F5`–`F7` | the corrected structural test run against the pre-fix tree |
| S4 invariants | the current `replayTiming.ts` (fuzz must find floor + shape violations) |
| S5 `R2` | the pre-fix two-pool-call `set_demo` implementation |
| S5 `R5` | a one-row-per-request counter design |
| S6 `R7` | an object keyed `zzz/<uuid>/x.webp` |
| S6 `R8` | a client key whose hash is negative, and one at `bigint` min |
| S6 `R6` | assert the enabled path reads `site_settings` *after* the lock |
| S6 `R9` | n/a — wording only; no behavioural claim to falsify |
- Regression gates: `uv run --package manzil-api pytest api/tests -q` (391 now),
  `pnpm test -- --run` (745 now), `tsc --noEmit`, `eslint`, `pnpm build`,
  `uv run ruff check .` (4 pre-existing errors in files not touched here).
- Known environmental, not regressions: two `worker/tests/test_backfill_locality.py`
  failures caused by the backfill scanning the whole dev database.
- Leave the database as found: demo disabled, `demo_hunt_id` null.
- A fresh verifier re-runs the whole claim after execution.
