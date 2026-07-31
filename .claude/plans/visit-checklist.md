# Plan — Visit Checklist

**Status:** approved 2026-07-30. **VC-0 landed** (design ratification — DESIGN v3.30) and
**VC-1 landed** (foundations: migration, RLS, template seed, visit/unit endpoints) and
**VC-2 landed** (Visits tab, create flow, pre-visit page) and **VC-3 landed** (checklist runtime:
`visit_entries`, the batched `PUT /entries`, the four entry-kind controls — IMPLEMENTATION 2.0.96).
**VC-4 landed** (defect log + promotion + red-flag tally — IMPLEMENTATION 2.0.97).
**VC-5 landed** (Realtime table wiring, per-Visit Presence, bylines, team aggregates — IMPLEMENTATION 2.0.98).
**VC-6 landed** (local-first queue, sync badge, `visit_entry_conflicts` + picker — IMPLEMENTATION 2.0.99, DESIGN v3.33).
**VC-7 landed** (money ledger, Fee Proposals, drawer ✓/✕ rows — IMPLEMENTATION 2.0.100, DESIGN v3.34).
**VC-8 landed** (`visit_unit_group_scores`, Overview Visit column, drawer Visits section — IMPLEMENTATION 2.0.101, DESIGN v3.35).
**The workstream is complete: VC-0 … VC-8 all landed.** Q1–Q6 ruled; see §3. Deferred to a Visits phase 2 (§18): photos, **voice notes + transcription** (answer a Question aloud instead of or alongside typing, and spoken comments on a Visit — same Storage bundle as photos; first LLM surface in Visits; needs a ruling on the Question gate), Rubric-derived checklist items, hunt-wide recurring custom items.
**UI mockup:** interactive prototype (Dusk & clay tokens, both themes) — brainstormed and iterated 2026-07-29/30.
**Template source:** `docs/apartment-tour-checklist.md` (21 sections, ~160 items).
**Author's note:** the design rulings in §2 are Yusuf's, recorded verbatim in intent. §3 lists what still needs a ruling before design ratification (VC-0) can land.

---

## 1. What this is

A **Visit** is a tour of a Property, recorded collaboratively on a phone while it happens and read on a
desktop afterwards. It replaces `docs/apartment-tour-checklist.md` as a thing you operate rather than
print.

Three surfaces: a **Visits tab** (list + create flow), the **visit checklist** itself (phone-first,
desktop-editable), and two **integration points** in existing screens (listing drawer, Overview column).

**What it is not:** it is not an Extraction source, it does not feed the scoring engine, and it does not
give the app knowledge of what units exist at a property. See §2 and §4.1.

---

## 2. Rulings already made

| # | Ruling |
|---|---|
| R1 | A Visit hangs off a **Property**, with optional Floor Plan pointers (plural). Survives DEDUPE and multi-Source RECONCILE without reparenting. |
| R2 | **One Visit per tour**, timestamped, spanning as many units as you walk. Prefill from a previous visit at the same Property. |
| R3 | **No solo mode.** A solo tour is a visit where one member filled things in; absent members' Impressions read "didn't attend" and can be added later. |
| R4 | **Fixed built-in template**, plus per-visit custom questions/checks that are always visibly labelled custom. |
| R5 | **No feedback into scoring.** The visit shows in the drawer and as a separate **Visit** column in Overview. Adjacent to Fit, never merged. |
| R6 | **Local-first:** optimistic local writes, a queue, a visible "N waiting" marker. Conflicts are *surfaced*, not auto-resolved (§7.2). |
| R7 | **Confirmed fees propose, never write.** Accept/reject on the listing; rejecting leaves the visit's own figure intact. Two icons (✓/✕) are allowed on proposal rows only — the pencil/revert slot stays single everywhere else. |
| R8 | Every checklist item is one of four kinds — **Fact**, **Check**, **Question**, **Impression** (§4.2). Sharing is a property of the *item*, not of the checklist. |
| R9 | Sections inherit the app's own fact scope: **Property-scoped** answers are recorded once per visit, **Floor-Plan-scoped** answers once per unit. The unit switcher exists only where it applies. |
| R10 | §21 (scoring/verdict) is **mixed scope** and splits: price/condition/size/noise/light per unit; felt safety, commute, management impression, common areas once per property. |
| R11 | Overview is **one row per Unit Group**; its Unit column is the group descriptor (`2 bd / 2 ba`), never a unit number. A unit's score reaches its group via its Floor Plan, and the group shows the **best** of the units toured (§6). |
| R12 | When an item's scope is genuinely ambiguous, it defaults to **Property**. A property answer repeated per unit is harmless; a unit answer shown property-wide is a false statement about units nobody looked at. |

