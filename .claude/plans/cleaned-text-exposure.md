# Cleaned Source text is readable by every Hunt member — procedure

Date: 2026-08-06
Severity: **High.** Live in the shipping product, independent of Demo Mode.
Status: **IMPLEMENTED 2026-08-07** — migration
`20260901000010_jobs_payload_projection.sql`, DESIGN §20 v3.58, IMPLEMENTATION
2.0.131. Items 1, 2, 2a, 3 and 4 all landed, each demonstrated red before green.
Three corrections to the procedure are recorded inline below, marked
**[executor]**.

Was: **revision 5 — APPROVED FOR EXECUTION** (Owner ruling 2026-08-07)

Revision 5 closes the single remaining blocker by folding in the
`answer_job_checkpoint` fix that `.claude/plans/checkpoint-payload-injection.md`
had recorded as deferred. The Owner's earlier "fix separately" ruling was made
when the two findings looked independent; they are not. Security review verified
the other three blockers closed, including an independent sweep confirming no
third RPC route and that the consumer enumeration is exactly right.

Revision 3's approach stands; revision 4 closes three gaps security review found
in it. The shape of the feedback changed between rounds — revisions 1 and 2 were
told the *approach* was wrong, revision 3 was told the approach is right and the
call sites were missed. Notably, **the revoke alone does not close the read
path**: an RPC returning `setof jobs` bypasses column ACLs entirely.

Revisions 1 and 2 both proposed *removing* the duplicated text (strip on write,
rehydrate on resume). Security review returned REVISE twice, and every blocker
across both rounds traced to one cause: stripping means touching the worker's
resume path, which is more intricate than the fix kept assuming — resume starts
past FETCH, the load function targeted had no production call site, the canonical
copy does not exist for a Job parked at its first checkpoint, the custom-scope
manifest has no FETCH to rewind to, and RECONCILE splices extra FETCH stages into
the live manifest. The failure mode was silent wrong results, worse than the
exposure itself.

**Owner ruled 2026-08-06: pivot to the read side.** Make the text unreadable
rather than absent. The second review's Blockers 1–3 evaporate because the worker
is not touched at all.

## The finding

DESIGN §16 control 2 says cleaned Source text is service-role-only "for **every**
member, not only for demo." That is false. Reproduced against the local database
with an ordinary member's JWT:

```
cleaned_text chars readable as an ordinary member: 2296
direct property_sources.cleaned_text:              false
```

The front door is locked and a side door is open. `jobs.payload.run_state` is a
dump of the whole `RunState` (`postgres_persistence.py:85`), and
`RunState.sources[].cleaned_text` (`state.py:239`) is the cleaned body of every
fetched page. `jobs` is member-selectable (`20260829000000:154`) and no column
revoke exists on `payload`.

**This is DM-1 repeating.** DM-1 found §16 claiming a control that did not exist,
revoked `property_sources.cleaned_text`, and updated §16 to say the claim was now
true. It was not: the data has a second home nobody enumerated. The lesson worth
carrying is not "revoke another column" but "enumerate every home before
claiming a class of data is protected."

## Enumeration — every store of page-derived text

Done first, because the failure above was a failure to do it.

| Store | Contains | Readable by `authenticated` | Disposition |
|---|---|---|---|
| `property_sources.cleaned_text` | whole page body | **no** — the only revoked column in the schema | correct today |
| `jobs.payload.run_state.sources[].cleaned_text` | whole page body | **yes** | **the fix** |
| `jobs.payload.auto_resolved_checkpoint.snapshot` | a whole `RunState`, so also page bodies (`queue.py:2641-2648`) | **yes** | **the fix** — same column |
| `property_sources.cleaned_text_path`, `screenshot_path` | reserved; **0 rows populated** | yes (paths only) | no action; note that a future Storage-backed implementation inherits this problem |
| `extractions` / `floor_plans.raw` / checkpoint context — `evidence_quote` | **bounded excerpts**, not page bodies | yes | **by design** — the drawer renders evidence, §16 permits "the evidence already readable to Hunt members". Explicitly not in scope; recorded so it is not re-discovered as a defect |
| `job_events.detail.result` (`tool_called`) | **a 2 KB raw page prefix** — `llm/tools.py:383` returns `ladder.cleaned.text[:FETCH_PAGE_MAX_CHARS]`, `_summarize` (`:236-241`) stores `full[:2048]` | **yes** | **the fix, item 5.** Revision 1 mis-classified this as a bounded evidence quote. It is page body |
| `job_events.detail` — `error`, checkpoint `question` | bounded strings; a `question` may embed one evidence quote (`verify.py:402-411`) | yes | out of scope, recorded |
| `FilePersistence` (`persistence.py:30-35`) | full text to local disk | n/a — CLI/eval, service-role context | no change; recorded so the next contributor sees it |

