# Admin Dashboard

Status tracker and orientation for the Manzil operator surface.
`DESIGN.md` owns intent (§3, §4.2, §19, §20 v3.37–v3.44); `IMPLEMENTATION.md` §7
owns the task table and acceptance evidence. **This file is the map** — where the
pieces are and why they are shaped that way.

Last updated 2026-08-11 (DESIGN v3.77 — Hunt lock/read-only lifecycle and mobile
table layouts added after the AD workstream completed).

---

## What it is

One place for the things that live *above* a Hunt: the people, the Hunts
themselves, the pipeline that costs money, and the feedback inbox nobody could
previously read. It is a separate workstream from Phase 3, parallel to it, and
**gates nothing**.

Route: `/admin/*`, deliberately outside the `/h/:huntId` tree, with its own shell
— none of it is Hunt-scoped, so the hunt navbar's items would all be dead.

## Status

| Slice | What it does | State |
|---|---|---|
| **AD-C** | Tier-3 fetch spend priced and folded into `cost_actual_usd`; per-stage cost persisted; monthly credit counter | ✅ 2.0.105 |
| **AD-G** | The four places history was being destroyed: fee values, role changes, Listing curation, deletions | ✅ 2.0.106 |
| **AD-F** | Private activity union + Owner RPC + `site_admins` identity primitive | ✅ 2.0.107; hardened 2.0.133 |
| **AD-0** | Design ratification — glossary, §4.2 column, workstream entry | ✅ |
| **AD-1** | Admin identity, the gate, `admin_audit_log`, router | ✅ 2.0.108 |
| **AD-2** | Panel shell, nav entry, feedback inbox | ✅ 2.0.109 |
| **AD-3 / PR-1** | People — roster, detail, provision/update/suspend/delete, memberships; sole account-creation path | ✅ 2.0.110 / 2.0.121 |
| **AD-4** | Hunts + the ghost view (`open as owner`), ownership transfer, permanent Hunt deletion, audited lock/unlock | ✅ 2.0.111; expanded 2.0.155–2.0.156 |
| **AD-5** | Jobs, Costs, System, Audit log — with `@mantine/charts`; responsive cards/contained scrolling | ✅ 2.0.112; responsive 2.0.156 |
| **DM-10** | Owned-Hunt Demo publication, freshness, and kill switch | ✅ 2.0.149 |

**The workstream is complete (AD-C, AD-G, AD-0…AD-5).**

Deferred to an **Admin phase 2** (DESIGN §18): spend caps with teeth, true user
impersonation, a general audit log over non-admin actions.

---

## The three decisions that shape everything

**1. Access is split.** RLS is the security boundary, so "an admin sees
everything" had to be true in Postgres, not React. But adding a bypass predicate
to every policy in the schema would make each future migration a security
decision. So: a **service-role router owns the panel and every admin write**,
while only *reads* widen. Writes stay in one auditable place.

**2. The gate queries the database, not a JWT claim.** A claim is fixed at
sign-in, so a *revoked* admin would keep access until their token expired. It is
one indexed PK lookup. `test_revoking_admin_takes_effect_without_a_new_token`
revokes an admin and reuses the same token to prove the refusal is immediate.

**3. History lives in the domain, not in an audit log.** Manzil already records
provenance correctly — `overrides` is append-only with an author, `visit_entries`
never overwrite, extraction facts carry lineage. AD-G added append-only
companions where that was missing rather than a global event stream, because a
parallel copy that can disagree with the domain table is a liability. The **one**
exception is `admin_audit_log`: nothing in the schema can record "an admin opened
a Hunt they are not a member of", because from the schema's point of view nothing
happened.

---

## Where things are