---

## 3. Open questions — need a ruling before VC-0 lands

Per AGENTS.md ("ambiguous or missing design detail → ask, don't guess"), these are not assumptions I
should make silently. Recommendations attached; each answer gets recorded in DESIGN.md.

| # | Question | Recommendation |
|---|---|---|
| Q1 | **Task numbering / phase.** This is a new product capability, not agent-system work, so it doesn't fit Phase 3's theme or exit criteria. | A **"Visits" workstream (VC-1…VC-8)** running parallel to Phase 3 and gating nothing, recorded in DESIGN §19. Alternative if you prefer one sequence: `P3-24…P3-31`. IDs are trivially renameable. |
| Q2 | **Who may do what.** §4.2's roles table has no visit rows. | Any **Member** creates a visit, answers items, and logs defects. Only the **creator or Owner** cancels or deletes one. **Accepting a fee proposal follows the existing Overrides permission** (Owner/Curator any listing, Member own listings) — because accepting *is* an override/fee write. |
| Q3 | **Are photos in v1?** They need a Storage bucket, signed-URL reads, upload UI, and storage RLS. | Ship v1 **without** photos (VC-6 covers the defect log; photos are its own slice, VC-6b). The mockup's camera affordance is the only thing that regresses, and a defect note without a photo is still worth having. This is the cleanest thing to cut if scope needs to shrink. |
| Q4 | **Does the Overview Visit column include building-scope impressions?** | **No** — unit-scope only. Building scores are identical across every row of that property, so including them would compress the differences between rows without adding information. Building scores show in the drawer. |
| Q5 | **Template versioning.** | Freeze `template_version` per visit. A later template edit must not retroactively change a completed visit's meaning or completion percentage. |
| Q6 | **Custom item lifetime.** | **Per-visit** in v1 (matches the mockup's "Added by Yusuf"). Hunt-wide recurring custom items go to §18 deferred, alongside the Rubric-generated ones (R4). |

### Answers to Open Questions:
1. I'm okay with the VC system as per your recommendation
2. Any member can create a visit, and permissions as per recommendations
3. Let's defer photos to VC phase 2 (VC2)
4. No; unit-scope only
5. yes, let's go as recommended
6. as recommended, per visit.

---

## 4. Data model

New tables, all Hunt-scoped. Migration file: `supabase/migrations/2026MMDD000000_visits.sql`
(+ a second for entries/defects if the first grows past reviewable size).

### 4.1 The §18 boundary — read this before writing the migration

DESIGN §18 line 977 defers **individual-unit numbers and individual-unit inventory**, and §3 states a
Floor Plan "is not an individual physical unit" while a Unit Group "is not stored".

This plan does **not** lift that. `visit_units` rows are **labels on a tour** — typed by whoever went,
Hunt-scoped, exactly the category as Interest Status and `visited`. The app still has no idea what
units exist at a property, cannot enumerate them, and never learns them from a Source. §18 defers the
app *knowing*; it does not stop a member writing down which doors they walked through.

That distinction is load-bearing and belongs in the §20 entry verbatim, or the next reader will
reasonably think the deferral was violated.

### 4.2 Tables

**`visits`**
`id, hunt_id, property_id, created_by, scheduled_for timestamptz null, started_at null, ended_at null,
cancelled_at null, cancel_reason text null, template_version int not null, prefilled_from uuid null, created_at`

- **State is derived, never stored:** `cancelled_at` → cancelled; `ended_at` → completed; `started_at`
  → in progress; else planned. A status column would drift from the timestamps that actually matter.
- Guard: the `(hunt_id, property_id)` pair must have a `hunt_listings` row — same cross-scope check
  pattern as the existing cross-property Floor Plan override guard (`test_rls_matrix.py:107`).

**`visit_units`**
`id, visit_id, label text, floor_plan_id uuid null, beds smallint not null, baths numeric(3,1) not null,
display_order int, created_by, created_at`

- `unit_group_key text generated always as (beds || '-' || baths) stored` — the same
  `"{beds}-{baths}"` key `hunt_listings.pins`, `ratings`, and `comments` already use.
- `beds`/`baths` are copied from the Floor Plan when one is chosen, or typed for a described unit.
  `floor_plan_id null` = described-only (renders with the dashed "custom" outline).
- Guard: `floor_plan_id`'s property must equal the visit's property.

**`visit_template_items`** — global, seeded, read-only to clients (mirrors `criteria_catalog`)
`key, version, section_key, display_order, tier (quick|standard|thorough), kind (fact|check|question|impression),
scope (property|unit), label, help null, value_schema jsonb, is_critical bool`

- Canonical source is a Python module in the API package, seeded by migration, with a parity test
  asserting DB matches module — the same arrangement as the Catalog seeded from `shared/`.
- It cannot live in `shared/`: `shared/` stays domain-blind, and this is rental-specific content.

**`visit_custom_items`** — `id, visit_id, section_key, kind, scope, label, created_by, created_at`

**`visit_entries`** — **append-only**; the current value is the newest `(created_at, id)` per identity.
`id, visit_id, item_key text, is_custom bool, visit_unit_id uuid null, owner_user_id uuid null,
author_user_id uuid not null, value jsonb, answer_text text null, note text null, prev_entry_id uuid null, created_at`

- **Identity** = `(visit_id, item_key, visit_unit_id, owner_user_id)`.
  - `visit_unit_id null` ⇔ the item is Property-scoped (R9).
  - `owner_user_id null` ⇔ shared item (Fact/Check/Question); set ⇔ Impression, keyed per member.
  - `author_user_id` is always who wrote the row — that's the byline, and it's why shared items still
    attribute without a second table.
- Append-only buys three things at once: free history for the byline, the conflict mechanism below,
  and consistency with `extractions` / `overrides` / `floor_plan_images`.
- A `current_visit_entries` view (`security_invoker`, per §8.3's rule for current-value views)
  centralizes the newest-per-identity rule so no caller re-derives it.

**`visit_defects`**
`id, visit_id, visit_unit_id null (null = building), from_item_key null, title, note null, severity smallint
check 1..5, promised_in_writing bool default false, resolution text null, created_by, created_at, deleted_at null`

**`visit_fee_proposals`**
`id, visit_id, visit_unit_id null, hunt_listing_id, target (fee_slot|override), target_key text,
amount numeric(10,2), status (pending|accepted|rejected) default 'pending', decided_by null, decided_at null, created_by, created_at`

- `target` matters and I had it wrong initially: **fee lines upsert `fee_checklist`**
  (PK `(hunt_listing_id, fee_slot)`, in-place, with `value_state`/`entered_by`), while **base rent and
  all-in go through `overrides`** (`criterion_key` `base_rent` / `all_in_monthly`, append-only). One
  proposal table, two accept paths.
- Reject sets `status` and touches nothing else — the visit's own figure survives (R7).

---

## 5. API surface

Module `api/src/manzil_api/visits/` — `router.py` / `schemas.py` / `service.py` / `exceptions.py`,
registered in `main.py` under the `/v1` prefix, following `collaboration/` and `fees/`.

| Method | Path | Notes |
|---|---|---|
| POST | `/hunts/{hunt_id}/visits` | property + initial units in one call |
| PATCH | `/visits/{visit_id}` | start / end / cancel / reschedule (timestamp transitions) |
| DELETE | `/visits/{visit_id}` | creator or Owner (Q2) |
| POST · PATCH · DELETE | `/visits/{visit_id}/units[/{unit_id}]` | |
| **PUT** | `/visits/{visit_id}/entries` | **batch** upsert, array of entries each carrying `prev_entry_id`. This is the sync-queue endpoint and the only write path for answers. |
| POST | `/visits/{visit_id}/custom-items` | |
| POST · PATCH · DELETE | `/visits/{visit_id}/defects[/{id}]` | |
| POST | `/visits/{visit_id}/fee-proposals` | |
| PATCH | `/fee-proposals/{id}` | `{status: accepted\|rejected}`; accept performs the `fee_checklist` upsert or `overrides` insert in one transaction |

**Reads go direct-Supabase**, per `frontend/AGENTS.md`'s two-client split — they're continuously
rendered and need Realtime anyway. Mutations go through `apiClient`. Every entry above must land in
`frontend/API_ASSUMPTIONS.md` **in the same commit** (hard rule).

---

## 6. The Unit Group roll-up (precise)

Feeding the Overview **Visit** column and the drawer:

1. **Unit score** = mean across members of that member's unit-scope Impression ratings for that
   `visit_unit`. Building-scope impressions excluded (Q4).
2. **Same unit toured twice → latest visit wins.** A second showing of 4B is a correction; best-of
   across time would let a rosy first impression outrank the careful second look.
3. **Several units in one group → the best.** Same shape as the Display Floor Plan rule (§3/§9.4), so
   the table keeps its existing "best of what's here" semantics. Surfaced with a `best of N` pill
   mirroring `ScoreCell`'s existing ×N affordance rather than a new marker.
4. **A described unit matching no advertised group → no row.** Minting a Unit Group would contradict
   §3 (groups are derived from the Property's Floor Plans). It stays visible on the visit and in the
   drawer's Visits list. Showing nothing beats inventing a row.

Implementation: a `security_invoker` view `visit_unit_group_scores` keyed
`(hunt_listing_id, unit_group_key)`. A view, not a projection, until it measurably hurts — correctness
first, and `all_in_components` is the precedent for promoting it later if needed.

---

## 7. Realtime and offline

### 7.1 Realtime
Extend `frontend/src/lib/realtime.ts`: add `visits`, `visit_units`, `visit_entries`, `visit_defects`,
`visit_fee_proposals` to `HuntRealtimeTable` with invalidation keys. The existing `useHuntRealtime` in
`AppLayout` then covers the whole feature with no new subscription plumbing.

**Presence** (who's in the checklist, who's in which section) is new — Phase 2 used `postgres_changes`
only. A per-visit Presence channel, scoped to the visit route so it isn't held hunt-wide. VC-5.

### 7.2 Local-first and conflicts (R6)
- **Persistence:** TanStack Query's paused-mutation persistence (`persistQueryClient` +
  `resumePausedMutations`) rather than a bespoke IndexedDB queue. Entry writes are already a single
  batch mutation, which is the shape that mechanism handles well.
- **Detection:** each queued write carries `prev_entry_id` — the row the author believed was current.
  On flush, if the identity's current row is no longer that row, the write still lands (nothing is
  discarded) and the fork becomes visible.
- **Surfacing:** `visit_entry_conflicts` — identities with more than one row sharing a non-null
  `prev_entry_id`. The UI shows both values with who and when; resolving writes a new row whose
  `prev_entry_id` is the chosen row, collapsing the fork. Append-only makes this natural.
- **Blast radius:** Impressions can't conflict (keyed per member) and Questions append rather than
  overwrite, so this only ever fires on a Fact or a Check.
- It reuses the **dispute checkpoint** vocabulary P3-6 already established rather than inventing a
  second conflict idiom.

---

## 8. Frontend surface

Routes (children of `/h/:huntId` in `routes/router.tsx`), plus a `Visits` item in `AppLayout`'s
`NAV_ITEMS` between Compare and Rubric:

- `visits` — list, four states, state filter
- `visits/new` — 4-step create flow
- `visits/:visitId` — the checklist

New components under `frontend/src/features/visits/`: `VisitsPage`, `VisitCreateFlow` (property search
→ plan picker → unit builder → pre-visit), `VisitChecklistPage`, `UnitSwitcher`, `ScopeBar`,
`CheckRow` (tri-state), `QuestionCard` (answer-gated), `ImpressionRating`, `TeamSplit`, `DefectLog`,
`MoneyLedger`, `VerdictSplit`, `ConflictPicker`, `PresenceBar`, `SyncBadge`, `VisitCell`.

Touching existing files: `ListingDetailDrawer` (Visits section), `CostAndFees` (proposal rows — the
two-icon exception), `OverviewTable` (Visit column), `realtime.ts`, `router.tsx`, `AppLayout`.

Mantine-first, tokens only, both themes, 44px touch targets on the tri-state control, no horizontal
page scroll — `frontend/UI_DESIGN.md` §7 checklist applies to every surface.

---

## 9. Slices

Each is independently approvable and shippable. `VC-0` must land first: DESIGN.md is authoritative for
intent, and AGENTS.md requires the §20 entry plus in-place section updates for a material design
change — writing code first would invert that.

| ID | Outcome | Depends on | Acceptance |
|---|---|---|---|
| **VC-0** | **Design ratification, docs only, no code.** §3 glossary (Visit, Visit Unit, Visit Entry + the four kinds, Visit Defect, Fee Proposal); §4.2 role rows (Q2); §8.2 tables; §8.3 RLS; **new §9.7 "Visits and the Visit Checklist"** (four kinds, scope inheritance, roll-up, conflicts, proposal lifecycle); §13.1–13.3; §18 deferrals + the §4.1 boundary note; §19 workstream entry (Q1); **§20 v3.30** + addenda. IMPLEMENTATION §3 contract subsection + §7 task rows. | Q1–Q6 answered | A reader who has not seen the mockup can derive the data model and the four kinds from DESIGN.md alone; §18's individual-unit deferral is still intact and explicitly reconciled |
| **VC-1** | Foundations: migration (`visits`, `visit_units`, `visit_template_items` seeded, `visit_custom_items`) + RLS + template module + parity test + visit/unit CRUD endpoints. No UI. | VC-0 | RLS matrix extended and green for all three roles incl. cross-hunt and cross-property denial; template parity test green; `supabase db reset` clean |
| **VC-2** | Visits tab: route, nav item, list with four states + filter, 4-step create flow, Start visit. | VC-1 | Create a visit end-to-end against the API; four states render correctly; phone + desktop, both themes |
| **VC-3** | Checklist runtime: `visit_entries` + `current_visit_entries` view, batch `PUT /entries`, section nav, the four entry-kind controls, tier dial, scope inheritance + unit switcher, verdict scope split (R10). | VC-1 | Answers persist and reload; a Property-scoped item is recorded once across units; a unit-scoped item is per unit; Question cannot be marked asked without text |
| **VC-4** | Defects + red flags: log, **check → defect promotion**, red-flag per-member tally. | VC-3 | Marking a check as a problem creates a defect carrying its unit and item key |
| **VC-4b** | *Optional (Q3):* visit photos — Storage bucket, signed-URL reads, upload, storage RLS. | VC-4 | Photo visible only to that Hunt's members; verified by a negative test |
| **VC-5** ✅ | Collaboration: realtime table wiring, per-visit Presence, member-coloured bylines, team aggregates. | VC-3 | ✅ Met 2026-07-30 in two WebKit contexts: a shared Check and a promoted defect crossed live without reload; presence appeared both directions naming the section, followed a section switch, cleared on leave and reappeared on return |
| **VC-6** ✅ | Local-first: paused-mutation persistence, sync badge, `prev_entry_id` conflict detection + picker. | VC-3 | ✅ Met 2026-07-30: an answer taken offline appears at once, counts in the badge, persists to storage and flushes on restore; a two-member offline fork surfaced both values with authors and resolved to one, clearing for both members without a reload, every branch retained |
| **VC-7** ✅ | Money: ledger prefilled from `all_in_components`, proposal creation, drawer proposal rows with ✓/✕, accept → `fee_checklist` upsert or `overrides` insert. | VC-3 | ✅ Met 2026-07-30: accepting wrote one ordinary `manual` fee row carrying a human's id, and a base-rent acceptance scoped to the walked unit's Floor Plan exactly as the drawer would; rejecting recorded the decision, wrote nothing, and left the Visit's own figure intact; deciding follows the Override permission in RLS, the API and the UI |
| **VC-8** ✅ | Surfacing: `visit_unit_group_scores` view, Overview Visit column, drawer Visits section. | VC-3 | ✅ Met 2026-07-30, all four §6 rules verified against a real database and in the browser: per-member-then-across averaging (4.0, not 3.67), latest tour replacing an earlier one, best door representing its group with a ×N affordance, and a described unit matching no advertised group showing no row while staying visible in the drawer |

**Rollback:** each slice is one migration + additive code. Down-migrations drop only that slice's
objects; no existing table is altered destructively. VC-7 is the only slice that writes to existing
tables, and it does so through the same paths a human override already uses.

---

## 10. Documentation plan

Explicitly enumerated because it's easy to under-deliver, and two of these are hard rules.

**Ratified up front in VC-0** (DESIGN.md): §3, §4.2, §8.2, §8.3, **new §9.7**, §13.1, §13.2, §13.3,
§18, §19, **§20 v3.30**. IMPLEMENTATION.md: §3 contract subsection, §7 rows + sequencing entry.

**Per-slice, same commit as the code:**
- `frontend/API_ASSUMPTIONS.md` — every endpoint and direct-Supabase read. *Hard rule:
  `frontend/AGENTS.md` requires this in the same commit as the hook change.*
- `frontend/UI_DESIGN.md` — three new patterns worth promoting to the shared language (tri-state
  Check control; **scope tag vs ownership marker** as orthogonal axes; the **proposal-row two-icon
  exception** and why it's bounded to that row) + a UI Decision Log entry.
- `IMPLEMENTATION.md` §7 — status marks (`✅`/`◐`/`⚠`) and landing notes per slice, matching the
  existing row style.

**On completion:**
- `AGENTS.md` — the "Current phase" paragraph, plus the workstream's standing (Q1).
- `docs/visit-checklist-guide.md` — new, following `docs/p3-7-vision-guide.md`: the template item
  catalog, the four kinds, scope rules, the roll-up, and the conflict model.
- `docs/apartment-tour-checklist.md` — keep as the human-readable companion; note that
  `visit_template_items` is generated from the Python module and this doc is its prose form, so the
  two must be changed together.

**§18 additions:** Rubric-Criterion → check/question generation (R4, explicitly deferred);
hunt-wide recurring custom items (Q6); visit photos if Q3 defers them; visit notifications (folds into
the already-deferred P3-22); and the §4.1 clarification that unit *inventory* stays deferred while
visit unit *labels* are Hunt opinion.

---

## 11. Testing

- **API:** per-module tests as in `api/tests/test_fees_router.py`; `test_rls_matrix.py` extended with
  visit rows across Owner/Curator/Member, cross-hunt denial, cross-property Floor Plan denial, and
  fee-proposal accept permission.
- **DB:** template parity test; `current_visit_entries` newest-per-identity test; conflict-view test;
  roll-up view tests for all four §6 rules.
- **Frontend:** Vitest + Testing Library in flat `frontend/tests/`, behaviour through roles and
  accessible names. Pure logic unit-tested at boundaries: scope resolution, tier filtering, roll-up
  math, conflict detection, state derivation. No snapshot tests.
- **Visual:** phone (375/390) and desktop, light and dark, keyboard-checked — per UI_DESIGN §6.
- **No LLM anywhere in this feature**, so no fixtures or bench work. Worth stating: this is the first
  substantial subsystem with no pipeline surface at all.

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| **Local-first is the highest-risk slice.** Losing twenty minutes of tour notes would end use of the feature. | VC-6 is isolated and late; VC-3 works online-only. Persistence uses TanStack Query's own mechanism, not bespoke storage. Nothing is ever discarded on conflict. |
| **Template churn invalidates completed visits.** | `template_version` frozen per visit (Q5). |
| **§18 misreading.** A future reader sees `visit_units` and concludes unit inventory shipped. | The boundary goes in §20 and §9.7 in the ruling's own words, not just in this plan. |
| **Scope drift into an inspection app.** ~160 template items is already a lot to fill. | The tier dial is the pressure valve; nothing new gets added to the template without a §20 entry. |
| **Two-icon exception spreading.** | Bounded in UI_DESIGN to proposal rows, with the reason recorded, so the next surface can't cite it as precedent. |