Whole-page text therefore has **three** exposed homes: two in `jobs.payload` and
one in `job_events.detail`. Revision 1 claimed two and was wrong — which is the
same enumeration failure this document exists to correct, made a second time.

## The fix: make it unreadable, at the database

### Item 1 — a maintained projection, and a revoke

Add a **stored generated column** `jobs.payload_public`, computed by an
`IMMUTABLE` function returning `payload` with source bodies removed from both
`run_state.sources[]` and `auto_resolved_checkpoint.snapshot.sources[]`. Then
`revoke select (payload) on jobs from authenticated`, granting `payload_public`.

Why a generated column rather than a definer view or a worker-maintained copy:

- **The database maintains it**, so it is correct for *every* writer — including
  `answer_job_checkpoint`, which accepts a caller-supplied payload (see the
  companion finding, `.claude/plans/checkpoint-payload-injection.md`). A
  sanitization the worker performs is bypassable by a writer that is not the
  worker; one the database performs is not.
- **No definer view**, so no second copy of the RLS predicate to drift out of
  step with `jobs_member_select`.
- **Backfill is automatic** — adding a stored generated column computes it for
  every existing row in the same statement.
- **The worker is untouched**, which is the whole point of the pivot.

Prototyped against the live schema before writing this: the generated column is
accepted, the 3 rows carrying bodies produce 0 in the projection, and `sources`
array length and element order are preserved.

**A column revoke is not sufficient on its own.** `correct_auto_resolved_checkpoint`
is `returns setof jobs` and `grant execute … to authenticated`
(`20260818000000_p3_11_checkpoint_corrections.sql:10, :113, :119-120`), and it
inserts the auto-resolved snapshot — a full `RunState` with bodies — into the new
Job's payload (`:79-86`). Column ACLs apply to *table references*, not to
composite rows returned by a function, and PostgREST serialises every column of
an RPC result. So a member can read the bodies straight out of that response
after the revoke. Required alongside item 1:

- **Both `security definer` RPCs that return `setof jobs` must return a body-free
  projection** — `payload_public` in place of `payload`, or a narrower return
  type. `answer_job_checkpoint` (`20260715000000_submit_listing.sql:56, :76-81`)
  returns the caller's own replacement payload so it is not a disclosure channel
  *today*, but it becomes one the moment anyone makes it merge rather than
  replace — which is exactly the fix direction in the companion injection
  write-up. Fix both now.
- **A catalogue self-check** asserting
  `has_column_privilege('authenticated','public.jobs','payload','SELECT')` is
  false. Supabase's bootstrap issues blanket `grant select on all tables`, so a
  future migration could silently undo the revoke — the DM-1 pattern a third time.
- **Realtime**: `jobs` is in the publication
  (`20260717000000_realtime_publication.sql:6`) and the frontend subscribes with
  the member's own token (`lib/realtime.ts:123`). Walrus filters columns by
  `has_column_privilege`, so this should close with the revoke — but it is the
  one path where the control depends on an upstream component's behaviour rather
  than on this repo, so it needs an explicit acceptance check rather than an
  assumption.

**The transform must be total and fail-closed for content.** Revision 3
specified two literal paths, which is unsound precisely because of the rationale
above: `answer_job_checkpoint` stores `p_payload` verbatim
(`20260715000000_submit_listing.sql:76`), so shapes are not worker-only. Two
failure modes to choose between deliberately, and the choice must be stated:

- If the expression **raises** on an unexpected shape (`sources` an object →
  `jsonb_array_elements` errors; `run_state` a scalar → `->` on a scalar), the
  generated column makes the row **unwritable**. That is not a member self-DoS:
  the same expression runs on the worker's own writes, and
  `ALTER TABLE … ADD COLUMN … GENERATED ALWAYS AS (…) STORED` evaluates it
  against **every existing row**, so one odd legacy row aborts the migration. An
  availability incident in the pipeline.