```
supabase/migrations/
  20260824000000_job_stage_costs.sql     AD-C  per-(job,stage) spend + tier3_credit_usage
  20260825000000_provenance_gaps.sql     AD-G  4 history tables, all trigger-filled
  20260826000000_hunt_activity_feed.sql  AD-F  identity + original feed (access superseded below)
  20260827000000_admin_audit_log.sql     AD-1  append-only ledger
  20260828000000_feedback_triage.sql     AD-2  feedback.triage
  20260829000000_admin_read_predicate.sql AD-4 SELECT-only admin predicate (31 policies)
  20260901000011_hunt_activity_access.sql AD-F private union + bounded Owner RPC
  20260901000014_demo_publications.sql   DM-10 private releases/captures + demo-assets
  20260901000016_former_member_attribution.sql removal-time contributor identity RPC

api/src/manzil_api/admin/
  dependencies.py   require_site_admin (the gate) + AdminAudit (the ledger writer)
  router.py         summary/hunts/management/transfer/delete/activity/audit/admins/feedback
  people.py         AD-3 account management — the half that writes to accounts
  operations.py     AD-5 jobs, costs, system
  schemas.py        response shapes

frontend/src/features/admin/
  AdminLayout.tsx       shell + rail; guard is UX only
  AdminOverviewPage.tsx counters, credit meter, needs-attention
  AdminPeoplePage.tsx   roster + detail panel, the delete refusal
  AdminHuntsPage.tsx    roll-ups + activity + transfer/delete + "Open as owner"
  GhostBanner.tsx       the persistent marker
  useGhostMode.ts       derived from non-membership, never URL state
  AdminFeedbackPage.tsx the inbox
  AdminJobsPage.tsx     cross-Hunt queue + stale locks
  AdminCostsPage.tsx    @mantine/charts spend, three ways
  AdminSystemPage.tsx   read-only machine state
  AdminAuditPage.tsx    what admins did
  AdminDemoPage.tsx     owned-Hunt publication, review, stale state, kill switch
  api.ts                hooks — all via apiFetch, never direct Supabase

worker/src/manzil_worker/costs.py   AD-C  CostTally, outside llm/ on purpose
worker/src/manzil_worker/ops/demo_publication.py  durable Demo release builder
```

`POST /v1/admin/people` is the only account-creation path. It is Site-Admin
gated, writes `user.provision` to the Admin Audit Log, and sends the new account
to password setup. Hunt invites and Login magic links authenticate existing
accounts only; neither may create one.

## Routes

| Route | Who | Notes |
|---|---|---|
| `GET /v1/admin/me` | anyone signed in | Answers `is_site_admin: false` rather than 403 — the frontend calls it on every load, and a 403 there is console noise for every ordinary user |
| `GET /v1/admin/summary` | admin | Overview counters |
| `GET /v1/admin/hunts` | admin | Roll-ups incl. LLM/fetch cost split |
| `GET /v1/admin/hunts/{id}/management` | admin | Current roster plus transfer choices and named deletion blockers |
| `POST /v1/admin/hunts/{id}/transfer-ownership` | admin | Existing-member target; atomic one-Owner mutation; audited in the same transaction |
| `DELETE /v1/admin/hunts/{id}` | admin | Exact-name-confirmed permanent deletion; selected Demo Hunt and active Jobs are refused |
| `GET /v1/admin/hunts/{id}/activity` | admin | Reads grantless `private.hunt_activity_all` after the live admin gate |
| `GET /v1/admin/audit` | admin | The ledger |
| `POST /v1/admin/admins` · `DELETE /v1/admin/admins/{id}` | admin | Grant / revoke |
| `GET /v1/admin/feedback` · `/counts` · `PATCH /v1/admin/feedback/{id}` | admin | The inbox |
| `GET /v1/admin/people` · `/{id}` | admin | Roster and detail |
| `POST /v1/admin/people` | admin | Invite, optionally straight into a Hunt |
| `PATCH /v1/admin/people/{id}` | admin | Display name, email, confirm |
| `POST .../suspend` · `/restore` · `/password-reset` | admin | Reversible account actions |
| `PUT .../memberships` · `DELETE .../memberships/{hunt}` | admin | Role changes; owner moves route through `transfer_hunt_ownership` |
| `DELETE /v1/admin/people/{id}` | admin | **Refused** while they own a Hunt |
| `/h/{huntId}` (ordinary Hunt URLs) | admin | The ghost view — no special route, see below |
| `GET /v1/admin/jobs` · `/{id}` | admin | Cross-Hunt queue; `stale_only=true` for dead workers' locks |
| `POST .../jobs/{id}/retry` · `/cancel` · `/jobs/release-locks` | admin | Queue control, all audited |
| `GET /v1/admin/costs?days=` | admin | Spend by stage, Hunt and model + daily series |
| `GET /v1/admin/system` | admin | Queue health, model pins, key **presence** |
| `GET /v1/admin/demo` · `/demo/hunts` | admin | Current release/freshness and only the caller's owned Hunt candidates |
| `POST /v1/admin/demo/preflight` · `/demo/publications` | admin | Exposure inventory, exact-name-confirmed durable publication |
| `PATCH /v1/admin/demo` | selected Hunt's admin Owner | Enable current release or immediately disable without deselecting |
| `/v1/admin/ghost/...` | admin non-member of the target Hunt | Mirrors Owner Hunt/listing/rubric/people mutations; every write is audited with `via_ghost_view = true` |

