# CLI Plan — `manzil submit` + `ingest --hunt`

Status: **drafted 2026-07-19, not started.** Small, self-contained; no phase
gate. Written against the working tree on 2026-07-19 (Phase 3, uncommitted
batch). Not a Phase 3 task — this is CLI hygiene that fell out of a README
audit, and it can land any time.

## 0. Why

`manzil ingest <url>` and the API submit path do **not** converge, and the gap
is currently undocumented and partly misleading:

| | `manzil ingest` | API `POST /v1/hunts/{id}/listings` |
|---|---|---|
| `jobs` row | none | `submit_listing` RPC (`supabase/migrations/20260715000000_submit_listing.sql:45`) |
| Derived rows (property/sources/extractions/scores) | **none** | terminal projection, `queue.py:759-779` |
| Rubric scored against | hardcoded `phase0_rubric()` (`cli.py:73`) | the hunt's rubric at `listing["rubric_version"]` |
| Hunt association | none | `hunt_id` + `hunt_listing_id` |
| DEDUPE merge applied | no — decision rides `RunState`, projection applies it (`dedupe.py:22`) | yes |

The **decision** (2026-07-19, Yusuf): the API stays the only path that creates
Listings. The CLI is a debugging tool, not a second submit path. Rationale:

1. **One writer.** The terminal projection is the sole writer of derived rows.
   A CLI that reproduces the end state means duplicating it — including
   `_merge_into_canonical` — and two copies will drift.
2. **RLS.** The CLI connects service-role via `DATABASE_URL`, below the RLS
   boundary. That is right for `split-property` (deliberate admin repair);
   it is wrong for Listing submission, which is a member action with a role
   matrix behind it. A CLI submit path that writes below RLS quietly reopens
   the boundary Phase 2 established.
3. **The no-DB behavior is the feature.** Pointing `ingest` at a hostile domain
   without leaving a half-broken Listing in the real hunt is its actual job.

So this plan does **not** wire `ingest` to enqueue. It fixes the one real defect
(a misleading score) and adds a thin, correctly-scoped submit command.

## 1. Scope

**In scope**

- `ingest --hunt <hunt-id>`: score against a real hunt's rubric, read-only.
- `ingest` default output: stop presenting a Phase-0-fixture score as if it were
  the hunt's.
- `manzil submit <hunt-id> <url>`: enqueue-only, no pipeline in-process.
- Doc corrections: README, IMPLEMENTATION P1-7 "done when", DESIGN §20 entry.

**Out of scope — do not build**

- Any DB write from `ingest`. It stays file-persistence only.
- Reproducing the terminal projection anywhere outside `queue.py`.
- Bulk/batch submit (a file of URLs, concurrency). Add only if one-at-a-time
  submission proves annoying in practice — do not build speculatively.
- Touching `split-property`'s service-role model; it is correct as-is.

## 2. Tasks

### C-1 — `ingest --hunt <hunt-id>` (rubric fidelity)

`ingest` currently always calls `phase0_rubric()`. Add an optional
`--hunt <uuid>` that loads the hunt's real rubric instead, **read-only**.

- Reuse `_load_rubric(conn, hunt_id)` (`queue.py:186`) — it already returns
  `list[RubricCriterion]` from `rubric_criteria where enabled order by
  position`. Promote it out of `queue.py` only if that can be done without
  disturbing the worker loop; otherwise import it as-is. Do not write a second
  loader.
- `rubric_version` comes from the `hunts` row, matching what the projection
  passes (`listing["rubric_version"]`).
- Requires `DATABASE_URL`; error clearly (exit 2) if unset, as
  `split-property` already does (`cli.py:159-165`).
- Unknown/absent hunt id → clear error, not a traceback.
- **Read-only is a hard constraint.** `--hunt` reads the rubric and nothing
  else. It must not create a Listing, a job, or any row. Assert this in review.

**Done when:** `ingest --hunt <id>` on a seeded hunt prints a breakdown whose
criteria match that hunt's rubric, and `psql` shows no new rows in `jobs`,
`hunt_listings`, `properties`, or `scores`.