- If it **passes unrecognised shapes through**, a body placed anywhere the two
  paths do not cover survives into the projection.

So: the function must never raise on any `jsonb` input (including `null`,
scalars and arrays), and must remove **every `cleaned_text` key at any depth**
rather than at two literal paths, emitting a redaction marker where a node's type
is not what it expects. `RunState` (`state.py:229-247, 525-606`) confirms
`sources[].cleaned_text` is the only whole-body field in the worker's own shapes;
recursion is for the writers that are not the worker. State the rationale in the
migration, or a future contributor will "simplify" it back to two paths.

Two further things the implementation must not get wrong:

- **Do not use `jsonb_strip_nulls`.** It would remove legitimate nulls elsewhere
  in `run_state` and silently change what the API reads. Remove exactly the
  `cleaned_text` key, nothing else.
- **Preserve array length, element order and every sibling key.** The API reads
  `run_state.url`, `source_claims`, `pending_dispute`, `cursor`, `checkpoint` and
  `auto_resolved_checkpoint` (`jobs/service.py:55-82, 119-147`) — none of which
  is a source body, so the projection is lossless for every consumer.

### Item 2 — move every authenticated reader of `jobs`

Revision 3 named two parsers and missed the actual call sites. The PostgREST
calls are `select("*")` under `UserClient`, and **`SELECT *` on a table with a
revoked column is a hard `permission denied`**, not a silently missing key — so
an incomplete enumeration breaks working endpoints, including writes.

Every access under a user JWT must be given an explicit column list:

- `jobs/service.py:185`, `:193` — `select("*")` on `jobs`.
- `listings/service.py:218-219` — `select("*")` on `jobs`, feeding
  `_refresh_matches` (`:177-179`), which reads `payload.scope` and
  `payload.fields`. **A third payload consumer** that revision 3's "lossless"
  claim omitted; the projection must preserve both keys.
- Write paths returning a representation, which need SELECT on the returned
  columns: `jobs/service.py:218, :236` (cancel/retry), `jobs/enqueue.py:11, :24`,
  `listings/service.py:239-253`, `rubric/service.py:259`.
- `admin/hunt_operations.py:810-819` calls `job_service.list_jobs` with a
  `ServiceClient` and is therefore safe — but only because of that. Revision 3's
  blanket "admin paths use the raw pool" is true only at `:823`; correct it.

**Reconcile the two key names.** `row_to_response` and `answer_checkpoint` also
consume rows returned by the RPCs (`jobs/service.py:280, :312`), which carry the
key `payload`. A naive rename drops `checkpoint`/`auto_resolved_checkpoint` from
those responses *silently* — the Tasks UI loses the prompt after answering, with
no error anywhere. Accept either key, or normalise at the RPC boundary.

Confirm PostgREST's actual behaviour for `return=representation` on `jobs` after
the revoke rather than assuming it.

**[executor] The enumeration is right for `api/src` and misses two sites in
`api/tests`**, both of which broke exactly as predicted:
`test_admin_ghost_view.py`'s `select("*")` loop over every ghost-readable table,
and `test_rls_matrix.py`'s raw `update(...)` whose default representation is a
`select *`. Both were given column lists with their assertions unchanged — the
RLS one now returns `id` rather than nothing, so `data == []` still means the
policy refused the row rather than the privilege check firing first. Worth
recording because the second one is a trap: `returning="minimal"` there would
have made the test pass whether RLS refused or not.

The general consequence, which no consumer in `api/src` hits but a future one
might: **no `authenticated` JWT can `select *` on `jobs` any more, including a
Site Admin's own.** The admin panel reads Jobs through the service-role client,
so the product is unaffected; `frontend/src` never queries `jobs` directly.

### Item 2a — the checkpoint answer must never write back what it read

**This is the blocker the revoke creates, and it is the failure mode the whole
read-side pivot exists to avoid.** `get_job_row` (`jobs/service.py:184-187`) is
the `select("*")` item 2 gives a column list; with `payload` revoked that list can
only contain `payload_public`. But that same read feeds a **read-modify-write**:
`jobs/service.py:261` parses it, `:292-298` mutates it, `:300-311` sends it as
`p_payload`, and `20260715000000_submit_listing.sql:76` **replaces** the column.
Every checkpoint answer would therefore overwrite the stored payload with the
body-free projection, silently emptying every source body.