## Hunt lifecycle actions

Admin → Hunts separates installation lifecycle from Ghost View stewardship. Transfer picks an existing current member and calls the same security-definer mutation as an Owner transfer, so the old Owner becomes Curator and the one-Owner invariant is never temporarily broken. The management preflight works whether the Site Admin is also a Hunt member; the mutation is always an explicitly audited Site Admin action from this panel.

Permanent deletion uses the shared named-subject modal and requires the exact Hunt name. The preflight and delete endpoint both name/refuse two blockers: the selected Demo Hunt, which must first be replaced in Demo Mode, and queued/running/waiting-for-user Jobs, which must finish or be cancelled. The Hunt row is locked before those checks, impact counts are captured, and cascade + Hunt tombstone + Admin Audit entry commit together. Hunt-owned memberships, Listing associations, scores, Overrides, comments, ratings, Visits, Jobs, Rubric, invites, and Hunt-scoped Extractions go; shared Properties, Sources, Floor Plans, images, and Catalog facts do not.

## Demo Mode publication (DM-10)

The Demo page is intentionally stricter than Ghost View. A Site Admin can
support any Hunt through Ghost View, but may publish only a Hunt whose
`hunts.owner_id` is their own account. That prevents operational access from
becoming permission to expose another Owner's comments, ratings, Visits, or Job
history publicly.

Selection is two-step: preflight inventories the public surface and returns a
ten-minute, single-use confirmation bound to the actor, Hunt, and source
fingerprint; publication requires the exact Hunt name. Every member needs an
explicit per-Hunt display name. The worker builds a versioned release and
promotes it only after rechecking the Hunt fingerprint, ownership, Site Admin
grant, and demo generation. There is one in-flight publication installation-
wide. The old release remains current through queued/building/failed/superseded
states.

The status response distinguishes configured `enabled` from effective
`available`. The Admin badge says **Blocked**, not **Public**, if ownership,
publisher consent, explicit member names, the current release, or another
fail-closed prerequisite has drifted. A direct publication request reruns both
content and security preflight on the server; UI-disabled controls are not an
authorization boundary. Only the first select-and-enable operation may request
enablement on promotion.

A building worker heartbeats its publication lease. A second worker may reclaim
a stale lease after the queue orphan interval, retry it up to three times, and
then fail it without displacing the prior ready release. Promotion, supersede,
and failure writes all verify lease ownership so a late worker cannot overwrite
a reclaimed result.

