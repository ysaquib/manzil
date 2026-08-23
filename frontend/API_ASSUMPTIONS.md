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
| `PUT /v1/hunts/{id}/rubric` | `usePutRubric` (`features/rubric/api.ts`) | generated criterion-list body (shared §8.2 shape) plus CORS-exposed `X-Manzil-Backfill-Count` response header | P1-5 / P3-10 | implemented |
| `POST /v1/hunts/{id}/rubric/custom-routing` | `useClassifyCustomRouting` (`features/rubric/api.ts`) | generated `CustomRoutingRequest`/`CustomRoutingResponse`; Owner-only, one traced classification; response includes an opaque key, suggested route, reason, and whether v1 supports the route | P3-10 | implemented |
| `POST /v1/hunts/{id}/listings` | `useCreateListing` (`features/listings/api.ts`) | generated `ListingCreate`/`ListingResponse` | P1-7 | implemented |
| `GET /v1/listings/{id}/deletion-impact` | `useListingDeletionImpact` (`features/listings/api.ts`) | generated `ListingDeletionImpact`; Owner-only preflight with grouped Hunt-local counts and active-Job count | DESIGN v3.68 | implemented |
| `DELETE /v1/listings/{id}` | `usePermanentDeleteListing` (`features/listings/api.ts`) | generated `ListingPermanentDelete` / `ListingDeletionImpact`; Owner-only, archived-only, exact Property-name confirmation, active-Job refusal; global Property truth survives | DESIGN v3.68 | implemented |
| `PATCH /v1/listings/{id}/status` | `usePatchListingStatus` (`features/listings/api.ts`) | generated `ListingStatusPatch`/`ListingResponse`; Owner-only archive/restore | m6/m7 (2026-07-19) | implemented |
| `PATCH /v1/listings/{id}/pins` | `usePatchPins` (`features/listings/api.ts`) | generated `PinsPatch` | P1-11 mini-endpoint | implemented |
| `PATCH /v1/listings/{id}/source-policy` | `usePatchSourcePolicy` (`features/listings/api.ts`) | generated `SourcePolicyPatch`/`ListingResponse`; Owner or submitter; relaxing atomically queues a `refresh(scope=discover)` Job | P3-5 | implemented |
| `POST /v1/listings/{id}/refresh` | `useRefreshListing` (`features/listings/api.ts`) | generated `RefreshRequest`/`JobResponse`; omitted fields refresh every mutable class, explicit values are refresh-class tokens | P3-12 | implemented |
| `POST /v1/hunts/{id}/refresh` | *(no frontend hook yet)* | generated `RefreshRequest`/`JobResponse[]`; Owner/Curator active-Listing fan-out | P3-12 | implemented |
| `PATCH /v1/listings/{id}/unit-groups/{unit_group_key}/state` | `usePatchUnitGroupState` (`features/listings/api.ts`) | generated `UnitGroupStatePatch`/`UnitGroupStateResponse` | DESIGN v3.5 | implemented |
| `GET /v1/hunts/{id}/jobs?state=…` | `useActiveJobs` / `useJobs` (`features/jobs/api.ts`) | generated `JobResponse` + optional `checkpoint`, `checkpoint_context`, and terminal `auto_resolved_checkpoint`; `started_at` drives elapsed time for running jobs; `stage_index` (manifest cursor from `payload.run_state.cursor`) drives pipeline progress on duplicate stages | P1-7 / P1-13 / P3-11 | implemented |

