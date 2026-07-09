# Frontend API & Data Assumptions (living document)

Every endpoint and direct-Supabase read the frontend assumes exists. Update this file **in the
same commit** as any data-hook change (rule: `frontend/AGENTS.md`). Regenerate types after backend
changes (`pnpm gen:api-types`).

Legend — **Status**: `stub` = route declared, handler raises NotImplementedYet · `missing` = not
declared at all · `implemented` = working · `no table` = table not yet in a migration.
**Shape**: `generated` = `src/lib/generated/api.d.ts` · `hand-typed` = local interface mirroring
`shared/src/manzil_shared/models.py`.

## API calls (via `apiClient`)

| Method & path | Hook (file) | Shape | Backing task | Status |
|---|---|---|---|---|
| `POST /v1/hunts` | `useCreateHunt` (`features/hunts/api.ts`) | generated `HuntCreate`/`HuntResponse` | P1-5 | implemented |
| `PATCH /v1/hunts/{id}` | `usePatchHunt` (`features/hunts/api.ts`) | generated `HuntUpdate` | P1-5 | implemented |
| `PATCH /v1/hunts/{id}/settings` | `usePatchHuntSettings` (`features/hunts/api.ts`) | generated `HuntSettingsPatch` | P1-5 | implemented |
| `PUT /v1/hunts/{id}/rubric` | `usePutRubric` (`features/rubric/api.ts`) | generated (shared §8.2 shape) | P1-5 | implemented |
| `POST /v1/hunts/{id}/listings` | `useCreateListing` (`features/listings/api.ts`) | generated `ListingCreate`/`ListingResponse` | P1-7 | implemented |
| `DELETE /v1/listings/{id}` | `useDeleteListing` (`features/listings/api.ts`) | generated (204) | P1-7 | implemented |
| `PATCH /v1/listings/{id}/pins` | `usePatchPins` (`features/listings/api.ts`) | generated `PinsPatch` | P1-11 mini-endpoint | implemented |
| `GET /v1/hunts/{id}/jobs?state=…` | `useActiveJobs` (`features/jobs/api.ts`) — the one polled read, 3s | generated `JobResponse` + optional `checkpoint` | P1-7 / P1-13 | implemented |
| `POST /v1/jobs/{id}/cancel` | `useCancelJob` (`features/jobs/api.ts`) | generated `JobResponse` | P1-7 | implemented |
| `POST /v1/jobs/{id}/retry` | `useRetryJob` (`features/jobs/api.ts`) | generated `JobResponse` | P1-7 | implemented |
| `POST /v1/jobs/{id}/checkpoint` | `useAnswerCheckpoint` (`features/jobs/api.ts`) | generated `CheckpointAnswer` | P1-7 | implemented |
| `POST /v1/listings/{id}/overrides` | `useCreateOverride` (`features/listings/api.ts`) | generated `OverrideCreate`/`OverrideResponse` | P1-8 | implemented |
| `PUT /v1/listings/{id}/fees/{slot}` | `useUpsertFee` (`features/listings/api.ts`) | generated `FeeEntryUpsert`/`FeeEntryResponse` | P1-8 | implemented |

## Direct Supabase reads (via `supabase-js`, RLS-guarded from P2-1)

| Table(s) | Hook (file) | Shape | Status |
|---|---|---|---|
| `hunts` | `useHunts`, `useHunt` (`features/hunts/api.ts`) | hand-typed `Hunt` (incl. `created_at`) | exists (0002; `created_at` 0003) |
| `hunt_listings` + embedded `properties`, `floor_plans`, `scores` | `useListings` (`features/listings/api.ts`) | hand-typed | exists (0001 + 0002) |
| `overrides` for one listing | `useOverrides` (`features/listings/api.ts`) | hand-typed | exists (0002) |
| `fee_checklist` for one listing | `useFees` (`features/listings/api.ts`) | hand-typed | exists (0002) |
| `extractions` latest-per-criterion for a property | `useExtractions` (`features/listings/api.ts`) | hand-typed | table exists (0001) |
| `rubric_criteria` | `useRubric` (`features/rubric/api.ts`) | hand-typed `RubricCriterion` | exists (0002) |
| `criteria_catalog` | `useCatalog` (`features/rubric/api.ts`) | hand-typed `CatalogEntry` | table exists (0001) + seed |

## Resolved contract conflicts (2026-07-08 decisions, fixed 2026-07-09)

1. **RubricOption shape** — resolved: API imports shared `{match, delta, dealbreaker_set_score}`.
2. **Checkpoint prompt** — resolved: `JobResponse.checkpoint` populated when `state=waiting_user`.
3. **`hunts.created_at`** — resolved (migration 0003): column added so `useHunts` can order
   newest-first; `HuntResponse.created_at` already exposed it. See DESIGN §20 (2026-07-09).
4. **`Score`/`FeeEntry` had no `id`** — resolved: `scores` and `fee_checklist` use composite PKs
   (no `id` column); the spurious hand-typed `id` fields were removed to match the DB.

## Not assumed (deliberately)

No `GET /v1/catalog` — the wizard reads `criteria_catalog` directly (global table, migration
0001). No Realtime (P2-4), no History-tab job events read (P2-6), no comments/ratings (P2).