Active Listings are live reads. Archived Listings define the release's replay
slate, and mapped Properties define its frozen basemaps. Consequently the page
shows these as separate counts and marks the derived release stale when those
inputs change. Updates are explicit; no Hunt mutation automatically calls
Google or changes the public replay slate. Disabling is the exception to every
workflow guard: it is immediate, retains Hunt/release, rotates the session
generation, and stands even if its audit write fails.

The current release is an immutable snapshot. Restoring or permanently deleting
a source Listing does not punch a hole in a capture that an operator already
reviewed; an explicit **Publish updates** replaces that replay membership.

## Things that will bite you

- **`site_admins`, `admin_audit_log` and `feedback` have RLS on with *no
  policies*.** That is deny-all, and it is deliberate — reads go through the
  service-role router. A direct Supabase query returns `[]`, not an error, which
  makes it look like the data is missing. It isn't; you used the wrong client.
- **The raw activity union is not a client surface.**
  `private.hunt_activity_all` is a grantless security-barrier view. Owners use
  `get_hunt_activity`, whose exact-role check and 500-row cap are the Hunt-local
  boundary; Site Admins use the route above. Do not add a public compatibility
  view or grant client SELECT on the private union.
- **The primordial admin cannot be deleted by anything**, including a superuser
  `DELETE`, because it is guarded by a trigger rather than a policy. To remove it
  in a dev database you must disable `site_admins_protect_primordial` first.
- **`admin_audit_log` refuses UPDATE and DELETE**, so test teardown cannot clean
  it up. That is the property under test.
- **Private Demo tables and `demo-assets` are not frontend data sources.** They
  have no client grants/read policy. The public API accepts only a current Demo
  token and exact current-manifest paths; do not add a Storage policy to make a
  broken image easier to debug.
- **Publish updates while disabled must stay disabled.** `enable_on_success` is
  an explicit first-selection intent, not `!demo_enabled`; deriving it from the
  current switch would turn a maintenance publish into an accidental public
  launch.
- **A release belongs to the Site Admin who published it as Hunt Owner.** If
  ownership transfers, even to another Site Admin, the release goes dark until
  the new Owner reviews and publishes it. Ownership alone is not inherited
  consent to expose collaboration history.
- Two Supabase advisor findings on these objects are **accepted, not
  oversights** — see IMPLEMENTATION.md §7.

## Deleting people (AD-3)

The one operation with no undo. It is **refused** where it would destroy a
Hunt, and **confirmed against a named list** everywhere it is allowed
(DESIGN §20 v3.73).

`hunts.owner_id` has no cascade, but `hunt_members`, `hunt_listings`, `jobs`,
`visits` and every fact under them do — deleting the account of someone who owns
a Hunt would take the Hunt and its entire history with it. `DELETE
/v1/admin/people/{id}` therefore **409s while they own anything**, and the
message names the Hunts. `PersonDetail.blocking_owned_hunts` carries the same
list, so the panel disables Delete and shows the transfer beside it instead of
letting the operator discover the problem by being refused.

Deleting is refused a **second** way, too: eleven columns across the Visit
tables, `hunt_shared_filters` and `listing_unit_group_states` reference
`auth.users` with `NO ACTION`, so an account that ever created a Visit cannot be
removed. That returns **409 `account_still_referenced`** naming what blocks it,
rather than a raw foreign-key 5xx. It is not a cascade on purpose: a tour is not
deleted because its creator closed their account, and §9.7's per-member roll-up
cannot survive its author being nulled — the work belongs to the Hunt, not the
person. The check reflects the FK catalogue, so a future table adding another
`NO ACTION` reference is covered without anyone remembering to update a list.

**Suspension is the reversible alternative** and is what an operator should
usually reach for. It is an auth-level ban (`ban_duration`), not a column of
ours: a second source of truth for "can this person sign in" is exactly the kind
of thing that drifts, and the ban is what Supabase actually enforces.