`state` accepts repeated query params (`state=queued&state=running`) **and** a single
comma-separated value (`state=queued,running,waiting_user`) — the form the Tasks tab polls.
| `POST /v1/jobs/{id}/cancel` | `useCancelJob` (`features/jobs/api.ts`) | generated `JobResponse` | P1-7 | implemented |
| `POST /v1/jobs/{id}/retry` | `useRetryJob` (`features/jobs/api.ts`) | generated `JobResponse` | P1-7 | implemented |
| `POST /v1/jobs/{id}/checkpoint` | `useAnswerCheckpoint` (`features/jobs/api.ts`) | generated `CheckpointAnswer`; a parked Job resumes in place, while a terminal auto-resolved Job returns a new correction Job from the retained checkpoint snapshot | P1-7 / P3-11 | implemented |
| `POST /v1/listings/{id}/overrides` | `useCreateOverride` (`features/listings/api.ts`) | generated `OverrideCreate`/`OverrideResponse`; true-Property, all-units, or exact Floor Plan target; API and RLS reject cross-Property Floor Plans | P1-8 / P3-SC2 | implemented |
| `PUT /v1/listings/{id}/fees/{slot}` | `useUpsertFee` (`features/listings/api.ts`) | generated `FeeEntryUpsert`/`FeeEntryResponse` | P1-8 | implemented |
| `POST /v1/listings/{id}/comments` | `useCreateComment` (`features/collaboration/api.ts`) | generated `CommentCreate`/`CommentResponse`; optional `unit_group_key` | DESIGN v3.4 | implemented |
| `PATCH /v1/comments/{id}` | `useUpdateComment` (`features/collaboration/api.ts`) | generated `CommentUpdate`/`CommentResponse`; author-only | DESIGN v3.4 | implemented |
| `DELETE /v1/comments/{id}` | `useDeleteComment` (`features/collaboration/api.ts`) | generated (204); author-only soft delete | P2-6 | implemented |
| `PUT/DELETE /v1/listings/{id}/unit-groups/{unit_group_key}/rating` | `useSetRating` (`features/collaboration/api.ts`) | generated `RatingUpsert`/`RatingResponse` | DESIGN v3.4 | implemented |
| `POST/GET /v1/hunts/{id}/invitation-links` | `useCreateInvitationLink` / `useInvitationLinks` (`features/invites/api.ts`) | generated Invitation Link shapes (`name` optional on create/response) | P2-11 | implemented |
| `PATCH/DELETE /v1/invitation-links/{id}` | `usePatchInvitationLink` / `useDeleteInvitationLink` (`features/invites/api.ts`) | generated Invitation Link shapes (`name` optional on patch) | P2-11 | implemented |
| `POST /v1/invitation-links/{token}/join` | `useJoinInvitationLink` (`features/invites/api.ts`) | generated `InvitationLinkJoined` | P2-11 | implemented |
| `POST/GET /v1/hunts/{id}/invites` | `useCreateInvite` / `useInvites` (`features/invites/api.ts`) | generated `InviteCreate` / `InviteResponse`; response includes the app-owned product-mail `delivery_status`, while the copyable link remains the bare `/invite/{token}` capability. The query polls every five seconds only while any visible delivery is non-terminal, because the private delivery outbox has no browser Realtime publication | P2-5 / P3-22 | implemented |
| `POST /v1/invites/{id}/resend` | `useResendInvite` (`features/invites/api.ts`) | generated `InviteResponse`; Owner-only, reuses an active invite token and queues a new idempotent delivery only after the prior delivery is terminal; otherwise 409 `invite_delivery_not_retryable` | P3-22 | implemented |
| `PUT /v1/profile` | `/account/profile` (`auth/AccountPage.tsx`) | generated `ProfileUpsert`/`ProfileResponse`; optional `default_color` is omitted by onboarding and required when explicitly sent | DESIGN §13.1 / P3-16 | implemented |
| `GET/PUT /v1/notification-preferences` | `useAccountNotificationPreferences` / `useSaveAccountNotificationPreferences` (`features/notifications/api.ts`) | generated `AccountNotificationPreferences`; exact five-event email map, with checkpoint/run-failed on and score/comment/rating off when no row exists. Saving invalidates every cached Hunt preference because inherited effective values may have changed | P3-22 | implemented |
| `GET/PUT /v1/hunts/{id}/notification-preferences` | `useHuntNotificationPreferences` / `useSaveHuntNotificationPreferences` (`features/notifications/api.ts`) | generated `HuntNotificationPreferences` read + `HuntNotificationPreferenceUpdate` write; nullable overrides inherit account defaults per event. The API applies the exact five-key map through one transactional RPC, never five partial writes | P3-22 | implemented |
| `GET /v1/hunts/{id}/attention` | `useAttention` (`features/notifications/api.ts`) | generated `AttentionResponse`; Owner/Curator count every waiting Checkpoint in the Hunt, Member counts only submitted Listings, Demo is zero; `jobs`/`job_events` Realtime invalidates it | P3-22 | implemented |
| `POST /v1/feedback` | `useSubmitFeedback` (`features/feedback/api.ts`) | generated `FeedbackCreate`/`FeedbackResponse`. Identity is server-side (`user_id` from the bearer token, `user_agent` from the request); `route` must be a site-relative path; a `hunt_id` the caller cannot read is a 403; the per-hour cap returns 429 `feedback_rate_limited`. **No read hook exists or can exist** — `feedback` has no `SELECT` policy for anyone, so the response confirms receipt rather than echoing the row | P3-16 | implemented |

