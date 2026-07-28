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
| `PATCH /v1/hunts/{id}/settings` | `usePatchHuntSettings` (`features/hunts/api.ts`) | generated `HuntSettingsPatch`; resolved client contract includes independent `min_confidence` (medium default) and `min_vision_confidence` (low default) | P1-5 / DESIGN v3.20 | implemented |
| `PUT /v1/hunts/{id}/rubric` | `usePutRubric` (`features/rubric/api.ts`) | generated (shared §8.2 shape) | P1-5 | implemented |
| `POST /v1/hunts/{id}/listings` | `useCreateListing` (`features/listings/api.ts`) | generated `ListingCreate`/`ListingResponse` | P1-7 | implemented |
| `DELETE /v1/listings/{id}` | *(no hook — superseded in the UI by the status patch below; endpoint kept)* | generated (204) | P1-7 | implemented |
| `PATCH /v1/listings/{id}/status` | `usePatchListingStatus` (`features/listings/api.ts`) | generated `ListingStatusPatch`/`ListingResponse`; Owner-only archive/restore | m6/m7 (2026-07-19) | implemented |
| `PATCH /v1/listings/{id}/pins` | `usePatchPins` (`features/listings/api.ts`) | generated `PinsPatch` | P1-11 mini-endpoint | implemented |
| `PATCH /v1/listings/{id}/source-policy` | `usePatchSourcePolicy` (`features/listings/api.ts`) | generated `SourcePolicyPatch`/`ListingResponse`; Owner or submitter; relaxing atomically queues a `refresh(scope=discover)` Job | P3-5 | implemented |
| `PATCH /v1/listings/{id}/unit-groups/{unit_group_key}/state` | `usePatchUnitGroupState` (`features/listings/api.ts`) | generated `UnitGroupStatePatch`/`UnitGroupStateResponse` | DESIGN v3.5 | implemented |
| `GET /v1/hunts/{id}/jobs?state=…` | `useActiveJobs` (`features/jobs/api.ts`) — the one polled read, 3s | generated `JobResponse` + optional `checkpoint`; `started_at` drives elapsed time for running jobs | P1-7 / P1-13 | implemented |

`state` accepts repeated query params (`state=queued&state=running`) **and** a single
comma-separated value (`state=queued,running,waiting_user`) — the form the Tasks tab polls.
| `POST /v1/jobs/{id}/cancel` | `useCancelJob` (`features/jobs/api.ts`) | generated `JobResponse` | P1-7 | implemented |
| `POST /v1/jobs/{id}/retry` | `useRetryJob` (`features/jobs/api.ts`) | generated `JobResponse` | P1-7 | implemented |
| `POST /v1/jobs/{id}/checkpoint` | `useAnswerCheckpoint` (`features/jobs/api.ts`) | generated `CheckpointAnswer` | P1-7 | implemented |
| `POST /v1/listings/{id}/overrides` | `useCreateOverride` (`features/listings/api.ts`) | generated `OverrideCreate`/`OverrideResponse`; true-Property, all-units, or exact Floor Plan target; API and RLS reject cross-Property Floor Plans | P1-8 / P3-SC2 | implemented |
| `PUT /v1/listings/{id}/fees/{slot}` | `useUpsertFee` (`features/listings/api.ts`) | generated `FeeEntryUpsert`/`FeeEntryResponse` | P1-8 | implemented |
| `POST /v1/listings/{id}/comments` | `useCreateComment` (`features/collaboration/api.ts`) | generated `CommentCreate`/`CommentResponse`; optional `unit_group_key` | DESIGN v3.4 | implemented |
| `PATCH /v1/comments/{id}` | `useUpdateComment` (`features/collaboration/api.ts`) | generated `CommentUpdate`/`CommentResponse`; author-only | DESIGN v3.4 | implemented |
| `DELETE /v1/comments/{id}` | `useDeleteComment` (`features/collaboration/api.ts`) | generated (204); author-only soft delete | P2-6 | implemented |
| `PUT/DELETE /v1/listings/{id}/unit-groups/{unit_group_key}/rating` | `useSetRating` (`features/collaboration/api.ts`) | generated `RatingUpsert`/`RatingResponse` | DESIGN v3.4 | implemented |
| `POST/GET /v1/hunts/{id}/invitation-links` | `useCreateInvitationLink` / `useInvitationLinks` (`features/invites/api.ts`) | generated Invitation Link shapes (`name` optional on create/response) | P2-11 | implemented |
| `PATCH/DELETE /v1/invitation-links/{id}` | `usePatchInvitationLink` / `useDeleteInvitationLink` (`features/invites/api.ts`) | generated Invitation Link shapes (`name` optional on patch) | P2-11 | implemented |
| `POST /v1/invitation-links/{token}/join` | `useJoinInvitationLink` (`features/invites/api.ts`) | generated `InvitationLinkJoined` | P2-11 | implemented |
| `PUT /v1/profile` | `/profile` (`auth/ProfilePage.tsx`) | generated `ProfileUpsert`/`ProfileResponse`; optional `default_color` is omitted by onboarding and required when explicitly sent | DESIGN §13.1 | implemented |