A delete the API *would* accept still goes through `ConfirmDeleteModal`
(`frontend/src/components/`): the account is named in the modal and the operator
types its **email address** back before the button enables. The roster also has
per-row checkboxes with a page-scoped select-all and a **Delete N accounts**
bar; that confirmation lists every selected account in a scrolling pane and asks
for the phrase `permanently delete all selected accounts`. Accounts that own a
Hunt are listed with *Skipped — owns N Hunts* and are never sent, which is the
`blocking_owned_hunts` refusal rendered before the request rather than after it.
Bulk deletes run **one request at a time**: each is an audited account deletion,
and a partial failure has to be able to name the accounts that survived — those
stay ticked in the roster with the server's reason in the notification. Removing
a *membership* uses the same modal without the typing, since the Hunt picker
directly beneath it puts them back.

Promoting someone to owner routes through `transfer_hunt_ownership` rather than
writing the role — a Hunt has exactly one owner, and setting a second directly
would leave the old one in place.

Removing only their membership has different semantics from deleting the account. The `hunt_members` row disappears immediately, so access, the roster, Presence, notification fan-out, and current-member counts all stop. Existing collaboration history stays. `record_hunt_member_tombstone()` snapshots the effective Hunt-visible name, and remaining Hunt members read that small attribution projection through `get_hunt_contributor_identities`; comments, ratings, Tasks, and Visit work render **Former User (Name)** with neutral grey rather than calling the departed person *Member*. The tombstone/governance history itself remains Owner/Site-Admin-only.

## The ghost view (AD-4)

**There is no ghost route.** "Open as owner" is a plain link to `/h/{huntId}`.
The SELECT-side read predicate means the existing Hunt screens already serve a
Site Admin, so there is no parallel implementation to keep in step — and no
`?ghost=1` to forge, go stale, or be *missing* when it should be set, which is
the direction that puts an admin into somebody's Presence as a phantom body.

Ghost mode is derived by `useGhostMode(huntId)`: **site admin AND not a member
of this Hunt**. It reports `undefined` until membership is known, and every
consumer treats not-yet-known as *not a member* — observe first, join only once
proven. That asymmetry is deliberate; the opposite default flashes an admin onto
a live tour.

What changes for a ghost:

| | |
|---|---|
| Banner | Persistent, on every screen of the Hunt. An admin two clicks deep cannot otherwise tell whose data they are editing. |
| Member list | They are simply not in `hunt_members`, so absence is free. |
| Presence | Channel subscribed, `track()` never called — they watch without appearing. |
| Visits | `readOnly`, reusing the prop the Visit screens already had for completed tours. |
| Everything else | The Owner's controls, attributed and audited. |

**An admin who *is* a member of the Hunt gets none of this** — §4.2's conditional
clause. `member_role()` was deliberately left unchanged so an admin never starts
*looking* like a member.

### The read/write asymmetry

`20260829000000_admin_read_predicate.sql` adds `private.can_read_hunt()` /
`can_read_hunt_governance()` to **31 SELECT policies and nothing else.** The
migration ends with two self-checks that fail it outright if either half drifts:

1. any Hunt-scoped SELECT policy lacking the predicate (a new table that forgot
   it shows up as one silently empty panel section);
2. **any write policy that admits a Site Admin** — the dangerous direction, since
   an admin writing through PostgREST is an admin whose change never reaches
   `admin_audit_log`.

To exercise the ghost view locally, make a Hunt you do not belong to:

```sql
insert into hunts (name, owner_id)
select 'Someone Else''s Hunt', id from auth.users where email <> 'you@example.com' limit 1;
```

## Costs, and one thing it does not claim (AD-5)

Spend is real: `job_stage_costs` gives **by stage** and **by Hunt** and the daily
series directly, and `tier3_credit_usage` drives the credit meter against the
5,000/month allowance.

**"By model" is derived, and the UI says so.** AD-C records spend per *stage*,
not per model, because per-call telemetry is Langfuse's job. So the model
breakdown folds stage spend under the model each stage is pinned to **right
now** — genuinely useful for "what is Gemini costing us", and wrong if read as
history, since a re-pinned stage files its older spend under the new model. The
response carries `grouped_by_current_pin: true` and the card is captioned.

