# Demo Mode security and implementation reanalysis

Date: 2026-08-05

Reviewed branch: `worktree-demo-mode` at `09a4974`

Prior review baseline: `66f978b` and `docs/demo-mode-security-impl-analysis.md`

Comparison base: `development` at `0e3c5cf`

## Executive conclusion

The implementation is substantially stronger than it was during the first review. In particular, the virtual principal with no `auth.users` row is a sound answer to the shared-GoTrue-account takeover problem; Hunt-scoped reads now inherit the kill switch through `private.member_role()`; Demo Storage reads are Property-scoped; the cost-bearing RPCs have entry guards; and the API has an app-wide unsafe-method guard.

**Demo Mode still should not be exposed publicly.** This reanalysis found two critical security weaknesses and several high-impact implementation/release defects:

1. Demo scoping fails open if the `demo_accounts` marker disappears while a token is live. The signed token's `manzil_demo` claim is ignored by RLS. With no marker row, the same token becomes “ordinary authenticated” to the global-fact and Storage policies and can read every global Property fact and image across all Hunts.
2. The public issuance limiter is neither concurrency-safe nor storage-bounded. Concurrent requests can overshoot both ceilings, while every disabled/rate-limited request inserts another permanent row. An unauthenticated attacker can grow the database indefinitely even when Demo Mode is off.
3. Existing Demo installations cannot be reconciled by the seed as claimed: it inserts the new singleton before deleting the old singleton and therefore trips the unique index.

The current branch implements DM-1 through DM-7. DM-8 (real adversarial verification) and DM-9 (Replay Capture/maps) remain incomplete. The default-off posture must remain until the critical/high items and DM-8 are complete.

## Prior-finding disposition

| Prior finding | Status | Reanalysis |
|---|---|---|
| C1 kill switch missed Hunt-scoped data | **Fixed, with a new fail-open caveat** | `private.member_role()` now synthesizes the Demo Curator role only for the configured Hunt while enabled. The new C1 below concerns loss/mismatch of the marker row. |
| C2 Demo could read all Storage | **Fixed for a healthy marker row** | Object paths map to Property IDs and use `private.demo_readable_property()`. The old broad posture remains for ordinary accounts and conflicts with DESIGN §8.3; see H6. |
| C3 shared GoTrue account takeover | **Strongly fixed** | The subject has no `auth.users` row. Direct GoTrue self-mutation has no target. |
| H1 explicit cost-RPC guards absent | **Fixed** | Guards are injected at function entry and structurally checked. The catalogue-rewrite technique has maintainability concerns but closes the stated gap. |
| H2 API guard absent | **Fixed** | `require_not_demo` is registered app-wide and unsafe-route coverage is schema-driven. |
| H3 future public tables may lack triggers | **Improved** | Reusable attachment helper plus transactional enable preflight. Future migrations must still call the helper; preflight protects enablement. |
| H4 adversarial tests incomplete | **Still open** | SQL/API/frontend tests expanded, but no real PostgREST + Storage + GoTrue + Realtime DM-8 pass is present. |
| H5 hosted Auth config unverified | **Partly superseded** | Virtual principal removes Demo dependence on a mutable GoTrue user, but ordinary production account-provisioning settings still need hosted verification. |
| M1 exact Curator membership | **Superseded** | The virtual principal has no stored membership; Curator is synthesized. Stored membership is refused. |
| M2 metadata overexposed | **Fixed** | Direct policies removed and replaced by narrow `demo_context()`. |
| M3 singleton unenforced | **Fixed** | Unique expression index enforces one row. |
| M4 settings/preflight integrity | **Mostly fixed** | Enabled requires a Hunt and preflight verifies the virtual principal, owner, guards, views, and cleaned text. Token/marker mismatch remains critical. |

## Critical findings

### C1 — Losing the marker row turns a live Demo JWT into a globally privileged reader

**Evidence**

