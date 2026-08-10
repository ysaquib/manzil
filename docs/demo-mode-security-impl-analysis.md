# Demo Mode security and implementation analysis

Date: 2026-08-05  
Reviewed branch: `worktree-demo-mode` at `66f978b`  
Comparison base: `development` at `0e3c5cf`  
Scope: the three Demo Mode migrations, their database tests, the existing Supabase Auth/Storage configuration, and the FastAPI authentication and privileged-operation seams.

## Executive conclusion

**Do not expose Demo Mode to the public in its current state.** The branch has a thoughtful database-first write guard and closes the pre-existing `property_sources.cleaned_text` exposure, but it has three release-blocking gaps:

1. The kill switch does not darken most Demo Hunt data. It only participates in the eight new global-fact policies. An already-issued Demo JWT continues to read the Demo Hunt's Hunt-scoped rows and receive their Realtime changes after `demo_enabled=false`.
2. Storage bypasses the new Property scoping. Every authenticated account can list and download every object in the private `property-images` bucket, including objects belonging to Properties outside the Demo Hunt.
3. The write guard covers `public`, not Supabase Auth. A visitor using the shared Demo Account can operate directly on that account through GoTrue: change its password, attempt identity/email changes, enroll MFA, and invalidate shared sessions. The committed configuration explicitly does not require recent reauthentication for password changes. A shared GoTrue identity is therefore an account-takeover and denial-of-service primitive even if all application data is perfectly read-only.

There are also authoritative-design contradictions and test gaps that must be fixed before DM-8 can be meaningful. The current work appears intentionally incomplete through DM-4; none of DM-2, DM-5, DM-6, DM-7, DM-8, or DM-9 is present on this branch. That incompleteness is not itself a defect, but public enablement before those gates—and before the findings below are fixed—would be unsafe.

## Severity model

- **Critical:** public exposure can leak non-demo data, defeat an emergency shutoff, take over the shared identity, or cause persistent public-demo denial of service.
- **High:** a stated security boundary is missing or contradicted, or a likely future change can bypass it without a deployment-time failure.
- **Medium:** implementation violates an authoritative invariant or unnecessarily exposes security metadata, with limited direct impact today.
- **Low:** hardening, maintainability, or verification improvements.

## Critical findings

### C1 — The kill switch leaves Hunt-scoped PostgREST and Realtime data readable

**Evidence**

- `private.demo_readable_property()` checks `site_settings.demo_enabled`, but it is used only by restrictive policies on `properties`, `property_sources`, `floor_plans`, `property_images`, `property_contacts`, `extractions`, `floor_plan_images`, and `extraction_images` (`20260901000001_demo_read_scoping.sql:33-112`).
- Hunt-scoped policies continue to authorize through `private.member_role(...)` / `private.can_read_hunt(...)`. The Demo Account remains a member of the Demo Hunt when the switch is disabled.
- The only kill-switch test selects `properties` (`api/tests/test_demo_guard.py:235-292`). It does not select `hunts`, `hunt_listings`, `jobs`, `job_events`, `scores`, `comments`, `ratings`, Overrides, fees, Visits, histories, or any `security_invoker` view.
- DESIGN §16 says disabling the demo “darkens PostgREST and Realtime.” Current behavior cannot satisfy that statement.

**Impact**

An operator responding to accidental disclosure or abuse can flip `demo_enabled=false` and still leave most of the useful demo payload readable to every live access token. Because Realtime authorization uses the same table policies, active subscriptions also remain authorized for Hunt-scoped tables.

**Required fix**

Create a centralized `private.can_demo_read_hunt(hunt_id)`/equivalent restrictive predicate and apply it to every Hunt-scoped base table and every relevant current-value/read view via its base policy. For Demo Accounts it should require all of:

- `demo_enabled=true`;
- `hunt_id=site_settings.demo_hunt_id`;
- the ordinary Hunt read predicate.

