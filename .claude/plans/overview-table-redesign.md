# Overview table redesign — implementation plan

**Design draft:** `claude.ai/code/artifact/6f575fce-17cb-420c-92b6-19bc7316ae11` (approved 2026-07-26)
**Scope:** presentation only. No contract, scoring, or API-shape change. `overviewRows.ts` — the tested pure
row/sort/filter logic — is not touched except to read from it.

## Why

Measured before: at 390 px the page is **701 px wide** (`document.scrollWidth`), violating UI_DESIGN §5
"no horizontal page scroll, ever". The table also spends its width on a flat one-fact-per-column spread
with a dead gap at the right, hides curation state behind a 140 px `Select` in every row, squeezes five
member ratings into `maw={16}`, and offers no indication that a row is still being fetched or has failed.

## Slices

Each slice ends green: `npx vitest run`, `npx tsc --noEmit`, `npx eslint src tests`.

### S1 — pure helpers + tests
- `features/listings/interestStatus.ts` — `interestTone(status)` → Mantine colour **name**
  (cyan/indigo/yellow/green/red/gray, never a hex, per UI_DESIGN §2) and `interestLabel(status)` → Title Case.
  All ten `INTEREST_STATUSES` mapped; grape and dusty brick excluded (manual / danger).
- `features/listings/rowState.ts` — `rowPipelineState(row, jobsByListing)` → `"working" | "failed" | null`
  plus stage/error text. **Rule:** an active job (`queued|running|waiting_user`) → working; latest job
  `failed` → failed. The *blanked placeholder layout* applies only when the row has no scored group
  (`row.group === null`); a scored row keeps its data and only swaps its marker.
- Tests: `tests/interestStatus.test.ts`, `tests/rowState.test.ts`.

### S2 — shared presentational pieces
- `OverviewTable.module.css` (currently 2 lines): sticky column offsets, conditional scroll shadow,
  grouped header band, group rules, marker slot, spinner (honouring `prefers-reduced-motion`).
- `StatusChip.tsx` — Title Case chip, tone from `interestTone`, opens the existing status menu.
- `VisitedChip.tsx` — labelled `✓ Visited`, replacing the unlabelled tick.
- `RowMarker.tsx` — one slot, priority-ordered: spinner → failure triangle → interest dot → hollow ring.
- `RatingSummary.tsx` — mono average + star, one dot per member in `memberColor`, comment count
  (hidden at zero). Replaces the crushed `Rating` widgets in `RatingDots`.

### S3 — desktop table
- Column order: select · **score** · property(+marker, +`⋮`) · unit · sqft · **all-in** · rent · deposit ·
  available · added · city · status · people.
- Two header rows: group band (`FIT · IDENTITY · UNIT · MONEY · TIMING · PLACE · CURATION · PEOPLE`) +
  labels. Header reads **"All-In Monthly"**, not "All-in / mo".
- `overflow-x` scroll container; sticky select/score/property; `⋮` moves *inside* the property cell
  (no right-hand rail, no extra column).
- Scroll shadow toggles on `scrollLeft > 0` only.
- Working/failed rows: marker, stage or error line, `View task ›` / `See history ›`, em-dash cells.

### S4 — mobile row list
- `OverviewRowList.tsx`: collapsed row = score · marker · property · unit · **all-in**; chevron (borderless)
  expands in place; tapping the row opens the drawer.
- Expanded: 3×2 stat tiles (rent / sqft / available / deposit / city / added), then Status + People tiles,
  then Listing · Compare · Archive actions.
- Working/failed rows carry no chevron; the whole card routes to Tasks.

### S5 — page + toolbar
- Search and Filters share an edge; view options (Active/Archived, columns, density) in one bordered cluster.
- Submit-URL row stays inline and always visible (frontend/AGENTS.md).
- `useMediaQuery` picks table vs row list at `sm`. **No horizontal page scroll at 390 px** is the acceptance.

### S6 — filter panel
- Seven labelled sections; paired bounds share a row (`$1,200 — $1,800`); controlled vocabularies
  (availability, status, visited, laundry, parking, pets, cooling, dishwasher) become Title Case toggle chips.
- Keep: removable active-filter pills, visible/filtered-out count, hunt-wide publish for owner/curator.

### S7 — Tasks hand-off
- `TasksPage` tab becomes URL-driven (`?tab=active|history`) so the row links can target History.

### S8 — docs + verification
- `frontend/UI_DESIGN.md` decision-log entry.
- Re-measure page width at 390 px; screenshot desktop + mobile in both schemes.
- Fresh-context `verifier` pass before reporting done.

## Risks

- **Sticky + `border-collapse: separate`** is required for sticky cells to keep their background; row
  borders must move to `td` rules.
- **Job→listing join** relies on `JobResponse.hunt_listing_id`; a listing with no job at all must fall
  through to today's "Pending" behaviour, not to "failed".
- `tests/DrawerImageGallery.test.tsx` has **one failure that pre-dates this work** (verified at `HEAD`
  in a detached worktree). Any *other* failure is mine.