- Demo tokens carry the signed top-level claim `manzil_demo=true` (`api/src/manzil_api/demo/service.py`), but all database controls identify Demo solely with `private.is_demo_account(auth.uid())`.
- `private.is_demo_account()` returns whether the subject currently exists in `demo_accounts` (`20260901000000_demo_mode_foundation.sql:84-92`). It never inspects `auth.jwt()`.
- `private.demo_readable_property()` begins with `not private.is_demo_account(auth.uid()) OR ...` (`20260901000001_demo_read_scoping.sql:33-49`). If the marker row is absent, this returns true for every Property.
- `private.demo_readable_storage_object()` similarly returns true immediately for any subject not currently marked Demo (`20260901000003_demo_hardening.sql:75-80`).
- The write trigger also stops identifying the JWT as Demo when the marker is missing.
- `demo_accounts.user_id` deliberately has no FK after virtual-principal migration, so nothing prevents a service-role/admin/script deletion while issued tokens remain alive.

**Impact**

Deleting or corrupting the singleton does not fail closed. Every unexpired Demo token immediately gains the same global-fact read posture as a normal authenticated account: all Properties, Sources except `cleaned_text`, Floor Plans, global Extractions, contacts, image metadata, and every object in `property-images`. Hunt-scoped rows mostly remain hidden because the virtual principal has no stored membership, but the global data exposure is precisely the cross-Hunt breach Demo scoping was introduced to prevent.

This can occur through an operational mistake, a faulty seed/reconcile deployment, manual service-role maintenance, or a future cascade/schema change. The emergency kill switch does not help because the unrestricted `not is_demo_account` branch bypasses `demo_enabled` entirely.

**Required fix**

Treat a signed Demo claim as restrictive even when configuration is missing or inconsistent. Create a database predicate such as `private.has_demo_claim()` based on `auth.jwt() ->> 'manzil_demo' = 'true'`, and define effective Demo identity as claim **or** marker, never marker alone. For a claimed token:

- marker missing, duplicate, or subject mismatch → zero application/global/Storage reads and all writes refused;
- Demo disabled → zero non-reference reads;
- configured correctly → Demo Hunt/Property reads only.

The claim is safe to use as a *restriction* because a forged JWT cannot reach PostgREST without a valid project signature. Do not use the claim alone to grant visibility; grant only when it also matches the configured singleton subject and enabled Hunt.

Add behavioral tests for the same live JWT after:

- deleting `demo_accounts`;
- changing the singleton to another UUID;
- nulling/changing `demo_hunt_id` while disabled;
- disabling and re-enabling;
- deleting/recreating the principal during reconciliation.

Every mismatch must return zero global facts/objects and refuse writes. Preflight is not sufficient because it runs only on enablement; the RLS predicate itself must fail closed at query time.

### C2 — The unauthenticated issuance endpoint permits limiter races and unbounded database growth

**Evidence**

- `issue_demo_session()` performs `count(*)`, decides, and then inserts without a row lock, advisory lock, counter row, or serializable isolation (`20260901000004_demo_sessions.sql:46-101`).
- Under PostgreSQL READ COMMITTED, concurrent transactions can all observe the same below-limit count and all issue tokens. A function being one SQL statement from the caller does not serialize its internal reads/writes.
- Every disabled request inserts an `outcome='disabled'` row before returning. Every over-limit request inserts `outcome='rate_limited'`. There is no retention, partition expiry, capped aggregation, scheduled deletion, or size ceiling.
- `/v1/demo/session` is unauthenticated by necessity and no edge/API limiter precedes the database function.
- The current “rate limit” test runs while Demo Mode is disabled and explicitly accepts only `disabled`/`rate_limited`; it never issues a token, reaches a ceiling, or creates concurrency (`api/tests/test_demo_api.py:202-227`).

**Impact**

An attacker can use parallel requests to exceed per-key/global issuance limits. More importantly, they can issue unlimited requests after the ceiling or while Demo Mode is disabled and force one durable insert each time. This converts the public endpoint into a straightforward database storage, WAL, index-bloat, and API-worker exhaustion attack. The kill switch does not stop it; disabled requests still write telemetry.

**Required fix**

- Serialize the decision with an advisory transaction lock or locked hourly counter rows, or use a single atomic upsert that increments a bounded `(window, client/global)` counter and conditionally returns issued.
- Do not persist one row per refused request. Aggregate counters by bounded time bucket, sample refusals, or enforce retention with a scheduled purge/partition drop.
- Put an independent edge limiter in front of `/demo/session` and `/demo/config`; the database limiter is defense in depth, not the first packet sink.
- Cap request concurrency/timeouts and use async I/O in FastAPI so slow PostgREST calls do not occupy event-loop workers.
- Test hundreds of concurrent calls against an enabled disposable database and assert issued count never exceeds either ceiling. Test sustained refused traffic and assert storage remains bounded.