Invitation Link responses carry an API-configured absolute `link`, but the frontend replaces its
origin with `window.location.origin` before copying. Supabase Auth storage is origin-scoped, so a
configured `www`/apex or localhost/LAN-host mismatch must not send a signed-in user to another
origin that appears logged out.

## Direct Supabase reads (via `supabase-js`, RLS-guarded from P2-1)

| Table(s) | Hook (file) | Shape | Status |
|---|---|---|---|
| `hunts` | `useHunts`, `useHunt` (`features/hunts/api.ts`) | hand-typed `Hunt` (incl. `created_at`) | exists (0002; `created_at` 0003) |
| `hunt_listings` + embedded `properties`, current `floor_plans`, `scores` | `useListings` (`features/listings/api.ts`) | hand-typed; `properties` includes nullable `city`, `state` (USPS code), `county`, and the §12 geocode cache `lat`/`lng` (nullable — written by DEDUPE only-when-null, so a listing may legitimately have no coordinates; the §13.2 map surfaces read them); embedded Floor Plans filter `is_current = true`, with a defensive client-side retirement filter | exists (0001 incl. `lat`/`lng` + 0002; locality 20260803000000; Floor Plan lifecycle 20260801000000) |
| `hunt_listings` (`status = archived`, same embed) | `useArchivedListings` (`features/listings/api.ts`) — fetched only while the Archived view is open | hand-typed; current Floor Plans only | exists (0001 + 0002; Floor Plan lifecycle 20260801000000) |
| `current_overrides` for one listing | `useOverrides` (`features/listings/api.ts`) | hand-typed scoped target/applicability; newest row per concrete target, including null revert tombstones | exists (20260801000000) |
| `fee_checklist` for one listing | `useFees` (`features/listings/api.ts`) | hand-typed | exists (0002) |
| `current_extractions` resolved rows for a Property | `useExtractions` (`features/listings/api.ts`) | hand-typed scoped target/applicability/provenance; exact and generalized rows may coexist | exists (20260801000000) |
| `extraction_resolution_candidates` + candidate `extractions`/`property_sources` | `useResolutionCandidates` (`features/listings/api.ts`) | P3-6 resolved-to-candidate provenance; RLS follows the resolved Extraction | exists (20260801000000) |
| `rubric_criteria` | `useRubric` (`features/rubric/api.ts`) | hand-typed `RubricCriterion` | exists (0002) |
| `criteria_catalog` | `useCatalog` (`features/rubric/api.ts`) | hand-typed `CatalogEntry` | table exists (0001) + seed |
| `hunt_members` (+ `user_profiles` for display-name/color defaults) | `useMembers` (`features/collaboration/api.ts`) | hand-typed `HuntMember`, including nullable Hunt-level overrides and effective coalesced identity | exists (0002+; profile coalesce P2 + 20260729000000) |
| `user_profiles` for the current account | `useProfile` (`auth/profile.ts`) | hand-typed `UserProfile` (`default_display_name`, `default_color`) | exists (0002 + 20260729000000) |
| *(derived)* same as `useMembers` | `useCurrentMember` (`features/collaboration/api.ts`) | `HuntMember \| undefined` via session user id — no extra fetch | client-side only |
| `comments` for one Listing | `useComments` (`features/collaboration/api.ts`) | hand-typed `Comment`; nullable Unit Group scope + `edited_at` | exists (0002 + 20260724000000) |
| `ratings` for one Listing | `useRatings` (`features/collaboration/api.ts`) | hand-typed `Rating`; filtered per Unit Group by row consumers | exists (0002 + 20260724000000) |
| `listing_unit_group_states` for one Hunt | `useUnitGroupStates` (`features/listings/api.ts`) | hand-typed `UnitGroupState` | exists (20260725000000) |

## Resolved contract conflicts (2026-07-08 decisions, fixed 2026-07-09)

1. **RubricOption shape** — resolved: API imports shared `{match, delta, dealbreaker_set_score}`.
2. **Checkpoint prompt** — resolved: `JobResponse.checkpoint` populated when `state=waiting_user`.
3. **`hunts.created_at`** — resolved (migration 0003): column added so `useHunts` can order
   newest-first; `HuntResponse.created_at` already exposed it. See DESIGN §20 (2026-07-09).
4. **`Score`/`FeeEntry` had no `id`** — resolved: `scores` and `fee_checklist` use composite PKs
   (no `id` column); the spurious hand-typed `id` fields were removed to match the DB.
5. **`hunt_listings.unavailable_at`** — added (migration 0004): a listing with no available
   floor plans renders as a dimmed, null-score Overview row (distinct from pending/error).
   Exposed on `ListingResponse.unavailable_at` and read on the hand-typed `Listing`.
   `buildRows` now emits one listing-level row (`group: null`) for a plan-less listing.
6. **`jobs.hunt_id`** — added (migration 0004): `list_jobs` filters on it directly. Not read by
   the frontend (jobs are fetched via `GET /v1/hunts/{id}/jobs`). `JobResponse.started_at` was
   later exposed for the running-job elapsed timer (DESIGN §13.2).

## Not assumed (deliberately)

No `GET /v1/catalog` — the wizard reads `criteria_catalog` directly (global table, migration
0001).