### Hunt lifecycle (DESIGN v3.77)

| Method & path | Hook (file) | Shape | Status |
|---|---|---|---|
| `GET /v1/hunts` | `useHunts` (`features/hunts/api.ts`) | membership-scoped `HuntResponse[]`, including archived and locked state; the switcher hides archived rows until requested | implemented |
| `PATCH /v1/hunts/{id}` | `usePatchHunt` (`features/hunts/api.ts`) | optional `{name, archived}` → `HuntResponse`; Owner-only, archive/restore refused while locked and cancels unfinished Jobs | implemented |
| `GET /v1/hunts/{id}/deletion-impact` | `useHuntDeletionImpact` (`features/hunts/api.ts`) | Hunt-local impact and blockers; Owner-only, archived-only | implemented |
| `DELETE /v1/hunts/{id}` | `useDeleteHunt` (`features/hunts/api.ts`) | `{confirmation_name}` → impact receipt; Owner-only, archived-only, exact-name-confirmed | implemented |

Archived/locked enforcement is database-backed for every Hunt-scoped write. The
frontend's central `useHuntAccess` capability projection is UX, not authority.

### Admin Hunt lifecycle (DESIGN v3.77)

| Method & path | Hook (file) | Shape | Status |
|---|---|---|---|
| `GET /v1/admin/hunts/{id}/management` | `useAdminHuntManagement` (`features/admin/api.ts`) | hand-typed current member roster, Owner identity, caller-membership flag, and named deletion blockers; Site Admin only | implemented |
| `POST /v1/admin/hunts/{id}/transfer-ownership` | `useTransferAdminHuntOwnership` (`features/admin/api.ts`) | `{new_owner_id}` → `{status:"ok"}`; target must already be a current member; reuses the atomic one-Owner mutation and writes the Admin Audit Log in the transaction | implemented |
| `PUT /v1/admin/hunts/{id}/lock` | `useSetAdminHuntLock` (`features/admin/api.ts`) | `{locked}` → refreshed `HuntManagement`; audited; locking cancels unfinished Jobs, and every mutation except unlock is refused while locked | implemented |
| `DELETE /v1/admin/hunts/{id}` | `useDeleteAdminHunt` (`features/admin/api.ts`) | `{confirmation_name}` → Hunt-local impact counts; exact-name confirmation, selected-Demo and active-Job refusal, transactional tombstone + Admin Audit write | implemented |

### Demo publication and protected release (DESIGN v3.72)

