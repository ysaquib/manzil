# Phase 2 Implementation Plan — Collaboration

Status: active; P2-1..P2-8 landed, P2-9 automation is complete, and the
permission gate is green. Manual P2-9/P2-10 acceptance remains. Entered
2026-07-10 at Phase 1 exit. Written against DESIGN.md
(working tree, 2026-07-10 — §4.2, §8.2, §8.3, §9.1, §13, §16, §19) and
IMPLEMENTATION.md §7's provisional Phase 2 table (P2-1..P2-9), which this plan
revises per the "entering a phase means revising its table first" rule. Code facts
verified against the tree at Phase 1 exit (commit `a320e41` + the pending 2026-07-10
working-tree batch).

**Security note for execution:** RLS policies, invite tokens, role checks, and the
privileged service-role surface are security-sensitive. Execute P2-1..P2-4 via the
security-executor role (or with equivalent security review), never as ordinary
feature work.

## 0. Scope

**In scope (DESIGN §19 Phase 2):** RLS policies + permissions matrix (Curator role),
invites, realtime sync, comments, ratings, member colors, Tasks History tab.
**Exit:** second real user active; permissions verified at the RLS layer by tests.

**Explicitly out of scope** (per AGENTS.md phase discipline — do not build):
- DISCOVER/RECONCILE multi-source, VISION, Maps/ENRICH, utility baselines, custom
  criteria authoring, refresh/TTL machinery, Compare view, optional worker isolation,
  mobile sheet polish, `resolve_dedupe`/`resolve_dispute` checkpoints, the 24 h
  auto-resume sweep (all Phase 3)
- Anything in DESIGN §18 (Deferred/Backlog)
- Learning track: L1 stays gated on **Phase 0** exit (P0-11..14 still open); L2's
  phase gate (Phase 1 exit) is now met, but the track proceeds in order — no
  agents-mode code lands in Phase 2 work

**Phase 0 tail runs in parallel, unchanged:** P0-11 labels (human), P0-12/13 real
bench runs, P0-14 census + model-pin decisions. Nothing in Phase 2 depends on them.

---

## 1. Cross-cutting decisions

### 1.1 RLS architecture (the boundary, per DESIGN §16/§8.3)

- **Membership helper, not per-policy subselects.** One `security definer` function
  answers "what is the caller's role in hunt X":

  ```sql
  create schema if not exists private;

  create or replace function private.member_role(h uuid)
  returns hunt_role
  language sql stable security definer
  set search_path = public
  as $$
    select role from hunt_members
    where hunt_id = h and user_id = auth.uid()
  $$;

  revoke all on function private.member_role(uuid) from public, anon;
  grant execute on function private.member_role(uuid) to authenticated;
  ```

  `security definer` breaks the recursion problem on `hunt_members`' own policies
  and keeps every policy body a one-liner (`private.member_role(hunt_id) = 'owner'`,
  `... is not null` for "any member"). Returns NULL for non-members.