Charts are `@mantine/charts` (`BarChart`, stacked), so the panel matches the
rest of the frontend. The two series are LLM and fetch and they are never
blended — fetch is a thin sliver at current volumes, which is honest; the exact
figures live in the table under each chart rather than being exaggerated in the
plot.

## Stale locks

A `running` Job whose worker died stays running forever, holding a claim nobody
will release. From a per-Hunt Tasks tab it just looks slow, which is why it gets
its own filter and its own bulk action here. Releasing **re-queues** rather than
failing: nothing is known to be wrong with the work itself, only with the
process that was doing it. `STALE_LOCK_MINUTES = 15`, against a worker that
refreshes `locked_at` at every persist-before-advance point.

## Bootstrapping an admin

There is deliberately no UI path to create the first one.

```sql
insert into site_admins (user_id, is_primordial, note)
select id, true, 'system owner' from auth.users where email = 'you@example.com';
```

The first row is the **system owner** — the owner of the Manzil application
itself — and is immutable. That, rather than the "don't revoke yourself" rule, is
what makes locking everyone out impossible: self-revocation guards still fall to
two admins removing each other.

## What AD-2 shipped

The shell, the nav entry, and the inbox.

The nav entry sits in `NavbarFoot` directly above *Send feedback* — the same
"meta, not Hunt" cluster, and the natural neighbour of the inbox that receives
those reports. The `/` Hunt switcher also leads with a filled primary-colour
Admin panel card, so the panel is reachable before entering a Hunt. Both render
only for admins, which is **UX, not enforcement**: the API refuses everyone else
regardless. The switcher's Hunt query remains explicitly membership-scoped;
Ghost View read widening must never turn every Hunt into one of "Your hunts."

Tabs that later slices will build are **shown and disabled**, labelled with the
slice that owns them. The panel's shape is part of the information, and a link
that 404s is worse than one that says "not yet".

The inbox needed almost no new infrastructure. `feedback` has carried reporter,
route (drawer params included), Hunt, build and browser since P3-16, and its
migration said in as many words that reads "belong to an operator holding
`service_role`" — this is that operator arriving. The only schema change was a
`triage` column. The route, build and browser sit **on the card** rather than
behind a click, because that context is the entire difference between a two-line
complaint and a reproducible bug.

## Verification

- api **314 passed** (7 new for the inbox, 13 for the router, 7 for the feed,
  8 for the provenance gaps)
- frontend **678 tests / 91 files**, tsc + eslint clean, production build green
- Driven in WebKit against the live stack as the primordial admin: `/admin`
  redirects a non-admin, the rail renders with pending slices disabled, the
  Overview shows real counts (4 people, 4 hunts, 6 listings, $0.33 spend, 1
  failed Job, 1 new report), the credit meter reads `0 / 5,000`, and the inbox
  renders the report with its full route + build + browser line and filters by
  triage state. AD-3 driven the same way: the roster lists real accounts with
  their state, Hunt counts and spend, and opening an account that owns a Hunt
  shows the blocking alert with **Delete and Remove-from-Hunt both genuinely
  `disabled` in the DOM**, not merely styled that way. AD-5 driven the same way:
  all four remaining tabs render from real rows — Costs showing $0.28 across the
  daily chart, by-stage, by-Hunt and by-model tables with the credit meter at
  `4 / 5,000`; Jobs listing a real failed ingest with Retry/Cancel; System
  reporting 14 model pins and five services as presence-only; Audit log showing
  the `job.retry`, `admin.grant` and `user.delete` this session generated.

> Safari's MCP screenshot returned a blank frame for these pages while the
> accessibility tree showed full content — a capture-side quirk, not a render
> failure. Visual confirmation is by DOM inspection; open `localhost:5173/admin`
> to see it directly.