| Method & path | Hook (file) | Shape | Backing task | Status |
|---|---|---|---|---|
| `GET /v1/admin/demo` | `useAdminDemoStatus` (`features/admin/api.ts`) | hand-typed status: configured `enabled` plus effective `available`, selected release, live/replay/map counts, staleness, blockers/warnings and latest in-flight/failure; Site Admin only | DM-10 | implemented |
| `GET /v1/admin/demo/hunts?q=` | `useDemoHuntOptions` (`features/admin/api.ts`) | hand-typed owned-Hunt options, capped at 50; ownership is enforced server-side and not inferred from Ghost View visibility | DM-10 | implemented |
| `POST /v1/admin/demo/preflight` | `useDemoPreflight` (`features/admin/api.ts`) | hand-typed ten-minute confirmation plus public-content counts, warnings and blockers; may idempotently create the virtual Demo principal | DM-10 | implemented |
| `POST /v1/admin/demo/publications` | `usePublishDemo` (`features/admin/api.ts`) | `202 {publication_id,state}`; requires unexpired confirmation, exact Hunt name, unchanged fingerprint, caller ownership, server-clean content/security preflight, and permits `enable_on_success` only for the initial selection | DM-10 | implemented |
| `PATCH /v1/admin/demo` | `useToggleDemo` (`features/admin/api.ts`) | `{enabled}`; enable requires the selected current release and owner, disable is immediate and keeps Hunt/release | DM-5/DM-10 | implemented |
| `GET /v1/demo/release` | `useDemoRelease` (`features/demo/api.ts`) | hand-typed current release id/time, capture ordinals and map manifest; Demo token + matching generation only, `private, no-store` | DM-9/DM-10 | implemented |
| `GET /v1/demo/release/captures/{ordinal}` | `useDemoCapture` (`features/demo/api.ts`) | validated immutable `DemoCapture`; fetched lazily by current-release ordinal and remains available if the source Listing is later restored or deleted, until an explicit publication replaces it | DM-9 | implemented |
| `GET /v1/demo/release/maps/{asset}` | `useDemoMapAsset` (`features/demo/api.ts`) | protected WebP blob; the client sends only a path taken from the current manifest and the API independently checks that allow-list | DM-9 | implemented |

The Demo release hooks deliberately use the API rather than direct Supabase reads. `DemoBanner`
mounts the release sentinel on every Hunt route and the release query rechecks every 15 seconds, so
an already-open session exits after disablement even when the visitor is not on Overview or Map. The private
publication/capture tables have no client grants and the `demo-assets` bucket has no browser read
policy; `apiFetchBlob` carries the short-lived Demo token and exits the Demo session if the release
is disabled or replaced underneath it.

### Visits (VC-1 backend, VC-2 hooks)