### C-2 — Honest default output

Without `--hunt`, the printed score is against the hardcoded Phase 0 fixture
rubric (2br · in-unit laundry · cats · balcony · all-in < $2,000). Today it is
labeled `<- display score` with no hint it is not the user's rubric.

Preferred: **drop the score block from the default output.** Print the
extracted facts, verify flags, source/tier, and cost — which is what you
actually want when debugging a fetch or an extraction. Print scores only when
`--hunt` is passed.

If the Phase 0 breakdown is still wanted standalone, keep it behind an explicit
`--phase0-rubric` flag with a one-line banner naming the fixture rubric. Decide
at implementation; the invariant is that **no unlabeled score is ever printed
against a rubric the user did not choose.**

**Done when:** no `ingest` invocation prints a score without naming which
rubric produced it.

### C-3 — `manzil submit <hunt-id> <url>`

Thin enqueue-only command. Creates the Listing + ingest job and exits; the
worker does the work. No pipeline runs in-process.

- **Preferred: go through the API** (`POST /v1/hunts/{id}/listings`) with a
  user token, so the role matrix and RLS apply unchanged. Needs a token source
  — env var (`MANZIL_API_TOKEN`) plus `VITE_API_BASE_URL`/an explicit
  `--api-url`. This keeps the CLI *above* the RLS boundary, which is the whole
  point.
- **Fallback: call the `submit_listing` RPC directly** via `DATABASE_URL`. Only
  if the token path proves impractical. This is service-role and bypasses RLS —
  if taken, it needs a security review and an explicit note that the command is
  admin-only, like `split-property`. **Do not pick this by default for
  convenience.**
- Accept `--source-policy` (optional), defaulted from hunt settings exactly as
  `ListingCreate` does (`api/src/manzil_api/listings/schemas.py:26-29`).
- Print the created listing id + job id; do not poll or block.

**Open question for implementation:** which path. Resolve it before writing
code, not during. If the answer is the RPC fallback, flag it rather than
proceeding quietly.

**Done when:** `manzil submit <hunt> <url>` produces a job row indistinguishable
from a UI submission of the same URL, and the listing appears in the UI.

### C-4 — Documentation

- **README** — CLI table and the stale "until wired to enqueue jobs (P1-7)"
  line. *(Being done separately, 2026-07-19, ahead of C-1..C-3; revisit once
  the commands exist.)*
- **IMPLEMENTATION §7, P1-7 "done when"** — currently reads *"CLI path and API
  path produce identical job rows."* That describes an architecture
  deliberately moved away from. Correct it to the API-only submit contract;
  note P1-7 is otherwise complete.
- **DESIGN §20 Decision Log** — append the 2026-07-19 entry: the CLI is
  reclassified from an alternate submit path to a debugging tool; the API is
  the sole Listing-creation path; one-writer and RLS rationale. Per AGENTS.md
  this is a material design change and needs the entry.

## 3. Sequence

C-4's doc corrections and C-1/C-2 are independent of C-3 and worth landing
first — they fix the misleading-score defect, which is the only thing here with
a live cost. C-3 is additive and gated on the token-vs-RPC decision.

C-1 → C-2 (same area of `cli.py`, C-2 depends on C-1's flag existing)
C-4 anytime
C-3 after its open question is resolved

## 4. Verification

- `uv run pytest` green; `uv run ruff check --fix . && uv run ruff format .`;
  `uv run mypy`.
- C-1/C-2: manual run against a seeded hunt (`scripts/dev_seed.py`) plus the
  no-new-rows check above. `MANZIL_LLM_MODE=replay` so it costs nothing.
- C-3: submit via CLI and via UI for the same URL; diff the two `jobs` rows —
  `type`, `state`, `payload` shape, `hunt_listing_id` presence should match.
- The read-only constraint on `--hunt` deserves an explicit assertion, not just
  an eyeball: it is the one place this plan could silently reintroduce the
  second-writer problem it exists to avoid.
