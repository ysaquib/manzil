# A member can inject arbitrary RunState through `answer_job_checkpoint`

Date: 2026-08-06
Severity: **High** — integrity, not disclosure. Live in the shipping product.
Status: **CLOSED for the RPC route, 2026-08-07** (implemented as
`.claude/plans/cleaned-text-exposure.md` item 2a, migration
`20260901000010_jobs_payload_projection.sql`, DESIGN §20 v3.58). `p_payload` is
gone: `answer_job_checkpoint` merges the answer into the Job's own stored
payload, so there is no parameter left to carry a `run_state`. Verified red
first — a member calling the RPC directly with a foreign `property_id`, and
again with a hostile `sources[0].url`, both succeeded before and now fail
`42883` with the stored payload untouched
(`api/tests/test_jobs_payload_projection.py::test_answer_job_checkpoint_takes_no_caller_payload`).
Server-side `choice` validation landed with it.

**A second route to the same primitive is still open, and was not in scope.**
`authenticated` holds table-level UPDATE on `jobs` (`relacl` `arwdDxtm`), and
`jobs_member_update_own` lets a member or Curator update any Job whose Listing
they submitted, with no column restriction and no `WITH CHECK` on `payload`.
`PATCH /jobs?id=eq.<own job>` with `{"payload": …, "state": "queued"}` therefore
reproduces every impact listed below without touching this RPC.
`jobs_curator_checkpoint_update` is a third variant for any `waiting_user` Job in
the Hunt. Closing it means the same surgery the SELECT revoke needed — drop the
table-level UPDATE grant and re-grant per column — which is a separate change
with its own breakage surface and needs its own review. **Do not treat this
document as closed until that is ruled on.**

The two findings turned out to share one fix. Revoking `jobs.payload` makes the
API read a redacted projection, and because this RPC *replaces* the payload
rather than merging it, the checkpoint round-trip would silently empty every
source body. Making the RPC merge server-side closes that and removes the
injection primitive in the same change.

Found during security review of `.claude/plans/cleaned-text-exposure.md`, and
confirmed independently in a second review. Unrelated to Demo Mode, and unrelated
to the cleaned-text exposure beyond sharing a column.

## Mechanism

`public.answer_job_checkpoint` (`supabase/migrations/20260715000000_submit_listing.sql:53-85`)
is `security definer`, `grant execute to authenticated`, and executes:

```sql
update jobs set state = 'queued', payload = p_payload ...
```

`p_payload` is **caller-supplied and unvalidated**. The function checks only that
the Job is in `waiting_user` and that the caller is the Owner/Curator or the
Listing's submitter. It does not check that the payload it is storing bears any
relation to the payload the Job had.

The API constructs a correct payload before calling it
(`api/src/manzil_api/jobs/service.py:286-295`), but that is **not a control**:
the RPC is exposed through PostgREST and a member can call
`/rpc/answer_job_checkpoint` directly with a payload of their choosing.

The worker then trusts what it reads back. `queue.py:255-273` `model_validate`s
the stored payload into a `RunState`, and the run continues from it.

## Impact

An authenticated member who owns a parked Listing can steer their own Job at
another Property's rows, and can control which pipeline stages execute:

- **`property_id` — and this is worse than "redirects a write".** `queue.py:1388-1389`
  (`if state.property_id is None:`) lets the snapshot's value win over the
  Listing's. The injected value reaches `_merge_into_canonical`
  (`queue.py:1406-1412`), so the placeholder Property is **merged into the victim
  Property** rather than merely written beside it. The service-role worker
  performs the merge, so RLS does not apply to it.
  A fix must not validate `property_id` alone: the merge target is `canonical_id`
  (`queue.py:1405`), which prefers a `property_sources` lookup on
  `sources[0].url` over the injected `property_id`, so an attacker can steer
  through **either** field.
- **`plan.stages` and `cursor`.** These decide which stages run and which are
  skipped, so a caller can bypass VERIFY's evidence audit — the primary
  anti-hallucination and anti-prompt-injection control (DESIGN §16) — and have
  unverified claims scored and persisted.
- **Claims and extractions.** Injected `source_claims`/`resolved_claims` are
  reconciled and scored as though they had been extracted from a page.

Not affected: SSRF through an injected `url` or `sources[].url` is separately
mitigated by `normalize_url` and the fetcher's resolving guard (DESIGN §20
2026-07-12). Demo Mode is not affected — `private.assert_not_demo` rejects the
demo subject at function entry — so this does not gate demo enablement.

## Why it matters beyond this bug

It is the reason a sanitization performed by the *worker* cannot be a security
control on `jobs.payload`: the worker is not the only writer. That is what pushed
the cleaned-text fix onto a database-maintained generated column rather than a
worker-side strip, and it is worth remembering the next time a control is placed
in the pipeline rather than in Postgres.

## Shape of a fix (not yet designed or reviewed)

The direction, for whoever picks this up:

- **Narrow the RPC so the caller cannot supply `run_state` at all.** The function
  has everything it needs to apply an *answer* — it can merge the answer into the
  stored payload itself rather than accepting a replacement. That removes the
  primitive instead of validating it, which is the stronger shape.
- If a replacement payload must be accepted, validate server-side inside the
  function: `property_id`, `hunt_listing_id`, `job_id` and the plan manifest must
  equal what the row already holds; only the answer and cursor may move forward.
- Re-examine `queue.py:1388-1389`'s precedence rule. A snapshot's `property_id`
  overriding the Listing's is defensible for a legitimate worker-written state
  and indefensible for a caller-written one; if the RPC is narrowed, this can
  stay, but it should be a deliberate decision rather than an inherited one.
- Audit the sibling RPCs. Verified during review:
  **`correct_auto_resolved_checkpoint` is *not* injectable in the same way** — it
  builds the payload from the stored snapshot, and its only caller-supplied
  field, `p_answer`, is checked against `prompt.options`
  (`20260818000000_p3_11_checkpoint_corrections.sql:61-64`). It is, separately, a
  *disclosure* channel: `returns setof jobs` bypasses column ACLs, which is
  handled in `.claude/plans/cleaned-text-exposure.md`.
  **`set_listing_source_policy` remains unverified** — it is `security definer`
  and `authenticated`-executable, and nobody has checked it for this shape.

## Verification owed when it is scheduled

- Reproduce first: call `/rpc/answer_job_checkpoint` directly as an ordinary
  member with a payload naming a foreign `property_id`, and show the worker
  **merging into** that Property. Repeat steering via `sources[0].url` instead,
  since `canonical_id` prefers it. The fix is not credible without both red runs.
- Assert the narrowed RPC rejects a payload differing from the stored row in any
  identity field, and that a legitimate answer through the API still works.
- Assert VERIFY cannot be skipped by a caller-supplied `plan`/`cursor`.