| Method & path | Hook (file) | Shape | Backing task | Status |
|---|---|---|---|---|
| `POST /v1/hunts/{id}/visits` | `useCreateVisit` (`features/visits/api.ts`) | generated `VisitCreate`/`VisitResponse`; any member; `units[]` created in the same call; `state` is a **computed** field, never sent; 422 `property_not_in_hunt` when the Property has no Listing here | VC-1 | implemented |
| `PATCH /v1/visits/{id}` | `usePatchVisit` (`features/visits/api.ts`) | generated `VisitPatch`/`VisitResponse`; `action` ∈ `start \| end \| reopen \| cancel \| reinstate \| reschedule`. **`reopen`** clears `ended_at` and returns a completed Visit to in-progress — any member, since it continues the work rather than overriding a judgement; a cancelled Visit is 409 until reinstated, and `template_version` never changes. Timestamps are **server-clock** — the client never sends `started_at`. `cancel`/`reinstate` are creator-or-Owner (403 `cannot_cancel_visit`); an impossible transition is 409 `invalid_visit_transition` | VC-1 | implemented |
| `DELETE /v1/visits/{id}` | `useDeleteVisit` (`features/visits/api.ts`) | generated (204); creator or Owner only | VC-1 | implemented |
| `POST /v1/visits/{id}/units` | `useAddVisitUnit` (`features/visits/api.ts`) | generated `VisitUnitInput`/`VisitUnitResponse`; supply `floor_plan_id` **or** both `beds` and `baths`; `unit_group_key` is database-generated and read-only; duplicate label (case-insensitive) is 409 | VC-1 | implemented |
| `PATCH /v1/visits/{id}/units/{unit_id}` | `usePatchVisitUnit` (`features/visits/api.ts`) | generated `VisitUnitPatch`/`VisitUnitResponse`; `label` and `display_order` only — a unit's shape is not editable in place | VC-1 | implemented |
| `DELETE /v1/visits/{id}/units/{unit_id}` | `useDeleteVisitUnit` (`features/visits/api.ts`) | generated (204) | VC-1 | implemented |
| `POST /v1/visits/{id}/custom-items` | `useCreateVisitCustomItem` (`features/visits/api.ts`) | generated `VisitCustomItemCreate`/`VisitCustomItemResponse`; per-Visit, always rendered as custom | VC-1 | implemented |
| `POST /v1/visits/{id}/defects` | `useCreateVisitDefect` (`features/visits/api.ts`) | generated `VisitDefectCreate`/`VisitDefectResponse`. Only for something the checklist never asked about — most defects arrive by **promotion** from a failed Check. `visit_unit_id: null` means the **building**, not "unknown"; `severity` is nullable and starts unrated | VC-4 | implemented |
| `PATCH /v1/visits/{id}/defects/{defect_id}` | `usePatchVisitDefect` (`features/visits/api.ts`) | generated `VisitDefectPatch`/`VisitDefectResponse`; any member may edit a defect they did not log — on a tour the phone-holder is often not the spotter | VC-4 | implemented |
| `DELETE /v1/visits/{id}/defects/{defect_id}` | `useDeleteVisitDefect` (`features/visits/api.ts`) | generated (204). **Soft delete**, and the Check that promoted it keeps its answer — that a test failed and what the problem was are two separate records. A deleted defect is never resurrected by re-marking the Check | VC-4 | implemented |
| `POST /v1/visits/{id}/fee-proposals` | `useCreateFeeProposal` (`features/visits/api.ts`) | generated `VisitFeeProposalCreate`/`VisitFeeProposalResponse`. **Any member may offer** — whoever walked the unit heard the number. `target` picks the accept path (`fee_slot` → `fee_checklist` upsert, `override` → `overrides` insert) and `target_key` is an allowlist of real fee slots / cost Criteria, so a typo is 422 rather than a fee line nothing renders. The Listing must belong to the Property that was toured (422 `listing_not_visited_property`). Re-confirming the same destination **updates the standing offer** rather than stacking a second | VC-7 | implemented |
| `POST /v1/visits/{id}/fee-proposals/{pid}/decision` | `useDecideFeeProposal` (`features/visits/api.ts`) | generated `VisitFeeProposalDecision`. `accept` performs the **ordinary** cost write by delegating to the fee/override services, so the row is indistinguishable from a manual drawer edit (`value_state: manual`, real `entered_by`) and a base-rent acceptance is Floor-Plan scoped to the walked unit exactly as the drawer would be; `reject` writes only the decision and leaves the Visit's figure alone. Permission is the **Override** permission (§4.2), enforced by RLS and the delegated writer. Re-deciding is 409 `fee_proposal_already_decided` | VC-7 | implemented |
| `DELETE /v1/visits/{id}/fee-proposals/{pid}` | `useWithdrawFeeProposal` (`features/visits/api.ts`) | generated (204). Author-only, pending-only — taking back an offer nobody has acted on | VC-7 | implemented |
| **`PUT /v1/visits/{id}/entries`** | `useSaveVisitEntries` (`features/visits/api.ts`) — invalidates **both** `visit_entries` and `visit_defects`, because a Check marked a problem promotes into a defect | generated `VisitEntryBatch`/`VisitEntryResponse[]`. The **only** write path for answers and the shape VC-6's offline queue will flush. Append-only: clearing an answer sends `value: null`, which lands as that identity's tombstone. Scope comes from the **item**, not the caller — a property item carrying a `visit_unit_id` (or a unit item without one) is 422 `checklist_scope_mismatch`, never silently re-filed. A Question sends `answer_text`, never `value` (422 `checklist_value_not_allowed`). `owner_user_id` is server-set: the author for an Impression, null for everything else. Returns the resulting **current** values, not the inserted rows | VC-3 | implemented |