Silently is the operative word. On resume, `extract.py:336`
(`if source.url in completed or not source.cleaned_text`) *skips* an emptied
source rather than erroring; `verify.py:418` audits evidence against `""`; and a
later P3-11 correction Job is built from the emptied snapshot
(`20260818000000:69-77`).

**The rule, stated generally, because the column list is what creates the
hazard:** no user-JWT or projection-sourced read may ever be written back to
`payload`.

The fix — which also closes the companion injection finding, since the caller can
no longer supply `run_state` at all:

**[executor] The Site Admin ghost path does *not* share `get_job_row`.**
`hunt_operations.py:867`'s handler reads through `_require_ghost_job`, which runs
`select * from jobs` on the raw asyncpg pool as the database superuser, and does
its own read-modify-write with `update jobs set payload=$2::jsonb`. It never
touches the column list, so the revoke cannot reach it and it was never at risk
of the data loss. (`get_job_row` *is* used at `:983`, under a `ServiceClient`,
which the grants also do not touch.) The acceptance row is still satisfied and
was still demonstrated red — by temporarily making `_require_ghost_job` read the
projection, i.e. the mistake the procedure predicted — but the premise was wrong,
and a fix written to the premise would have edited the wrong function.

- **`answer_job_checkpoint` merges server-side** against the row's own stored
  `payload`. It reads the prompt from the stored `run_state.checkpoint`, validates
  the answer's `choice` against `prompt.options` **inside the function** (the API's
  check at `jobs/service.py:288-290` is not a control, because the RPC is directly
  callable), then `jsonb_set`s `checkpoint_answer` (with `context_ref` from the
  stored prompt), `run_state.status = 'running'` and `run_state.checkpoint = null`.
- **The API passes only `p_answer`/`p_detail`** — never a payload it read. The
  `p_payload` parameter goes away.
- The Site Admin ghost path shares `get_job_row`
  (`admin/hunt_operations.py:867`) and must keep working; it uses a
  `ServiceClient`, so the column list must not assume a user JWT.
- Changing either RPC's return type requires `drop function` then `create`, not
  `create or replace`.

Mark `.claude/plans/checkpoint-payload-injection.md` as closed by this work, and
carry its verification items — a foreign `property_id` and a `sources[0].url`
steering attempt must both fail — into this procedure's acceptance.

**[executor] "Removes the primitive" is true of the RPC and false of the
member.** `authenticated` holds table-level UPDATE on `jobs` (`relacl`
`arwdDxtm`) and `jobs_member_update_own` permits an update of any Job whose
Listing the caller submitted, with no column restriction and no `WITH CHECK` on
`payload`. A member can therefore `PATCH /jobs?id=eq.<own job>` with
`{"payload": …, "state": "queued"}` and obtain every impact the injection
write-up lists, without calling the RPC at all; `jobs_curator_checkpoint_update`
is a third variant. Narrowing the RPC was implemented as specified and is
verified, but the companion document has been marked closed **for the RPC route
only**, with this recorded as open. Closing it needs the same drop-and-re-grant
surgery the SELECT revoke needed, applied to UPDATE — a separate change with its
own breakage surface, deliberately not attempted here.

### Item 3 — stop storing a raw page prefix in `job_events`

Independent of `payload`, and a live exposure of its own. `llm/tools.py:383`
returns `ladder.cleaned.text[:FETCH_PAGE_MAX_CHARS]`; `_summarize` (`:236-241`)
stores `full[:2048]` into `job_events.detail.result`, member- and demo-readable
(`20260829000000:157-160`). Store a non-body summary for `fetch_page` results —
length, hash, outcome — rather than the prefix.

Structural residual to record: `_summarize` truncates *any* tool result, so a
per-tool fix leaves the same hazard for the next body-returning tool. A general
fix belongs with the tool registry, not here.

### Item 4 — correct §16 in both places

The claim appears twice: control 2 (`DESIGN.md:1029`) and the PII posture
(`DESIGN.md:1038`, "Cleaned Source text … remains service-role-only"). Fixing one
leaves the DM-1 pattern intact. Record the enumeration table, and a §20 entry
stating the control is a **column revoke plus a maintained projection**, and that
the text is present-but-unreadable rather than absent.

### Deliberately not doing