## High findings

### H1 — The seed cannot upgrade an existing singleton to the virtual principal

`scripts/seed_demo_hunt.py` inserts `DEMO_PRINCIPAL_ID` at lines 183-191, then deletes any other row at line 194. With the singleton unique index, an existing prior Demo Account causes the insert to fail before the delete runs. The comment claims the reverse.

This is especially relevant because this branch evolves an earlier real-account Demo implementation into a virtual principal. The preflight then correctly refuses the old row because it still has an `auth.users` record, leaving the operator unable to enable Demo without manual intervention.

**Fix:** within one transaction, disable Demo, delete/reconcile the stale marker first, insert/upsert the deterministic virtual principal, verify there is no matching `auth.users` row, and run preflight. Preserve or explicitly remove the obsolete Auth user through an audited/runbook path; do not silently strand it. Add an upgrade test starting with a different singleton linked to an actual Auth user.

### H2 — Previously issued tokens revive when Demo Mode is re-enabled

The kill switch gates reads through current `demo_enabled`, but tokens contain no configuration generation/epoch. Disabling hides data; re-enabling the same singleton subject makes every still-unexpired token valid again.

**Impact:** during an incident, an operator may disable the demo, remediate, and re-enable expecting prior potentially stolen tokens to remain dead. They instead regain access until `exp`. With a default 30-minute TTL this window is bounded, but environment configuration can make it much longer (H4).

**Fix:** add a monotonically changing Demo generation/`not_before` value to `site_settings`, include it in issued JWTs, and require an exact match in claim-aware RLS/Storage predicates. Increment it on every disable or enable transition. Test a token issued before the transition remains dark after re-enable.

### H3 — “Short-lived” token lifetime has a minimum but no maximum

`mint_token()` uses `max(60, settings.demo_session_ttl_seconds)`. A typo such as seconds-versus-milliseconds can mint tokens valid for months or years. Preflight cannot see API environment configuration and no startup validator bounds it.

**Fix:** use a Pydantic constrained integer with a deliberate maximum (for example 5–30 minutes, per the product decision), fail startup outside the range, and test both bounds. Record the deployed value in DM-8 evidence. Kill-switch generation (H3) is still needed even with a short maximum.

### H4 — Demo toggle and its Admin Audit Log write are not atomic

`PATCH /v1/admin/demo` calls `set_demo_enabled(...)` and only afterward inserts the audit row through a separate pool operation. If the audit insert fails after the setting commits, the public security posture changes without the required Admin Audit Log event. The same general pattern exists elsewhere, but Demo enablement is a particularly sensitive externally visible transition.

**Fix:** perform toggle and audit insertion in one database transaction/function, with actor validation already performed by the API. Return success only after both commit. Test audit failure rolls back the setting. Disabling must remain operationally reliable; ensure the audit table cannot make emergency disable impossible without an explicitly approved fallback that emits external alerting.

### H5 — Ordinary authenticated users still have bucket-wide image access contrary to DESIGN §8.3

The Storage helper deliberately returns true for every non-Demo authenticated subject. This fixes Demo cross-Hunt access but preserves the pre-existing bucket-wide exposure. DESIGN §8.3 says signed-URL access is granted only in an authenticated Hunt context containing that Property.

This is an authoritative DESIGN/code conflict, even if current accounts are trusted and global Property facts are broadly readable. Images can contain more privacy-sensitive content than structured facts, and the current policy permits listing every object.

**Fix:** either enforce Hunt-context image access for all ordinary users via object-to-Property authorization/signed URLs, or stop and ratify the intended global-image posture in DESIGN with a Decision Log entry. Do not silently retain the contradiction.

### H6 — DM-8's advertised boundary verification still does not exist

The branch has good SQL simulation and API route enumeration, but no executable evidence drives the issued token through real PostgREST, Storage HTTP, GoTrue, Realtime, and FastAPI against an enabled, fresh database. Important examples missed by current tests are C2's concurrency behavior, token revival, marker-loss behavior, and actual Storage list/download responses.

DM-8 must include:

- successful session issuance through the real API/service-role RPC (effective privilege was verified after a clean reset, but the enabled HTTP path still needs a behavioral test);
- exact in-scope/out-of-scope PostgREST and Storage requests;
- marker deletion/mismatch fail-closed tests;
- GoTrue `/user`, update, MFA, logout and reauthenticate returning `user_not_found`;
- active Realtime subscriptions before/after disable and generation rotation;
- every cost-bearing RPC and zero downstream Job/cost/external-call effects;
- concurrent issuance and bounded telemetry;
- hosted/staging configuration evidence.

## Medium findings and weaknesses

### M1 — Public endpoints perform synchronous network I/O inside async handlers

`demo_config()` and `create_demo_session()` call synchronous `supabase-py` methods directly from `async def` handlers. An attacker can occupy event-loop capacity with repeated public calls, magnifying upstream latency into API denial of service. Use an async client, run bounded blocking work in a thread pool, or make the handlers synchronous so FastAPI dispatches them appropriately. Add strict upstream timeouts.

### M2 — `/demo/config` is a second unauthenticated public endpoint with no limiter/cache

DESIGN says the session endpoint is the only unauthenticated public route, but `/v1/demo/config` is also unauthenticated and performs a service-role database read per request. This is a minor design wording conflict and a DoS amplifier.

Serve a short cached boolean, edge-cache it with a small TTL, or fold availability into a rate-limited session attempt. Never cache or expose the Hunt/principal. Include it in edge limits and public-endpoint inventory.

### M3 — `demo_context()` exposes Demo configuration to every authenticated user

The function returns `enabled` and `hunt_id` to any authenticated subject, not only the Demo principal. This is much narrower than the old table policies and low sensitivity, but the stated need was “am I demo?” for the frontend. Consider returning Hunt/config only when the caller has the signed Demo claim and valid singleton match; ordinary users need only `is_demo=false` or no call at all.

### M4 — Client-side demo detection trusts mere token presence for UX

`isDemo()` returns true for any value stored under `manzil-demo-token`, without checking expiry or even JWT shape. This is not an authorization issue—the server/database remain authoritative—but a malformed/expired injected value disables all frontend writes, invalidation, and Realtime until the user manually exits Demo Mode.

Validate basic claims/expiry client-side for UX, clear malformed/expired values, and handle 401 by exiting/reissuing visibly. Continue treating server verification as the only security decision.

### M5 — Generic unsafe-write interception produces inconsistent simulated behavior

`apiFetch()` resolves every Demo unsafe request as `undefined`. Only comments, ratings, pins, and Visit entries have meaningful optimistic handling. Other mutation hooks may dereference a returned object (`usePatchUnitGroupState` does so in `onSuccess`) or show success while making no visible local change. This is a product-integrity weakness rather than a database security gap, but confusing “saved” states undermine the demo's honest read-only promise.

Inventory every visible Curator mutation. Either implement explicit local simulation with typed synthetic return values, or intercept it with a consistent “Demo only—nothing saved” result/toast. Add component-level tests for Overrides, fees, utilities, Interest Status, listing state, comments update/delete, Visit defects/custom items, and checkpoint/job actions—not merely the generic fetch seam.

### M6 — Session issuance audit fields need stricter validation and retention semantics

`p_client_key`, `p_user_agent`, and limit parameters are trusted inside the service-only function. Today only the API calls it, but defense in depth should constrain key format/length and positive ceiling ranges in SQL. The API truncates user-agent only inside SQL; client key is not constrained. Define retention and disclose the HMAC/user-agent telemetry in the privacy/runbook documentation.

### M7 — JWT validation should pin the complete accepted profile

The API validates HS256 signature, audience, and expiry, which is the essential core. It does not require UUID subject format, exact `role='authenticated'`, expected issuer, `iat` sanity, or a token generation. PostgREST ultimately casts `auth.uid()` to UUID, but rejecting malformed profiles at issuance/API verification yields clearer and safer behavior.

Require and validate the exact claims the API itself emits. Verify that the hosted Supabase project still accepts the chosen custom HS256 token scheme; newer asymmetric signing-key configurations and key rotation need an explicit operational plan. Never expose `SUPABASE_JWT_SECRET` outside the API environment.

## Positive security properties confirmed

