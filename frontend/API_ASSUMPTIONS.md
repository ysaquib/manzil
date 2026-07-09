# Frontend API & Data Assumptions (living document)

Every endpoint and direct-Supabase read the frontend assumes exists. Update this file **in the
same commit** as any data-hook change (rule: `frontend/AGENTS.md`). Reconcile against the backend
when P1-1/P1-5/P1-7/P1-8 land, then regenerate types (`pnpm gen:api-types`).

Legend — **Status**: `stub` = route declared, handler raises NotImplementedYet · `missing` = not
declared at all · `implemented` = working · `no table` = table not yet in a migration.
**Shape**: `generated` = `src/lib/generated/api.d.ts` · `hand-typed` = local interface mirroring
`shared/src/manzil_shared/models.py`.

## API calls (via `apiClient`)

| Method & path | Hook (file) | Shape | Backing task | Status |
|---|---|---|---|---|
| `POST /v1/hunts` | `useCreateHunt` (`features/hunts/api.ts`) | generated `HuntCreate`/`HuntResponse` | P1-5 | stub |
| `PATCH /v1/hunts/{id}` | `usePatchHunt` (`features/hunts/api.ts`) | generated `HuntUpdate` | P1-5 | stub |
| `PATCH /v1/hunts/{id}/settings` | `usePatchHuntSettings` (`features/hunts/api.ts`) | generated `HuntSettingsPatch` | P1-5 | stub |
| `PUT /v1/hunts/{id}/rubric` | `usePutRubric` (`features/rubric/api.ts`) | **hand-typed** — see conflict #1 | P1-5 | stub (schema conflict) |
| `POST /v1/hunts/{id}/listings` | `useCreateListing` (`features/listings/api.ts`) | generated `ListingCreate`/`ListingResponse` | P1-7 | stub |
| `DELETE /v1/listings/{id}` | `useDeleteListing` (`features/listings/api.ts`) | generated (204) | P1-7 | stub |
| `PATCH /v1/listings/{id}/pins` | `usePatchPins` (`features/listings/api.ts`) | generated `PinsPatch` | P1-11 mini-endpoint | stub |
| `GET /v1/hunts/{id}/jobs?state=…` | `useActiveJobs` (`features/jobs/api.ts`) — the one polled read, 3s | hand-typed `Job` — see conflict #2 | P1-7 / P1-13 | stub (missing field) |
| `POST /v1/jobs/{id}/cancel` | `useCancelJob` (`features/jobs/api.ts`) | generated `JobResponse` | P1-7 | stub |
| `POST /v1/jobs/{id}/retry` | `useRetryJob` (`features/jobs/api.ts`) | generated `JobResponse` | P1-7 | stub |
| `POST /v1/jobs/{id}/checkpoint` | `useAnswerCheckpoint` (`features/jobs/api.ts`) | generated `CheckpointAnswer` | P1-7 | stub |
| `POST /v1/listings/{id}/overrides` | `useCreateOverride` (`features/listings/api.ts`) | generated `OverrideCreate`/`OverrideResponse` | P1-8 | stub |
| `PUT /v1/listings/{id}/fees/{slot}` | `useUpsertFee` (`features/listings/api.ts`) | generated `FeeEntryUpsert`/`FeeEntryResponse` | P1-8 | stub |

## Direct Supabase reads (via `supabase-js`, RLS-guarded from P2-1)

| Table(s) | Hook (file) | Shape | Status |
|---|---|---|---|
| `hunts` | `useHunts`, `useHunt` (`features/hunts/api.ts`) | hand-typed `Hunt` | no table (P1-1) |
| `hunt_listings` + embedded `properties`, `floor_plans`, `scores` | `useListings` (`features/listings/api.ts`) | hand-typed | no table (P1-1); `properties`/`floor_plans` exist (0001) |
| `overrides` for one listing | `useOverrides` (`features/listings/api.ts`) | hand-typed | no table (P1-1) |
| `fee_checklist` for one listing | `useFees` (`features/listings/api.ts`) | hand-typed | no table (P1-1) |
| `extractions` latest-per-criterion for a property | `useExtractions` (`features/listings/api.ts`) | hand-typed | table exists (0001) |
| `rubric_criteria` | `useRubric` (`features/rubric/api.ts`) | hand-typed `RubricCriterion` | no table (P1-1) |
| `criteria_catalog` | `useCatalog` (`features/rubric/api.ts`) | hand-typed `CatalogEntry` | table exists (0001) + seed |

## Known contract conflicts (flagged per AGENTS.md; frontend follows DESIGN.md)

1. **RubricOption shape.** `api/src/manzil_api/rubric/schemas.py` defines
   `{value, delta>=0, label, is_bonus}`; DESIGN §8.2 pins
   `{match: {op, value}, delta, dealbreaker_set_score}` (negative deltas legal, dealbreakers
   option-level). The API shape cannot express dealbreakers or negative deltas, which P1-12
   requires. **Decision (2026-07-08, Yusuf): frontend builds and saves the DESIGN §8.2 pinned
   shape; the API schema must be corrected when P1-5 implements the handlers.**
2. **Checkpoint prompt.** `JobResponse` omits `jobs.payload`, so a `waiting_user` job carries no
   `{question, options}` for the Tasks tab to render. **Decision (2026-07-08, Yusuf): frontend
   types `Job.checkpoint?: CheckpointPrompt | null` and renders answer buttons only when present;
   P1-7 must add the parked checkpoint prompt to `JobResponse`.**

## Not assumed (deliberately)

No `GET /v1/catalog` — the wizard reads `criteria_catalog` directly (global table, migration
0001). No Realtime (P2-4), no History-tab job events read (P2-6), no comments/ratings (P2).
