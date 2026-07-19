# Compare view + hunt-wide filters — design (2026-07-19)

Approved scope (Yusuf, 2026-07-19): the compare-view half of P3-13, hunt-wide
shared filters, and a more comprehensive filter set. Decisions below were
confirmed interactively: compare set is **personal per browser**, hunt-wide
filters are **Owner + Curator** published and **seed-on-open** (members freely
deviate locally).

## 1. Compare view (P3-13, compare half)

**Entity compared:** the Unit Group row — `{ hunt_listing_id, unit_group_key }` —
exactly what an Overview row is. This refines DESIGN §13.1's "2–4 listing
side-by-side" (recorded in §20): comparing listings would collapse a 2bd/2ba
against a 1bd/1ba of the same property into one column, which is not how
decisions are made.

**Selection set:** personal, per browser. localStorage key
`manzil:compare:<huntId>`, value: array of `{ listingId, groupKey }`. Capacity
is `COMPARE_LIMIT = 3`, a named constant in `compareSet.ts` — raising it later
is a one-line change (DESIGN said 2–4; 3 chosen for now, §20 entry).
Entries whose listing or group no longer exists are pruned silently when the
page loads (set-stability over error noise).

**Entry points:**
- Overview row actions menu: "Send to Compare" toggles to "Remove from
  Compare" when the row is in the set; disabled with a tooltip when the set is
  full and the row isn't in it.
- App nav: "Compare" link with a count badge when non-empty.

**Page layout** (`/h/:huntId/compare`, route already reserved in §13.1):
transposed table — attribute labels in a sticky first column, one column per
compared Unit Group (≤3), horizontal scroll inside the table container.
Sections top to bottom:

1. **Photos** — `PropertyImageCarousel` per column (existing component +
   `usePropertyImages`; ≤3 queries).
2. **Header facts** — property name + address (per-column remove button and a
   link back to the Overview detail), score (score-scale coloring), unit
   group (beds/baths), rent range, sqft range, all-in monthly (estimated
   portion visually distinct, reusing `AllInCost` semantics), deposit,
   availability, interest status, visited.
3. **Monthly cost composition** — rows from `all_in_components.components`
   (union of component labels across columns), each cell tagged
   actual/estimated/unknown. This is where pet rent, parking fees, and
   utilities land — no bespoke per-fee rows.
4. **Criteria** — union of `displayScore.breakdown.criteria` keys across
   columns, ordered by the first column's breakdown order: label, effective
   value (via `displayValue`), points delta chip. Because this iterates the
   breakdown, **custom criteria appear automatically once P3-10 lands** (noted
   in IMPLEMENTATION as a P3-10 acceptance nicety; no follow-up code needed
   here).

**Controls:** Clear (empties the set), row density menu (reuse
`TableDensityMenu`), persisted at `manzil:compare-density`. Overview density is
already persisted (`manzil:overview-density`) — no change needed there.

**Non-goals now:** mobile bottom-sheet polish (stays in P3-13's remainder),
shared/server-side compare sets, pinning columns, diff highlighting
(suggestion file candidate).

## 2. Hunt-wide filters

**Persistence:** new per-hunt table (NOT `hunts.settings` — that shape is
pinned in §8.2 and its keys are scoring inputs with rescore-triggering edit
semantics; filters are view state):

```sql
hunt_shared_filters (
  hunt_id uuid primary key references hunts(id) on delete cascade,
  filters jsonb not null,
  updated_by uuid not null references auth.users(id),
  updated_at timestamptz not null default now()
)
```

RLS: SELECT for hunt members; INSERT/UPDATE/DELETE for Owner + Curator via
`private.member_role(hunt_id)` (matches the curation-write precedent of
`listing_unit_group_states`, not the Owner-only settings precedent —
confirmed choice). Written directly from the frontend under the user JWT.

**Semantics — seed on open:** when the Overview mounts and shared filters
exist, they become the initial local filter state. Members then deviate
freely; nothing re-applies mid-session. The filter bar shows a badge:
"Hunt-wide filters" while local state deep-equals the shared set, switching to
"Hunt-wide (modified)" once it deviates, with:
- **Apply hunt-wide** (Owner/Curator only): upserts current local filters.
- **Reset to hunt-wide**: local state ← shared set (any member).
- Clearing all local filters stays local; it never deletes the shared set.
  An Owner/Curator clears the hunt-wide set by applying empty filters
  (stored as the default state; badge disappears when shared set is default).

**Forward compatibility:** `filters` stores an `OverviewFilterState`-shaped
object. On read, unknown keys are dropped and missing keys defaulted, so old
rows survive filter-set growth.

**Realtime:** not added to the §13.3 channel list — seed-on-open is
deliberately not live-synced. TanStack invalidation on publish covers the
publisher; others pick it up next visit.

## 3. New filters (predicate registry additions)

All operate on data the Overview already loads; unknown values always pass
(consistent with existing predicates — pending/unknown is not a verdict):

| Filter | Input | Source |
|---|---|---|
| Laundry | MultiSelect (in_unit, hookups, on_site, none) | breakdown criterion `in_unit_laundry` value |
| Parking | MultiSelect (garage…none) | breakdown `parking` |
| Pets policy | MultiSelect | breakdown `pets_policy` |
| Cooling | MultiSelect | breakdown `cooling` |
| Dishwasher | yes/no Select | breakdown `dishwasher` |
| Max all-in | NumberInput | `allInValue(row)` |
| Available by | DateInput (ISO) | earliest plan `availability_date` in group; a group with any plan available on/before the date passes |

Limitation, documented: breakdown values exist only for rubric-enabled
criteria; a disabled criterion filters as unknown (passes). Acceptable — the
alternative (bulk extraction loading) buys little and costs a query pattern.

## 4. Documentation deltas

- DESIGN §8.2: add `hunt_shared_filters` to per-hunt tables.
- DESIGN §13.2: extend the filter-bar sentence (new filters + hunt-wide
  badge/publish); add a Compare view paragraph.
- DESIGN §20 (2026-07-19): one entry for the compare refinement (unit-group
  columns, personal set, limit-3 constant), one for hunt-wide filters
  (table, Owner+Curator, seed-on-open).
- IMPLEMENTATION: changelog entries; P3-13 → ◐ (compare landed, mobile
  polish remains); new task row for shared filters marked landed.

## 5. Testing

- `overviewRows` predicate/pill unit tests for every new filter.
- `compareSet` hook logic (add/remove/toggle/cap/prune) as pure functions +
  unit tests.
- Shared-filters serialization guard test (unknown keys dropped, missing
  defaulted).
- ComparePage render test with fixture rows (columns, union rows, clear).
- Migration exercised via `supabase db reset` locally; RLS matrix relies on
  the `private.member_role` pattern already covered by P2 tests.