- The virtual principal has no Auth user or stored Hunt membership; Curator visibility is synthesized only for the configured Demo Hunt.
- `private.member_role()` centralizes the Hunt kill switch, so existing Hunt-scoped policies and `security_invoker` views inherit it.
- Demo global-fact policies are restrictive and the Storage object parser fails closed on malformed paths.
- `cleaned_text` remains withheld through column grants.
- Statement-level write and TRUNCATE guards cover final-schema public tables; enabling runs a database preflight.
- Cost-bearing public RPCs now guard at entry, before their current writes.
- Direct Demo metadata table reads were removed.
- API demo-token verification checks signature, audience, and expiry; forged and expired token tests exist.
- The app-wide API dependency rejects Demo unsafe methods before route validation/work.
- Frontend sessions use `sessionStorage`, disable Supabase persistence/refresh, suppress Realtime, and never send unsafe API calls.
- Signup remains disabled and OTP uses existing-account-only behavior for ordinary users.

## Verification performed

### Review and inspection

- Re-read DESIGN §1, §3, §4.2, §5, §8.3, §16 and the Demo Mode implementation table.
- Queried the knowledge graph when available and compared all changes from the prior reviewed commit `66f978b` to `09a4974`.
- Reviewed migrations `20260901000003` through `00005`, JWT minting/verification, app-wide dependencies, public/admin routes, seed reconciliation, frontend client/cache/Realtime seams, and all Demo-specific tests.
- Re-enumerated Storage policy/object-key construction and public API reachability.

### Commands run

- `uv run ruff check ...` on all changed Demo API/test/seed Python: **passed**.
- `pnpm -C frontend test -- --run tests/demoMode.test.ts`: due the package script's argument handling, this ran the full frontend suite: **98 files, 728 tests passed**.
- `pnpm -C frontend build`: TypeScript and Vite production build **passed**; only the existing large-chunk warning remained.
- `git diff --check`: run during finalization.

### Database runtime follow-up

After the initial reanalysis, the Owner confirmed no production deployment existed and authorized a destructive local reset. The reset first exposed duplicate migration versions for three Visit migrations; those files were renumbered to adjacent `...000001` versions. A second reset then applied every migration through `20260901000005`, seed data loaded, and `admin@manzil.local` was recreated and verified as Site Admin.

The focused command below produced **45 passed, 1 failed**. The failure is a fixture defect in `test_demo_reads_are_scoped_to_the_demo_hunt`: on a truly fresh database the fixture created exactly two Properties and put both in the test Hunt, while the assertion requires `total > len(expected)` before it can test exclusion. No out-of-scope Property existed. This test must create its own out-of-scope row rather than relying on ambient seed/developer data.

Effective privilege was also checked directly after reset: `service_role` **can** execute `public.issue_demo_session(text,text,integer,integer)` and `authenticated` cannot. This disproves the earlier static concern that the missing explicit grant made the service path unusable; Supabase's effective role privileges provide it. A catalogue assertion should pin that observed contract.

Focused command:

```text
uv run --package manzil-api pytest api/tests/test_demo_guard.py api/tests/test_demo_api.py
uv run --package manzil-api pytest api/tests
```

After fixing the self-contained fixture, rerun it and then execute DM-8 against the actual HTTP interfaces. A direct privilege query or privileged SQL call is not a substitute for the enabled PostgREST RPC behavior.

## Required release gate

Keep Demo Mode disabled until all of the following are complete:

1. Claim-aware RLS/Storage/write predicates make marker loss or mismatch fail closed.
2. Issuance is concurrency-safe, telemetry is bounded/retained, and an edge limiter protects public endpoints.
3. Effective issuance privileges are pinned and successful issuance is verified through the real service-role client.
4. Existing real-account/singleton state upgrades idempotently to the virtual principal.
5. Token generation rotation prevents pre-disable tokens reviving; TTL is strictly bounded.
6. Demo toggle and audit are atomic, or an explicitly ratified emergency-audit design replaces that requirement.
7. The ordinary-user Storage posture is reconciled with DESIGN §8.3.
8. The fresh-database fixture failure is fixed without relying on ambient data, then focused suites pass.
9. DM-8 passes on a fresh database and staging across API, PostgREST, Storage, GoTrue, Realtime, RPC, concurrency, and kill-switch transitions.
10. DM-9 is complete before exposing submission/replay/maps surfaces promised by DESIGN.

Until those conditions are met, default-off plus no public session issuance remains the only safe deployment posture.