- **Global tables** (`properties`, `property_sources`, `floor_plans`, `extractions`,
  `property_images`, `criteria_catalog`, `utility_baselines`,
  `fetch_adapter_registry`): `enable row level security` + one SELECT policy for
  `authenticated`; **no write policies at all** — the worker's asyncpg service-role
  connection bypasses RLS, which is exactly §8.3's "writable only by the service
  role". One refinement: `extractions` rows with `hunt_id is not null` are
  hunt-scoped custom-criterion values (§8.2: "must never leak through the global
  namespace"), so their SELECT policy is
  `hunt_id is null or private.member_role(hunt_id) is not null` — a §8.3
  clarification to record in DESIGN §20 when P2-1 lands.

- **Per-hunt tables**: policies per the §4.2 matrix (full table in §2 below).
  `jobs` policies key on `jobs.hunt_id` directly — the 0004/0005 migrations made
  this a single indexed predicate on purpose.

- **Backfill in the same migration** (the lockout trap the provisional table
  already named): `create_hunt` has inserted the owner membership row since P1-5,
  and `dev_seed.py:111` seeds one, but any earlier hunt row must not lock its owner
  out the moment RLS flips:

  ```sql
  insert into hunt_members (hunt_id, user_id, role)
  select id, owner_id, 'owner' from hunts
  on conflict (hunt_id, user_id) do nothing;
  ```

- **Exactly-one-owner constraint** (P2-8's transfer test needs it as a backstop):

  ```sql
  create unique index one_owner_per_hunt
    on hunt_members (hunt_id) where role = 'owner';
  ```

- **Worker unaffected.** `manzil_worker` holds zero supabase-py imports (verified);
  all worker access is asyncpg with the service role, which bypasses RLS. No worker
  changes in P2-1.

### 1.2 "Own" semantics — no schema change

§4.2 grants Members "manage **own** jobs" and "overrides/fees/checkpoints on **own
listings**". `jobs` has no submitter column, and adding one is unnecessary:

- **Own listing** = `hunt_listings.added_by = auth.uid()`.
- **Own job** = a listing-scoped job (`hunt_listing_id is not null`) whose listing
  the caller added. Hunt-level jobs (`rescore`, `hunt_listing_id is null`) are
  system-triggered by mutations and manageable by the **Owner only** — nobody
  "owns" a rescore.

This covers every Phase 2 job type. If Phase 3's refresh jobs need requester
attribution, `jobs.created_by` is that phase's decision, not this one's.

### 1.3 The cancel-vs-checkpoint distinction, encoded in RLS

The matrix separates two things that are both `UPDATE jobs`: Curators may **resolve
checkpoints on any listing** but may **not manage (cancel/retry) anyone else's
jobs**. RLS can express this precisely because `WITH CHECK` sees the NEW row:

```sql
-- Curator: touch only parked jobs, and never park→cancelled
create policy jobs_curator_checkpoint on jobs for update
  using (private.member_role(hunt_id) = 'curator' and state = 'waiting_user')
  with check (state <> 'cancelled');
```

A checkpoint answer flips `waiting_user → queued` (passes); a cancel writes
`cancelled` (fails). Owner and own-job policies carry no state constraint — the API
service keeps its existing transition guards (`JobNotCancellable` etc.) as the
mirror layer.

### 1.4 API mirror: `require_owner` → a role-dependency family

Phase 1 shaped this seam deliberately (`valid_hunt_id` → `require_owner` at
`hunts/dependencies.py:24-38`): P2 changes dependency bodies, not routers.

```python
def require_role(minimum: HuntRole):          # owner > curator > member
    async def dep(hunt = Depends(valid_hunt_id), user = Depends(get_current_user),
                  client = Depends(get_user_client)) -> Hunt: ...
    return dep

require_member  = require_role(HuntRole.MEMBER)
require_curator = require_role(HuntRole.CURATOR)
require_owner   = require_role(HuntRole.OWNER)   # same name, new body — routers untouched
```

The body reads the caller's `hunt_members` row through the **user client** (RLS
lets any member read their hunt's membership), raising `NotHuntMember` (404-shaped,
don't leak hunt existence) / `InsufficientRole` (403). Routes that loosen from
owner-only to member (GET hunt, GET rubric, GET listings, GET jobs, POST listings,
…) swap `require_owner` → `require_member`; per-listing "own vs any" checks
(overrides, fees, pins, job cancel/retry, checkpoint answer) live in the service
functions, comparing `added_by`/role per §4.2 — with RLS as the actual boundary
underneath.

`list_hunts` (`hunts/service.py:103`) drops `.eq("owner_id", user_id)` for a
membership-driven read (select hunts joined through the caller's memberships) —
under RLS the filter is enforced anyway; the explicit join keeps intent readable.

### 1.5 Privileged surface: create `privileged.py`, exactly as §2 prescribed

IMPLEMENTATION §2 already names the case: *"API operations that legitimately need
the service role (accepting an invite writes `hunt_members` before membership
exists) go through an explicitly named `privileged.py` module."* Created now with
**three** operations, nothing else:

1. `accept_invite(token, user)` — validate token (exists, unexpired, unaccepted,
   not revoked), insert `hunt_members` with granted role + next unused color, stamp
   `invites.accepted_by`. One transaction.
2. `send_invite_email(email, token, hunt)` — `auth.admin.invite_user_by_email`
   (Supabase Auth's built-in email, NFR5 — no third-party mailer). Local testing
   via Mailpit, same as magic-link login.
3. `transfer_ownership(hunt_id, new_owner_id)` — demote current owner to curator,
   promote target, update `hunts.owner_id`, one transaction (demote-then-promote so
   the one-owner index never sees two). Caller-side owner check happens **before**
   the privileged call, in the service, via `require_owner`.

Everything else in the API keeps the user-JWT client. `grep privileged` stays the
audit.

### 1.6 Test identity: real users, real JWTs

Today `api/tests/conftest.py` fakes auth (`dependency_overrides[get_current_user]`
→ `FAKE_USER`) and reads/writes with the anon client — that dies the moment RLS is
live, and faking would defeat P2-3's whole point ("verified at the RLS layer").
New session-scoped fixtures against the local stack:

- `seeded_users` — creates four users once per session via the service-role admin
  API (`auth.admin.create_user`, email-confirmed): `owner@`, `curator@`, `member@`,
  `outsider@test.manzil`; signs each in for a real access token.
- `as_owner` / `as_curator` / `as_member` / `as_outsider` — supabase-py clients
  (anon key + that user's JWT) plus `httpx.AsyncClient` variants whose
  `Authorization` header carries the real token (no `get_current_user` override).
- A `collab_hunt` fixture: hunt owned by `owner`, memberships for curator+member,
  one listing added by `member`, one by `owner` (the "own vs any" fixtures).

Existing router tests migrate from `FAKE_USER` to `as_owner`; pure-validation tests
that never touch the DB may keep the override. All of it skips cleanly when the
local stack is down (existing `db_pool` pattern), and CI gains a
`supabase start && supabase db reset` step so P2-3 actually gates merges.

### 1.7 Realtime mechanics (P2-6 in the revised numbering)

- **Migration:** the local stack has realtime enabled but no tables published.
  Exactly the §13.3 five: 

  ```sql
  alter publication supabase_realtime
    add table hunt_listings, scores, comments, jobs, job_events;
  ```

  RLS applies to Realtime automatically (§8.3) — no extra security work.
- **Frontend:** one hook, `useHuntRealtime(huntId)`, mounted in the hunt layout
  route: a single channel per hunt, `postgres_changes` on the five tables
  (server-side `filter: hunt_id=eq.{huntId}` where the column exists —
  `hunt_listings`, `jobs`; coarse per-table invalidation for `scores`, `comments`,
  `job_events`, whose rows RLS already scopes). Events map to TanStack Query key
  invalidations — the §13.3 "one consistency mechanism".
- **Delete the P1-13 polling**: `frontend/src/features/jobs/api.ts` drops both
  `refetchInterval`s (30 s active / 15 s all — the file's own comment says "P2-4
  replaces the polling with Realtime"). NFR2's "no polling" becomes true here.
- Ratings are deliberately **not** in the publication — §13.3 pins exactly five
  tables. Own-rating mutations invalidate locally; others' rating dots refresh on
  window focus / other events. If that staleness annoys in real use, adding
  `ratings` is a one-line migration + a §13.3 touch-up — noted, not built.

### 1.8 Member colors

`hunt_members.color` stores either a named palette token or a canonical `#RRGGBB`
custom color. Automatic assignment uses the ordered `MEMBER_COLOR_TOKENS` list
`dusk, clay, moss, ochre, brick, olive, stone, plum`; acceptance assigns the first
token unused in that Hunt (§9.1 "next unused color"). The frontend resolves tokens
through `frontend/src/colors.ts` and uses custom hex directly. P2-6 lets members
change their own color to any palette token or valid hex value (RLS: self-row
update cannot touch `role` — §2 below).

---

## 2. P2-1 — Migration `NNNN_rls_policies.sql` (the boundary)

One migration: enable RLS on **every** table, helper function (§1.1), owner
backfill, one-owner index, policies. The §4.2 matrix, translated table-by-table
(O=Owner, C=Curator, M=Member, "member" = any role, blank = no policy → denied;
worker/service-role bypasses RLS everywhere):

| Table | SELECT | INSERT | UPDATE | DELETE |
|---|---|---|---|---|
| hunts | member, plus the authenticated `owner_id` creation-return path | any authed, `with check (owner_id = auth.uid())` | O (rename/archive/settings) | O |
| hunt_members | member | self-as-owner on own hunt (keeps `create_hunt` working): `with check (user_id = auth.uid() and role = 'owner' and hunt_id in (select id from hunts where owner_id = auth.uid()))` | (a) self color: `using (user_id = auth.uid()) with check (user_id = auth.uid() and role = private.member_role(hunt_id))` — new role must equal current role, so self-promotion fails; (b) O on others' rows (role changes) | O, `using (... and role <> 'owner')` — removing the owner row is impossible; transfer is the only path |
| invites | O | O, `with check (created_by = auth.uid())` | — (acceptance is privileged) | O (revoke) |
| hunt_listings | member | member, `with check (added_by = auth.uid())` | O/C any row; M own rows (`added_by = auth.uid()`) — covers pins | O only (§4.2 "delete listings") |
| rubric_criteria | member (view rubric: all roles) | O | O | O |
| overrides | member | O/C any listing; M where listing `added_by = auth.uid()`; always `with check (user_id = auth.uid())` | — (append-only) | — |
| fee_checklist | member | O/C any listing; M own listings | same as INSERT (upsert) | — |
| scores | member | — (worker only) | — | — |
| comments | member | member, `with check (user_id = auth.uid())` | author only (`user_id = auth.uid()`) — soft-delete + body edit | — (soft-delete only) |
| ratings | member | own row (`user_id = auth.uid()`) | own row | own row |
| jobs | member (task history: all roles) | member of `hunt_id` (submit + the rescore-on-mutation enqueues run under the user JWT) | O any; M/C own jobs (§1.2 join through `hunt_listings.added_by`); C checkpoint policy (§1.3) | — (rows are never deleted, FR10) |
| job_events | member (join through `jobs.hunt_id`) | — (worker only) | — | — |
| *global tables* | authenticated (extractions: `hunt_id is null or member` — §1.1) | — | — | — |

Also in this migration: `grant usage on schema private to authenticated;` and
`alter table ... force row level security` is **not** used (the API's asyncpg pool
belongs to the worker loop, which legitimately bypasses).

**Done when:** policies deployed; `supabase db reset` + dev-seed still green; the
Phase 1 hunt's owner still sees everything (backfill verified); `grep -r
service_role api/src` shows only `database.py` (worker-loop) + `privileged.py`.

**DESIGN upkeep at landing:** one §20 entry (RLS live; the `extractions`
custom-criterion SELECT refinement to §8.3).

---

## 3. P2-2 — API role matrix + test identity

**Listing-submission resolution (2026-07-11):** authenticated clients retain no
direct write policy on global tables. The authenticated-only, security-definer
`public.submit_listing` RPC (explicit authenticated-only EXECUTE grant) verifies Hunt membership and atomically creates the
URL-derived placeholder Property, Listing (`added_by = auth.uid()`), and ingest
Job. This constrained database capability keeps `privileged.py` limited to its
three pinned operations and prevents half-created submissions.

Hunt creation installs the Owner membership with an `AFTER INSERT` trigger. The
membership invariant is therefore atomic for API creation, seeds, and future
writers; the API no longer performs a fallible second PostgREST request. The
Hunt SELECT policy still admits `owner_id = auth.uid()` because PostgREST must
return the inserted row before membership-backed visibility is available to the
response; the trigger, not this visibility branch, establishes authorization.

Checkpoint answering uses the equally constrained `public.answer_job_checkpoint`
RPC so the authorized Job transition and its immutable `job_events` audit row
commit atomically without granting clients general write access to Job Events.

**Files:** `api/src/manzil_api/hunts/dependencies.py` (role family, §1.4),
`api/src/manzil_api/dependencies.py` (unchanged chain), every router that loosens
from owner-only, `api/src/manzil_api/privileged.py` (created, §1.5, initially
empty-but-wired so the grep-audit exists from day one), `api/tests/conftest.py`
(§1.6 fixtures), `jobs/service.py` + `overrides/service.py` + `fees/service.py`
+ `listings/service.py` ("own vs any" checks per §4.2).

Route-level minimums after the swap (only rows that change from Phase 1's
owner-everything are listed):

| Route | Phase 1 | Phase 2 |
|---|---|---|
| GET /v1/hunts/{id} · /rubric · /listings · /jobs | owner | member |
| POST /v1/hunts/{id}/listings | owner | member |
| POST /v1/jobs/{id}/cancel · /retry | owner | own job or owner (service check) |
| POST /v1/jobs/{id}/checkpoint | owner | own listing (M) / any (O, C) |
| POST /v1/listings/{id}/overrides · PUT /fees/{slot} · PATCH /pins | owner | own listing (M) / any (O, C) |
| DELETE /v1/listings/{id} · PUT /rubric · PATCH /v1/hunts/{id} | owner | owner (unchanged) |

**Done when:** existing router tests pass as `as_owner` with real JWTs against the
RLS-enabled stack; a member can read a hunt they don't own; `list_hunts` returns
membership hunts.

---

## 4. P2-3 — Permission integration tests (the phase exit gate)

**File:** `api/tests/test_rls_matrix.py`. The §4.2 matrix as literal data —
`(actor, action, target-ownership, expect)` tuples, parametrized — exercised **at
both layers**:

1. **RLS layer** (the boundary): each role's supabase-py client attempts the raw
   PostgREST operation (select/insert/update/delete per §2's table). Every
   forbidden pair must come back empty/denied; every allowed pair must succeed.
   Includes the sharp cases: outsider sees zero rows of a hunt; member self-promote
   via `hunt_members` UPDATE fails; member cancels another's job fails; curator
   answers another's checkpoint succeeds but cancels it fails (§1.3); member reads
   another hunt's custom-criterion extraction fails; owner-row DELETE fails;
   second-owner INSERT trips `one_owner_per_hunt`.
2. **API layer** (the mirror): the same pairs through the routers with real JWTs,
   asserting the §1.4 error shapes.

CI: add the local-stack step so this suite runs on every PR (skip-when-absent stays
for offline dev machines).

**Done when:** full matrix red/green in CI. This is the exit gate — nothing after
it merges while it's red.

---

## 5. P2-4 — Invites

**API** (`api/src/manzil_api/invites/{router,schemas,service,exceptions}.py`):

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/v1/hunts/{id}/invites` | owner | body `{email?: str, role: "member"\|"curator"}` → row with `token` (`secrets.token_urlsafe(24)`), `expires_at = now()+7d`; when `email` present, dispatch via privileged `send_invite_email`; always return the copy-link URL (`/invite/{token}`) |
| GET | `/v1/hunts/{id}/invites` | owner | pending (unaccepted, unexpired) invites |
| DELETE | `/v1/invites/{invite_id}` | owner | revoke (hard delete) |
| POST | `/v1/invites/{token}/accept` | any authed | privileged `accept_invite` (§1.5): expired/revoked/accepted → 410-shaped errors; success → `{hunt_id}`; idempotent for an existing member of the same hunt (returns the hunt, burns nothing) |

Color assignment on acceptance per §1.8. Invite email nullable = copy-link-only
token (§8.2). Tokens are single-role, expiring, revocable (§16).

**Frontend:** `/invite/:token` route (auth-gated: unauthenticated users hit the
magic-link login with a post-login return to the invite URL — the existing
`RequireAuth` redirect already carries `location.state`); `InviteAcceptPage`
accepts → navigates to `/h/{huntId}`. Invites section in settings (create with role
Select, copy-link button, pending list with revoke) ships with P2-8's settings
work; only the accept page is needed here.

**Done when:** second account joins via **both** paths (email through Mailpit
locally, copy-link) and lands in the hunt; curator grant works; expired/revoked
tokens refused; P2-3 suite extended with invite cases.

---

## 6. P2-5 — Realtime (mechanics in §1.7)

**Files:** migration `NNNN_realtime_publication.sql`;
`frontend/src/lib/realtime.ts` (`useHuntRealtime`); mount in the `/h/:huntId`
layout; **delete** both `refetchInterval`s in `frontend/src/features/jobs/api.ts`.

Invalidation map (event table → query keys): `hunt_listings` → listings;
`scores` → listings + scores + the open drawer's breakdown; `comments` → comments
for that listing; `jobs`/`job_events` → jobs (Tasks tabs) + any checkpoint prompt.

**Done when:** two browsers, two accounts: a score change and a new comment appear
< 2 s apart without refresh; `grep -rn refetchInterval frontend/src` is empty; an
outsider's subscription receives nothing (manual check — RLS on the socket).

---

## 7. P2-6 — Comments, ratings, colors

**API:**

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/v1/listings/{id}/comments` | member | insert `{body}`; `user_id = caller` |
| DELETE | `/v1/comments/{id}` | author | soft-delete (`deleted_at = now()`) |
| PUT | `/v1/listings/{id}/rating` | member | upsert own `{rating: 1..5}`; DELETE to clear |
| PATCH | `/v1/hunts/{id}/members/{user_id}` | self (color) / owner (role — P2-8) | color validated as a `MEMBER_COLOR_TOKENS` value or canonical `#RRGGBB` |

Reads are direct supabase-js per the two-client rule: `useComments(listingId)`
(filter `deleted_at is null` client-side rendering "deleted" tombstones only for
threading continuity — simplest: just exclude them), `useRatings(listingId)`,
`useMembers(huntId)`.

**Frontend:** detail drawer gains a Comments section (thread + composer + own-delete)
and a rating control (5 dots, own rating editable); Overview table gains the §13.2
rating-dots cell (one dot per rater, in their member color, tooltip = name + score)
and comment-count column; settings gains the own-color picker (swatches from
`colors.ts` tokens).

Open point recorded, defaulted, reversible: comment **moderation** (Owner deleting
others' comments) is not a §4.2 matrix row — Phase 2 ships author-only soft-delete;
if moderation turns out to matter with a second user, it's one policy + one route,
decided then.

**Done when:** rating dots render in member colors for two real accounts;
comment soft-delete leaves the row (DB) but not the thread (UI); vitest covers the
dots cell + comment component.

---

## 8. P2-7 — Tasks History tab

Jobs are never deleted (FR10) — the data has been accruing since P1-1. The read
paths already exist or are direct:

- Job list: existing `GET /v1/hunts/{id}/jobs?state=done,failed,cancelled`
  (`parse_job_states` already parses multi-state).
- Per-run expansion: **direct supabase-js read** of `job_events` by `job_id`
  (RLS-scoped via `jobs.hunt_id`, §2) — no new API endpoint, matching the
  reads-direct rule.

**Frontend:** `TasksHistoryTab` under the existing Tasks route (`Tabs`: Active |
History): run list with filters — listing, outcome, and member (resolved through
the `hunt_listings.added_by` join; hunt-level rescores render as "system") —
where expanding a run shows a
Mantine `Timeline` from `job_events` (stage started/completed/failed), checkpoint
Q&A (`checkpoint_asked`/`checkpoint_answered` event details; auto-resolutions
render when Phase 3 produces them — the event vocabulary already exists), error
text, `cost_actual_usd`, and duration. Plan-manifest display slot renders the
`plan` column when non-null (real manifests arrive with P3-2 — show what exists,
don't fake).

**Done when:** a seeded/legacy job renders fully from its events; filters compose;
a failed job shows its error and a checkpointed job shows Q&A.

---

## 9. P2-8 — Member management + settings surface

**API:** `members` router — `GET /v1/hunts/{id}/members` (member; also served
direct, route exists for completeness per §5.1), `PATCH .../members/{user_id}`
role change (owner; cannot change own role — transfer is the path), `DELETE
.../members/{user_id}` (owner; not the owner row), `POST
/v1/hunts/{id}/transfer-ownership` `{new_owner_id}` (owner → privileged §1.5;
target must already be a member).

**Frontend:** settings page (`HuntSettingsPage.tsx`) grows the §13.1 full surface:
Members (list with role badges + color dots, role Select, remove), Invites (§5),
own color (§7), hunt-settings panel (already shipped in Phase 1 — P1-5 PATCH +
form; verify plain-language labels against the §8.2 keys, nothing else), Danger
zone (transfer ownership with confirm modal, archive hunt).

**Done when:** owner transfer leaves exactly one owner — asserted both by the
partial unique index (constraint test) and end-to-end (old owner is curator, new
owner passes `require_owner`); removal revokes access instantly (RLS test: removed
member's next select returns empty).

---

## 10. P2-9 — Curator end-to-end (verification task)

No new code. With three real-ish accounts (P2-3's seeded users promoted through
real flows): curator overrides/fees/pins on the member's listing succeed; curator
answers the member's checkpoint; curator cancel/retry on the member's job denied;
curator cannot touch rubric/settings/members/invites. Verified by the P2-3 suite
(automated) + one manual pass through the UI.

**Done when:** matrix suite green + manual pass logged in the changelog entry.

**Automation status (2026-07-11): complete.** The matrix now explicitly covers
Curator retry, Hunt-settings mutation, and member-role mutation denials in
addition to the allowed stewardship actions and cancel/checkpoint distinction.
The UI pass and its changelog note remain human acceptance work.

---

## 11. P2-10 — Exit

Partner (second real user) invited via email, active in the real hunt: submits a
listing, rates, comments, fills a fee slot after a leasing-office call. Permissions
matrix green in CI. Then: revise the Phase 3 table on entry per the standing rule,
with a fresh look at the P0-14 census/model decisions (which should be closed by
then — they gate P3-14's tier-3 scope).

**Repository-prep status (2026-07-11): complete.** Phase 3 readiness and
dependency-wave tables are prepared in IMPLEMENTATION §7. Formal Phase 2 exit,
the real-partner workflow, CI confirmation, and final Phase 3 entry revision
remain human/external gates; P0-14 is still open, so P3-14 stays conditional.

---

## 12. Sequencing

```
P2-1 RLS migration ──► P2-2 API roles + test identity ──► P2-3 matrix tests (GATE)
        │                                                        │
        │            ┌───────────────┬──────────────┬────────────┤ (parallel after the gate)
        │            ▼               ▼              ▼            ▼
        │       P2-4 invites   P2-5 realtime   P2-6 comments  P2-7 history
        │            └───────────────┴──────┬───────┘
        │                                   ▼
        └──────────────────────────► P2-8 members/settings ──► P2-9 curator e2e ──► P2-10 exit
```

P2-1..P2-3 are strictly serial (each is the next one's substrate) and
security-sensitive (§0 note). P2-4..P2-7 are independent tracks after the gate.
P2-7 (history) has no dependency on P2-4/5/6 and can start any time after P2-1.

---

## 13. Testing & CI

- **CI gains the local Supabase stack** (`supabase start && supabase db reset`
  before pytest) so the P2-3 gate and the migrated router tests actually run on
  PRs. Skip-when-absent behavior stays for offline dev.
- **API:** real-JWT fixtures (§1.6); matrix suite (§4); router tests migrated off
  `FAKE_USER`; invite/member/comment/rating router tests follow the existing
  per-router test convention.
- **Worker:** untouched by RLS (service role); existing suites must stay green as
  the no-regression check after P2-1.
- **Frontend:** vitest for rating-dots cell, comments component, history timeline
  rendering from a fixture event list, invite-accept page states
  (valid/expired/revoked). No snapshot tests (convention).
- **No LLM surface changes anywhere in Phase 2** — no bench rerun owed.

---

## 14. Exit criteria (DESIGN §19)

- Second real user active in Yusuf's live hunt (invited by email, submitting,
  rating, commenting).
- Every forbidden (role, action) pair denied **at the RLS layer** by automated
  tests running in CI; every allowed pair verified.
- Realtime: no `refetchInterval` remains; two-browser sync < 2 s.
- Task history renders complete runs (timeline, checkpoint Q&A, cost) for jobs
  that predate Phase 2.
- Owner transfer + member removal verified; exactly one owner, constraint-backed.
- Phase 3 table revised on entry, per the standing rule.