For non-demo accounts it should preserve current behavior. Do not remove the Demo Account's membership as the kill mechanism: that is slower, creates race windows, and does not address global Property policies cleanly.

Add a schema-driven test that enumerates every authenticated-readable table/view and either proves it is approved reference data or proves that the same JWT sees zero rows after the switch is disabled. Test live Realtime authorization as part of DM-8, not merely SQL selection.

### C2 — Private Storage is globally readable and bypasses Demo Hunt scoping

**Evidence**

- `property-images` is a private bucket, but `property_images_storage_authenticated_select` authorizes every authenticated user for every object where `bucket_id='property-images'` (`20260723000000_property_images_pipeline.sql:22-26`).
- The policy does not join the object path to `property_images`, a Property, a Hunt, or `private.demo_readable_property()`.
- The new migration scopes only the `public.property_images` metadata row. Supabase Storage checks `storage.objects`, not the metadata table, when listing or downloading an object.
- The existing policy also permits object listing, so an attacker does not need to guess content hashes or paths.

**Impact**

A public Demo Account can enumerate and download images from every Hunt/Property in the project. This is cross-Hunt data disclosure and directly defeats the stated private-Storage/Hunt-context design. It affects ordinary authenticated users too, not only Demo Mode.

**Required fix**

Replace the bucket-wide policy. Prefer a stable, validated object-key contract containing a Property or image identifier, then authorize via a `security definer` helper that maps the object to `property_images.property_id` and applies ordinary Hunt visibility plus Demo scoping and `demo_enabled`. If object names cannot be mapped safely, remove direct client SELECT entirely and issue short-lived signed URLs from a Hunt-authorized API endpoint.

Add direct Storage API tests using a real Demo JWT:

- listing returns only Demo Hunt objects (or is forbidden entirely);
- a known in-scope object downloads;
- a known out-of-scope object returns 404/403 even when its exact key is supplied;
- the same token cannot download either object after the kill switch is off.

### C3 — A shared GoTrue user can mutate or disrupt the shared identity

**Evidence**

- The Demo write trigger is attached only to base tables in `public` (`20260901000000_demo_mode_foundation.sql:124-154`). It cannot govern `auth.users` or GoTrue endpoints.
- The design acknowledges that the untrusted browser can drive GoTrue directly, but no auth hook or other control is implemented on this branch.
- `supabase/config.toml` has `auth.email.secure_password_change = false` (line 239), so a current session is not required to reauthenticate before a password change.
- The frontend already uses `supabase.auth.updateUser({ password })` in `ResetPasswordPage.tsx`, demonstrating that self-service user mutation is enabled. A hostile visitor need not use the frontend.
- A holder of the shared session can also invoke global sign-out/session invalidation and can repeatedly race any scheduled reconciler. A reconciler repairs state after compromise; it does not prevent compromise or continuous denial of service.

**Impact**

Any visitor can potentially replace the shared password, alter/rebind identity state subject to provider confirmation settings, enroll MFA, or invalidate other visitors' sessions. This enables persistent denial of service, loss of operator access to the demo identity, and abuse of recovery/email flows. Database read-only controls do not mitigate it.

**Required fix**

Do not distribute credentials or refresh tokens for one shared GoTrue user. The safest shape is a short-lived, server-minted viewer JWT that PostgREST recognizes but that has no mutable GoTrue user/session behind it, carrying an explicit immutable demo claim and a unique session identifier. RLS should key on that claim, not on membership in a shared interactive account. If the architecture must use GoTrue, create isolated per-visitor ephemeral identities, prohibit identity/MFA/user updates with an Auth hook or equivalent provider-side control, use short TTLs, and clean them up; this is operationally heavier.

At minimum, before any exposure:

- enable secure password change and reduce JWT lifetime;
- verify hosted Auth settings rather than assuming `config.toml` configures production;
- test password update, email update, MFA enrollment/unenrollment, refresh-token use, local/global sign-out, recovery, identity linking, and user deletion directly against GoTrue;
- require all mutation attempts to fail without changing the account or other visitors' sessions.