**Removing the duplication.** The text stays in `payload`, unreadable. That is
weaker than absence — a future view, admin export or support tool could reach it
— and it is the accepted trade for not touching resumability. Record it as a
known residual rather than presenting the fix as complete removal. Revisit if the
resume path is ever reworked for other reasons.

## Acceptance — red before green, per item

| Item | Must be demonstrated to fail first |
|---|---|
| Member cannot read bodies | the reproduction at the top, as a test: an ordinary member's simulated JWT reads **0** characters of `cleaned_text` from `jobs`; fails against current code |
| Demo cannot read bodies | the same with a demo token against a Demo Hunt Job |
| Projection is lossless | every field `jobs/service.py` reads is identical between `payload` and `payload_public`; array length and order preserved |
| Auto-resolved snapshot covered | a Job whose `auto_resolved_checkpoint.snapshot` carries bodies |
| Nulls not stripped | a payload with a legitimate `null` inside `run_state` survives unchanged |
| Tasks UI unaffected | `stage_index`, live checkpoint, checkpoint context and the auto-resolved record all still resolve through the API |
| `job_events` page prefix | a `fetch_page` tool call: assert no page body in `detail`; fails against current code |
| Total member-readable page text | one test bounding the characters an ordinary member JWT can read across `jobs.payload*` **and** `job_events.detail` |
| RPC disclosure channel | an ordinary member calling `/rpc/correct_auto_resolved_checkpoint` on a Job with an auto-resolved snapshot reads **>0** chars of `cleaned_text` today, 0 after |
| Revoke cannot be silently undone | the catalogue self-check fails when `select (payload)` is re-granted to `authenticated` |
| Realtime carries no bodies | a member subscription to `jobs` receives an UPDATE record with no `payload`/`cleaned_text` |
| Transform is total | a table-driven test over `null`, `'"str"'::jsonb`, `[]`, `{"run_state":"x"}`, `{"run_state":{"sources":{"a":{"cleaned_text":"BODY"}}}}`, snapshot-in-snapshot, and legitimate `null` siblings: each write succeeds, `BODY` appears nowhere in `payload_public`, and every key the API reads is unchanged |
| Refresh coalescing still works | the existing refresh-coalesce test finds a matching Job, proving `payload.fields` survived the projection |
| Every user-JWT `jobs` path | list, detail, cancel, retry, checkpoint answer, refresh-coalesce and rescore-enqueue all green under a member JWT with the revoke applied |
| Checkpoint answer preserves bodies | red-first with the revoke and column list applied but the RPC unchanged: a member answers a `waiting_user` checkpoint via `POST /v1/jobs/{id}/checkpoint`, then a service-role read asserts `run_state.sources[0].cleaned_text` is still non-empty. Fails before the RPC change, passes after |
| Resume after an answer still has text | a worker resume following a checkpoint answer: VERIFY and CUSTOM_MATCH receive non-empty page text |
| Admin ghost path unaffected | the same answer flow through `hunt_operations.py:867` under a `ServiceClient` |
| Injection primitive removed | a member calling `/rpc/answer_job_checkpoint` directly cannot supply `run_state`; steering attempts via a foreign `property_id` **and** via `sources[0].url` both fail |
| Answer validation is server-side | a `choice` outside `prompt.options` is rejected by the function, not only by the API |
| Nothing else regressed | `pytest api/tests` (397), `pytest worker/tests` (681 + 2 known environmental), frontend 751, ruff |

## Risk

Lower than revisions 1 and 2 by construction: no worker change, no resume path,
no scrub-ordering hazard, and no silent-wrong-results failure mode. Two residual
risks to state in the migration itself: a generated column's expression is **not**
recomputed for existing rows if the function is later altered, so changing the
transform requires a deliberate column rebuild; and a missed authenticated reader
of `payload` surfaces as a broken Tasks UI, caught immediately in development
rather than silently in a paid pipeline.

Operationally: adding a STORED generated column takes `ACCESS EXCLUSIVE` and
rewrites `jobs`, detoasting and re-TOASTing every payload — seconds at this
scale, but the worker blocks on it. State that in the migration, along with the
fact that the transform **cannot be changed by `create or replace function`
alone**: existing rows are not recomputed, so altering it requires a deliberate
column rebuild.

The standing residual — text present but unreadable — belongs in §17 as a risk,
not only in §20 as a decision.