There are deliberately **no GET routes**: Visit reads are continuously-rendered and Realtime-backed,
so they belong to the direct-Supabase client per the two-client split. `PUT /v1/visits/{id}/entries`
(the batched, `prev_entry_id`-carrying answer write) arrives with VC-3.

Answer identity is `(item, unit, owner)` — `features/visits/entries.ts` owns it, and no caller
re-derives it: getting it wrong merges two members' opinions or splits one member's answer across
units. Visit **state is never read from a column** — `features/visits/visitState.ts` derives it from
`started_at`/`ended_at`/`cancelled_at` on the client, exactly as `VisitResponse.state` does on the
server. Realtime wiring landed with VC-5: `visits`, `visit_units`, `visit_entries`, `visit_defects`
and `visit_custom_items` all invalidate from `lib/realtime.ts`, so another member's write appears
without a reload. Presence is separate from that — `features/visits/usePresence.ts` holds one
ref-counted channel per Visit, scoped to the Visit route rather than the hunt, and is display-only:
nothing is ever stored through it and the checklist works with no signal at all.

**Offline (VC-6).** `useSaveVisitEntries` no longer owns its own mutation function: it lives on the
query client in `lib/offline.ts` under `SAVE_ENTRIES_KEY`, because a write restored from storage is
rebuilt in a page where the hook's closure is gone. `visitId` therefore travels in the variables
rather than being captured, and the same registration owns the `visit_entries` / `visit_defects` /
`visit_entry_conflicts` invalidation. Persistence is narrowed to visit-scoped query keys so a cold
start cannot resurrect stale listings or jobs, and only *paused* mutations are kept. Writes are
optimistic; an optimistic row carries an `optimistic:` id and must never be sent as a
`prev_entry_id`. Open forks read from the derived `visit_entry_conflicts` view
(`useVisitEntryConflicts`); **resolution has no endpoint of its own** — it is an ordinary
`PUT /v1/visits/{id}/entries` whose `prev_entry_id` is the chosen branch.

**The Visit roll-up (VC-8)** is read from `visit_unit_group_scores`, a derived `security_invoker` view
keyed `(hunt_listing_id, unit_group_key)`. It carries no `hunt_id` — RLS already scopes it to the
caller's Hunts — so `useVisitUnitGroupScores` selects every row it is allowed to see and the client
indexes it with `visitScoreKey(listingId, unitGroupKey)`. **The four roll-up rules live in the view,
not in the client**: latest tour per door, best door per group, per-member-then-across averaging, and
no row at all for a unit whose Unit Group the Property does not advertise. Nothing re-derives them.
Because it is derived, `visits`, `visit_units` and `visit_entries` all invalidate it from
`lib/realtime.ts`.

**Fee Proposals (VC-7)** are read straight from `visit_fee_proposals` — `useVisitFeeProposals` for one
Visit's ledger and `useListingFeeProposals` for the pending offers a drawer renders. `useDecideFeeProposal`
takes the Visit in its *variables*, not the hook argument, because a Listing can carry offers from more
than one tour; on an accepted decision it invalidates `fee_checklist`, `overrides` and `hunt_listings`
— exactly what `useUpsertFee` and `useCreateOverride` invalidate, since accepting causes precisely those
writes.

Known gap: a queued write that flushes as the tab navigates can be restored and sent a second time,
appending a duplicate history row. It cannot manufacture a conflict (identical branches are
agreement), and the fix if it ever matters is a client-generated idempotency key with a unique
index, which would change the API contract.

Invitation Link responses carry an API-configured absolute `link`, but the frontend replaces its
origin with `window.location.origin` before copying. Supabase Auth storage is origin-scoped, so a
configured `www`/apex or localhost/LAN-host mismatch must not send a signed-in user to another
origin that appears logged out.