DM-2's planned “reconciler” is insufficient as the primary boundary and should be treated only as recovery/monitoring.

## High findings

### H1 — DESIGN says money-spending RPCs have explicit guards; code deliberately omits them

DESIGN §16 item 4 and IMPLEMENTATION DM-4 require explicit Demo rejection inside `submit_listing`, `answer_job_checkpoint`, `set_listing_source_policy`, and `correct_auto_resolved_checkpoint`. The membership migration instead states that these checks were “deliberately not done” because the table trigger currently blocks their writes (`20260901000002_demo_membership_guard.sql:18-28`). This is a direct DESIGN > code conflict and must stop implementation until reconciled.

The trigger currently provides defense, but explicit RPC guards are still needed because these are security-definer, cost-bearing entry points whose internals can evolve to call a service-role or external side effect before a guarded table write. Guard at function entry, before locks, network dispatch, queue insertion, or any other side effect. Add one behavioral test per RPC using a Demo JWT and assert SQLSTATE `42501`, zero Jobs/events/cost rows, and no external-call dispatch.

### H2 — The advertised API guard does not exist

The foundation migration says an API-layer check accompanies the database guard (`20260901000000_demo_mode_foundation.sql:6-8`), DESIGN §16 says the same, and IMPLEMENTATION DM-5 specifies `require_not_demo`. There is no Demo Mode code under `api/src` or `frontend/src` on this branch.

The database must remain the boundary, but an API-wide unsafe-method rejection is still required to prevent expensive validation/work before the database refuses a write and to produce a stable `403 demo_read_only`. Ensure exceptions are limited to the intended unauthenticated demo-session/config endpoints. Test every registered unsafe FastAPI route automatically; a hand-maintained route list will drift.

### H3 — Trigger coverage fails open in production when a later table is added and tests are skipped

The attachment loop covers tables existing when migration `20260901000000` runs. A later migration can create a new public table without a guard. The code comments recognize this and rely on `test_every_public_table_carries_the_write_guard` (`20260901000000_demo_mode_foundation.sql:156-166`). CI detection is valuable but is not a database invariant, and deploying migrations without the test leaves a live bypass.

Required improvement: provide a reusable `private.attach_demo_guards(regclass)` helper and require each table-creating migration to call it, plus retain the final-schema test. Stronger options are a tightly-scoped DDL event trigger or a final deployment preflight that refuses enablement if any base table lacks both guards or any authenticated-writable view exists. `PATCH /admin/demo` should run the preflight transactionally before changing `demo_enabled` to true.

### H4 — Current tests are narrow simulations, not the promised adversarial pass

The tests correctly simulate an authenticated role for several SQL statements, but they do not exercise PostgREST, Storage, GoTrue, Realtime, or FastAPI. They also test only `properties` for read scoping, only a sample of writes, and do not invoke the cost-bearing RPCs. This is materially below DM-8 and allowed C1/C2/C3 to pass unnoticed.

Build an adversarial harness that obtains the exact token shape used publicly and drives all five externally reachable planes directly. Capture request/response evidence and row-count invariants. Run it against a fresh, fully migrated schema in CI and against staging immediately before enablement.

### H5 — Hosted Auth configuration is an unverified deployment boundary

The repository correctly sets global signup off and uses `shouldCreateUser:false` for OTP. However, `supabase/config.toml` is a local configuration artifact; IMPLEMENTATION already notes that hosted/staging must mirror it. A public demo turns configuration drift into an account-creation or account-mutation exposure.

Before launch, automate or document a blocking hosted-project check for signup disabled, anonymous signup disabled, manual linking disabled, secure password changes enabled, redirect allow-list exactness, JWT TTL, SMTP/rate limits, and email-change confirmation. Exercise unknown-email password, OTP, recovery, and signup requests against staging. Do not accept dashboard screenshots as the only evidence; record executable results.

