# Feature suggestions (2026-07-19)

Brainstormed alongside the Compare view + hunt-wide filters work. **This is an
idea parking lot, not a commitment** — R10 (scope creep) is the project's
named killer, and several entries below are already in DESIGN §18's deferred
list (marked, with the rule: never implement without pulling them in
deliberately via a §20 decision).

Priority = judgment across importance to the actual hunt, usefulness per unit
of effort, and feasibility on the existing substrate. **P1** = worth pulling
into a wave soon · **P2** = worth doing when adjacent code is open · **P3** =
parked until reality demands it.

## Major features

| # | Priority | Suggestion | Notes on value / feasibility |
|---|---|---|---|
| M1 | P1 | **Map view** — a `/h/:huntId/map` (or Overview toggle) plotting listings as score-colored pins; click opens the detail drawer; optional commute-target overlays | Location is *the* un-tabular decision axis and every property already has `lat`/`lng` from DEDUPE's geocode. Needs a map tile dependency (MapLibre + free tiles keeps NFR5's new-moving-part rule honest). High value, moderate effort |
| M2 | P1 | **Net-effective cost over the lease term** — a per-listing "total cost of a 12-month stay": rent × term + one-time fees (already extracted) − concessions, shown beside all-in monthly | The §9.5 composition answers "per month"; renters actually sign a *term*. One-time fees and household math already exist; concessions need M3. Mostly display arithmetic — cheap and honest |
| M3 | P1 | **Concession extraction** ("6 weeks free", "$500 off first month") as an EXTRACT block feeding M2 and a badge | Concessions are how buildings hide real price differences. Optional-with-default block (no prompt bump, same pattern as `one_time_fees`); needs bench labels for the new field |
| M4 | P2 | **Price history + drop badges** — floor-plan rent tracked across refreshes; sparkline in the drawer, "↓ $75" badge on the row | Refreshes already upsert `floor_plans` on a stable key, so history just needs an append-only `floor_plan_price_events` (or reuse of extractions' append-only pattern). Real value arrives only once P3-12 refresh loops run routinely — sequence after it |
| M5 | P2 | **Tour workflow** — per-unit-group tour date/time, a mobile "visit mode" checklist (questions to ask, fees to confirm → writes fee-checklist slots), post-visit rating prompt | The gap between "interested" and "applied" is where a real hunt lives. Builds on `listing_unit_group_states` + fee checklist. Scope carefully: a date field + checklist page, not a calendar-integration project |
| M6 | P2 | **Compare v2: decision aids** — highlight best value per row, pin one column as baseline (diffs shown relative to it), copy-as-Markdown summary for sharing | Cheap on the shipped transposed table; best-per-row needs per-row polarity (lower rent good, higher score good) — encode next to the row definitions |
| M7 | P2 | **Hunt activity feed** — chronological "who did what" (submissions, status changes, overrides, comments) on the hunt switcher or a drawer tab | Most data already exists (`job_events`, appended overrides/comments, `updated_by` columns); a read-model union view + one page. Collaboration glue for the two-member hunt |
| M8 | P3 | **Automated discovery / alerts** — saved search criteria → agent finds new listings | **DESIGN §18 deferred.** Also the census showed hostile aggregators own search surfaces; DISCOVER (P3-5) must land first regardless |
| M9 | P3 | **Push/email notifications** (checkpoint asked, score changed, price drop) | **DESIGN §18 deferred.** Worth revisiting once checkpoints auto-resume (P3-11) proves insufficient — a missed checkpoint currently self-heals in 24 h by design |
| M10 | P3 | **Per-member weighted rubrics** | **DESIGN §18 deferred.** The §20 record already rejected it once; two-member hunts resolve disagreement in comments faster than in math |
| M11 | P3 | **Application tracker** — documents, deadlines, per-application fees paid, outcome per unit group | Interest statuses already model outcomes; the rest is a checklist product of its own. Park until the hunt reaches application volume that hurts |
| M12 | P3 | **Public read-only hunt share / CSV export** | **DESIGN §18 deferred** (both). CSV is trivially satisfiable ad-hoc via Supabase if ever needed pre-feature |

## Minor features

| # | Priority | Suggestion | Notes |
|---|---|---|---|
| m1 | P1 | **Free-text search** in the filter bar (property name / address substring) | One predicate + one input on the shipped registry; the first thing anyone reaches for at 30+ listings |
| m2 | P1 | **More sort keys** — all-in cost, availability date, recently added | `sortValue` is a pure switch; all three values already sit on the row |
| m3 | P1 | **Duplicate-submission pre-check** — warn before enqueueing a URL whose property already exists in the hunt | DEDUPE merges eventually, but a submit-time `property_sources.url` lookup saves a whole pipeline run and a checkpoint |
| m4 | P2 | **Named filter presets** — save current filters as a chip ("2bd under $2k"), personal by default; publishing one is just the shipped Apply-hunt-wide | Serialization + sanitize already exist; a localStorage list + chips row |
| m5 | P2 | **Keyboard navigation** — ↑/↓ row focus, Enter opens drawer, ←/→ pages the drawer between rows | Table is plain Mantine; needs focus management only. Pairs with the lightbox's existing keyboard nav |
| m6 | P2 | **Bulk actions** — multi-select rows → set status / archive / send to compare | Curation at scale; checkbox column + one menu. RLS already vets each write |
| m7 | P2 | **Archived-listings view** — a filter/tab exposing `status = archived` rows with restore | The column exists; today archived rows are simply invisible |
| m8 | P2 | **Score-history sparkline** in the drawer (per rubric version) | `scores` keeps every rubric_version row; tiny chart, no new data |
| m9 | P2 | **"New since your last visit" dot** per row (localStorage last-seen timestamp per hunt) | Cheap orientation aid for the second member; no server state |
| m10 | P2 | **Per-row refresh action** once P3-12 lands ("Refresh now" in the row menu) | The jobs plumbing exists; gate on P3-12's TTL/hash logic so a manual refresh is cheap by construction |
| m11 | P3 | **Column visibility picker** on the Overview | Waits until the column set actually outgrows one screen; density just shipped for the same pressure |
| m12 | P3 | **Compare column reordering** (drag) | Cosmetic until COMPARE_LIMIT grows past 3 |
| m13 | P3 | **Locale/currency formatting setting** | Single-market tool today (SE Michigan, USD); YAGNI until that changes |
| m14 | P3 | **Onboarding checklist card** for a brand-new hunt (submit first URL → set rubric → invite partner) | Nice polish; the empty states already point the way, and there are exactly two users |

## Review appendix — second pass (same day)

Re-reading the list against DESIGN's constraints and the actual state of the
hunt, with corrections:

1. **M1 (map) stays the top major suggestion, with one honesty note.** It's
   the only entry that adds a genuinely new decision axis rather than
   polishing an existing one. But it also adds the project's first mapping
   dependency — NFR5 says that cost is real. Recommendation stands: MapLibre
   + a free raster tile source, Overview-toggle rather than a new route, and
   no clustering/commute overlays in v1.
2. **M2/M3 should be treated as one unit, and they're cheaper than they
   look.** Net-effective math without concession extraction is misleading
   (it would systematically favor buildings that price honestly), so don't
   ship M2 alone. Together they follow the exact `one_time_fees` playbook
   from 2.0.62 — block, projection, display line — plus the owed bench-label
   pass. Upgrade the pair's standing: strongest candidate for the next
   Yusuf-directed UI/pipeline batch after P3-5.
3. **M4 (price history) was over-prioritized in the first pass.** Until
   P3-12 ships, refreshes are manual and rare, so the "history" would be two
   points. Confirmed P2 but explicitly **sequenced after P3-12**, and the
   schema should be decided when the refresh cadence is known — resist
   creating the table early.
4. **M5 (tour workflow) is the highest scope-creep risk on the list** — it
   wants to become a product. If pulled in, cap it at: one nullable
   `tour_at` on `listing_unit_group_states`, one static checklist page, no
   calendar integrations, no reminders (that's M9's deferred territory).
5. **M7 (activity feed) demoted in spirit.** With two members and Realtime
   already syncing state, the feed answers questions nobody is asking yet.
   Keep at P2 only because the read-model is nearly free; drop to P3 if the
   union query turns out to need new indexes.
6. **m3 (duplicate pre-check) may be the best effort-to-value ratio in the
   whole file** — one indexed lookup that saves an entire pipeline run and a
   human checkpoint. If only one minor item gets picked up, pick this.
7. **m9 (new-since-last-visit) has a subtle flaw as specified:** localStorage
   means the dot lies across devices. Acceptable for v1 (the compare set
   accepts the same trade-off, per §20 2026-07-19), but say so in the UI
   copy ("new on this device") or move the timestamp to `user_profiles` when
   it graduates.
8. **Deliberately absent from this list** (checked against §18 to avoid
   re-suggesting the rejected): Yelp-tier ratings sources, screenshot-based
   extraction, zip-level utility baselines, off-market detection beyond
   stale badging, buy-domain support. All remain exactly where §18 left
   them.
9. **Custom criteria in Compare (from today's request):** no follow-up item
   needed — the shipped criteria section iterates the score-breakdown union,
   so P3-10's custom criteria appear automatically. Verified against the
   implementation, not just intended.
10. **Meta-recommendation:** nothing in this file should jump ahead of P3-5
    (DISCOVER) or the owed bench re-run. The pipeline's spine outranks every
    suggestion here, including the good ones.