**Site Admin Ghost View mutations.** Hunt-scoped hooks derive Ghost View from the current account's
Site Admin identity plus the absence of a `hunt_members` row. Once confirmed, they mirror ordinary
`/v1/...` requests under `/v1/admin/ghost/...`; the request and response bodies stay identical.
Those endpoints use service-role access only after re-checking non-membership server-side and write
`admin_audit_log` with `via_ghost_view = true`. A Site Admin who is a Hunt member always uses the
ordinary endpoint and their assigned Hunt role. Personal comments, ratings, profile color/name, and
Visits remain on ordinary member-only paths and are never routed through Ghost View.
Listing permanent deletion mirrors `GET /v1/admin/ghost/listings/{id}/deletion-impact` and
`DELETE /v1/admin/ghost/listings/{id}`. The delete and `listing.permanent_delete` audit write share
one transaction; if the audit cannot be written, the Listing remains. Deleting the Listing also
deletes Visits for its Hunt + Property, rather than mutating Visits through their ordinary member
route.

## Direct Supabase reads (via `supabase-js`, RLS-guarded from P2-1)

| Table(s) | Hook (file) | Shape | Status |
|---|---|---|---|
| `hunts` (+ inner `hunt_members` membership filter for `useHunts`) | `useHunts`, `useHunt` (`features/hunts/api.ts`) | hand-typed `Hunt` (incl. `created_at`); the switcher is explicitly current-member-scoped because Site Admin SELECT policies expose all Hunts for Ghost View | exists (0002; `created_at` 0003; admin read widening 20260829000000) |
| `hunt_listings` + embedded `properties`, current `floor_plans`, `scores` | `useListings` (`features/listings/api.ts`) | hand-typed; `properties` includes nullable `city`, `state` (USPS code), `county`, and the §12 geocode cache `lat`/`lng` (nullable — written by DEDUPE only-when-null, so a listing may legitimately have no coordinates; the §13.2 map surfaces read them); embedded Floor Plans filter `is_current = true`, with a defensive client-side retirement filter | exists (0001 incl. `lat`/`lng` + 0002; locality 20260803000000; Floor Plan lifecycle 20260801000000) |
| `hunt_listings` (`status = archived`, same embed) | `useArchivedListings` (`features/listings/api.ts`) — fetched only while the Archived view is open | hand-typed; current Floor Plans only | exists (0001 + 0002; Floor Plan lifecycle 20260801000000) |
| `current_overrides` for one listing | `useOverrides` (`features/listings/api.ts`) | hand-typed scoped target/applicability; newest row per concrete target, including null revert tombstones | exists (20260801000000) |
| `fee_checklist` for one listing | `useFees` (`features/listings/api.ts`) | hand-typed | exists (0002) |
| `current_extractions` resolved rows for a Property | `useExtractions` (`features/listings/api.ts`) | hand-typed scoped target/applicability/provenance; exact and generalized rows may coexist | exists (20260801000000) |
| `extraction_resolution_candidates` + candidate `extractions`/`property_sources` | `useResolutionCandidates` (`features/listings/api.ts`) | P3-6 resolved-to-candidate provenance; RLS follows the resolved Extraction | exists (20260801000000) |
| `rubric_criteria` | `useRubric` (`features/rubric/api.ts`) | hand-typed `RubricCriterion` | exists (0002) |
| `criteria_catalog` | `useCatalog` (`features/rubric/api.ts`) | hand-typed `CatalogEntry` | table exists (0001) + seed |
| `hunt_members` (+ `user_profiles` for display-name/color defaults) | `useMembers` (`features/collaboration/api.ts`) | hand-typed `HuntMember`, including nullable Hunt-level overrides and effective coalesced identity; member rows remain available to Ghost View if contributor-attribution enrichment is unavailable | exists (0002+; profile coalesce P2 + 20260729000000) |
| `get_hunt_contributor_identities(hunt_id)` RPC | `useHuntContributors` (`features/collaboration/api.ts`) | current-member identities plus removal-time `HuntContributor` snapshots; `is_former` distinguishes retained attribution from membership, former color is intentionally null so the UI renders neutral grey | exists (20260901000016) |
| `user_profiles` for the current account | `useProfile` (`auth/profile.ts`) | hand-typed `UserProfile` (`default_display_name`, `default_color`) | exists (0002 + 20260729000000) |
| *(derived)* same as `useMembers` | `useCurrentMember` (`features/collaboration/api.ts`) | `HuntMember \| undefined` via session user id — no extra fetch | client-side only |
| `comments` for one Listing | `useComments` (`features/collaboration/api.ts`) | hand-typed `Comment`; nullable Unit Group scope + `edited_at` | exists (0002 + 20260724000000) |
| `ratings` for one Listing | `useRatings` (`features/collaboration/api.ts`) | hand-typed `Rating`; filtered per Unit Group by row consumers | exists (0002 + 20260724000000) |
| `listing_unit_group_states` for one Hunt | `useUnitGroupStates` (`features/listings/api.ts`) | hand-typed `UnitGroupState` | exists (20260725000000) |
| `hunt_listing_refresh_status` for one Hunt | `useRefreshStatuses` (`features/listings/api.ts`) | hand-typed `RefreshStatus`; service-role success markers, member-readable through Listing membership | exists (20260816000000) |
| `property_images` + `current_floor_plan_images` for one Property, plus signed Storage URLs | `usePropertyImages` (`features/listings/api.ts`) | hand-typed `PropertyImage`; projects canonical LLM `primary_scene` from `vision_assessment.classification` (DESIGN v3.102), with leftover ONNX `predicted_scene`/`kitchen_score` (and pre-promotion `classification_shadow`) visible until refresh; separately projects the validated per-image `kitchen_quality.assessment` (visibility, rating, confidence, rationale) for the Drawer gallery | exists (20260705000000 + 20260808000000; LLM authority DESIGN v3.102) |
| `visits` (+ embedded `visit_units`, `properties`) for one Hunt, one Property, or one id | `useVisits`, `usePropertyVisits`, `useVisit` (`features/visits/api.ts`) | hand-typed `Visit`; **state is derived client-side** from `started_at`/`ended_at`/`cancelled_at` — there is no status column to read | exists (20260817000000) |
| `visit_template_items` for the Visit's `template_version` | `useVisitTemplate` (`features/visits/api.ts`) — `staleTime: Infinity`, since it only changes by migration | hand-typed `VisitTemplateItem`; global read-only reference data like `criteria_catalog`. Section titles are **frontend copy** — the table carries `section_key` and a globally monotonic `display_order`, no section table | exists (20260817000000) + seed in migration |
| `current_visit_entries` for one Visit | `useVisitEntries` (`features/visits/api.ts`) | hand-typed `VisitEntry`. The **view**, never `visit_entries` directly — it centralises the newest-per-`(visit, item, unit, owner)` rule, and is `security_invoker` so it keeps the base table's RLS | exists (20260819000000) |
| `visit_defects` for one Visit (live rows only) | `useVisitDefects` (`features/visits/api.ts`) | hand-typed `VisitDefect`; the query filters `deleted_at is null`, so soft-deleted rows never surface | exists (20260820000000) |
| `visit_custom_items` for one Visit | `useVisitCustomItems` (`features/visits/api.ts`) | hand-typed; per-Visit additions, rendered as custom | exists (20260817000000) |

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
   later exposed for the running-job elapsed timer (DESIGN §13.2). `JobResponse.stage_index`
   exposes `payload.run_state.cursor` for manifest-cursor pipeline progress (duplicate FETCH
   after DISCOVER).

## Not assumed (deliberately)

No `GET /v1/catalog` — the wizard reads `criteria_catalog` directly (global table, migration
0001).