## Medium findings

### M1 — Membership guard permits `member`, contradicting “Curator and nothing else”

`private.demo_membership_guard()` rejects foreign Hunts and the `owner` role, but accepts both `curator` and `member` in the Demo Hunt (`20260901000002_demo_membership_guard.sql:35-62`). DESIGN §3 requires exactly Curator. The positive test proves Curator is allowed but never proves Member is rejected (`api/tests/test_demo_guard.py:350-372`).

Change the condition to require `new.role = 'curator'` exactly. Add INSERT and UPDATE tests rejecting both `member` and `owner`, including service-role execution. This matters because UI permission derivation and demo behavior assume the Curator surface.

### M2 — Demo metadata is overexposed

Every authenticated user can read all rows and fields in `demo_accounts` and the full singleton `site_settings`, including `created_by`, notes, `updated_by`, timestamps, and the Demo Hunt ID (`20260901000000_demo_mode_foundation.sql:41-71`). The frontend needs only “am I demo?” and a minimal public config response.

Remove direct table SELECT from authenticated users. Expose a narrow invoker/definer function returning only caller-scoped `is_demo` and public configuration, or serve it through `GET /v1/demo/config`. This reduces identity enumeration and avoids making future settings accidentally public when columns are added.

### M3 — `demo_accounts` cardinality is not actually one

The migration says expected cardinality is one but the schema permits arbitrarily many rows. Multiple Demo Accounts amplify session/reconciliation complexity and can make operational assumptions false. Enforce the intended cardinality or deliberately redesign helpers/tests for multiple accounts. If retaining a table for future multiplicity, correct the design and runbook rather than relying on commentary.

### M4 — The kill-switch/settings row has no integrity coupling

`site_settings` allows `demo_enabled=true` while `demo_hunt_id is null`, and permits selecting a Demo Hunt not owned by the primordial Site Admin. The former fails closed for Property reads but produces inconsistent behavior; the latter violates the Demo Hunt definition.

Use an admin-only transactional function to enable demo mode that verifies: exactly one configured Demo identity; enabled implies a non-null Hunt; the Hunt owner is primordial; the Demo Account has exactly one membership and it is Curator in that Hunt; all guard/preflight checks pass. Direct service-role updates should be discouraged or constrained where practical.

## Auth and API review results

### Controls that are sound in the reviewed code

- FastAPI authenticates bearer tokens by asking Supabase Auth for the user, rather than trusting an unverified decoded JWT (`api/src/manzil_api/dependencies.py`).
- Ordinary mutations use a caller-scoped Supabase client, preserving RLS. Raw pool access is concentrated in admin modules and those routes use the live-database `AdminUser` check, so revocation does not wait for JWT expiry.
- Admin account provisioning is behind the Site Admin dependency and records an audit event. Public frontend signup is absent.
- OTP login uses `shouldCreateUser:false`; global and SMS signup are disabled in the committed local configuration.
- CORS uses a configured origin allow-list rather than `*`. CORS is not an authorization boundary, but this is the correct browser posture.
- Privileged invitation and ownership operations are centralized, making their subject-based Demo checks auditable.

### Remaining API/Auth improvements required for public exposure

- Implement DM-5's rate-limited unauthenticated demo-session endpoint using cross-instance storage. In-memory limiting is inadequate with multiple processes/restarts. Apply per-IP and global issuance ceilings, short expirations, abuse telemetry, and a hard server-side disable.
- Never return or embed the Demo Account password. Do not put a reusable refresh token in static assets/local storage.
- Ensure error responses do not reveal whether Demo Mode, the Demo Account, or a target Hunt exists when disabled; DM-5's planned disabled `404` is appropriate.
- Add request-body and URL limits to the demo replay submission even though it is browser-only; otherwise it becomes an easy client-memory/log abuse surface.
- Verify that no “demo” request reaches worker/fetch/LLM/Maps code. Assert external-call counters and `jobs`, `job_events`, `job_stage_costs`, and tier-credit rows remain unchanged.
- Add security headers at the deployment edge: a restrictive CSP, `frame-ancestors`, `nosniff`, referrer policy, and HSTS. This is especially important once a public session-bearing page exists.

## Implementation-quality observations

The statement-level write guard is a good central control for current `public` tables. It blocks zero-row statements, includes TRUNCATE defense in depth, uses a fixed `search_path`, and tests final-schema trigger coverage. Revoking write grants on public views is also useful hardening. The `cleaned_text` column-grant change correctly removes the table-level grant before regranting safe columns and intentionally fails closed for newly added columns.

Two comments should be corrected because they overstate guarantees:

- “One trigger covers every table in `public`, including tables that do not exist yet” is false; the later comment correctly admits future tables are not covered.
- “Foreign-key cascades are covered” should be verified rather than asserted. PostgreSQL's internally generated referential actions and trigger firing behavior are nuanced; add a behavioral cascade test under a Demo JWT for any cascade reachable by an authenticated statement.

Performance should also be measured. `private.demo_readable_property()` repeatedly reads the singleton settings row and probes `hunt_listings`. The intended dataset is small, but EXPLAIN representative Overview/detail queries under both real and Demo identities to confirm restrictive policies do not produce pathological nested evaluation. This is not a launch blocker unless measured latency is poor.

## Verification performed

### Static and structural review

- Read DESIGN §1, §3, §4.2, §5, §8.3, and §16 and followed the auth/API reading paths.
- Compared `development...worktree-demo-mode`; reviewed all 973 changed lines across DESIGN, IMPLEMENTATION, three migrations, and `api/tests/test_demo_guard.py`.
- Enumerated all 45 public base tables, authenticated-read policies, security-definer functions/RPC grants, Storage policies, FastAPI raw-pool/service-role use, auth calls, router registration, and local Auth configuration.
- Confirmed no Demo Mode implementation exists yet in `api/src` or `frontend/src`.

### Runtime status

The local Supabase stack was reachable, but its applied schema ended at migration `20260829000000`. `supabase migration up --local` refused to apply the demo migrations because the local migration history is missing three earlier Visit migrations (`20260824000000_visit_reopened_at.sql`, `20260825000000_visit_defect_severity.sql`, `20260826000000_visit_template_v2.sql`) and requires `--include-all`. I did **not** run a destructive `supabase db reset` or force out-of-order migrations because the shared local database may contain user state.

Therefore the new database tests were not executable against the existing local schema during this review. This is a verification gap, not evidence that they pass. Before merging, run on a disposable/fresh database:

```text
supabase db reset
# immediately restore the required local Site Admin bootstrap per AGENTS.md
uv run --package manzil-api pytest api/tests/test_demo_guard.py
uv run --package manzil-api pytest api/tests
```

Then run the expanded direct PostgREST/Storage/GoTrue/Realtime adversarial suite described above. The current test file alone is insufficient for release sign-off.

## Required release gate

Do not set `site_settings.demo_enabled=true` or deploy a public demo-session endpoint until all of the following are true:

1. C1, C2, and C3 are fixed and verified against real external interfaces.
2. The DESIGN/code conflict in H1 is resolved in favor of DESIGN or explicitly re-ratified with a Decision Log change.
3. DM-2 and DM-5 through DM-8 are complete; DM-8 includes PostgREST, Storage, GoTrue, RPC, Realtime, and API evidence.
4. Every public table/view passes final-schema read/write coverage, every money-bearing RPC is explicitly guarded, and the enable transaction runs the same preflight.
5. Hosted Supabase Auth settings are checked by an executable staging test.
6. The kill switch is tested with already-issued access and refresh tokens and active Realtime subscriptions.
7. Demo seed/replay content has passed the privacy review and no real member identity, comment, rating, Visit, contact detail, or non-demo image is reachable.

Until then, the safe posture is the current default: Demo Mode disabled and no public session issuance.
