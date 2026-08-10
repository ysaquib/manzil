# Demo Mode — hardening, DM-8, DM-9 plan

Branch: `worktree-demo-mode` at `f5777b1`
Sources: `docs/demo-mode-security-impl-analysis.md` (R1), `docs/demo-mode-security-impl-reanalysis.md` (R2)
Status: **Phases A–H complete 2026-08-06** (DESIGN v3.56 + v3.57,
IMPLEMENTATION 2.0.128 + 2.0.129). Demo Mode stays disabled.

Three items are owed before enablement, none of them code:

1. **The Replay Capture itself.** The export path, the browser replay and the
   pacing are built and tested; the bundle needs a real paid ingest to record.
   Owner submits a URL that produces a good timeline including a checkpoint,
   then `manzil export-demo-capture <job_id>`.
2. **Pre-captured map stills.** `MapFrame` already refuses to call
   `loadGoogleMaps()` in a demo session and renders an honest placeholder;
   supplying `demoStaticUrl` upgrades that to a picture. Depends on which
   Properties the Demo Hunt ends up carrying.
3. **A staging run of both scripts.** `scripts/dm8_adversarial.py` is green
   locally (37/37); it must run again against staging immediately before
   enablement, and `scripts/check_hosted_auth.py` has never run at all because
   no hosted project exists.

## Ordering, and why it is not the order requested

DM-8 is the release gate, not a buildable task: it is an adversarial pass driven
against the state we intend to ship. Executing it before R2's C1/C2 are fixed
would produce a report that restates findings we already hold. The hosted Auth
check (R1 H5) has the same shape plus a hard blocker — R2 records that no hosted
deployment exists, so the check can be *written* now and *run* only against a
staging project.

So: **fix (A–E) → build DM-9 (F) → build and run DM-8 (G) → hosted check (H)**.
Phases A–C are the critical path; D is Owner rulings that gate parts of A and B;
E and F are independent and can run alongside.

---

## Phase A — Demo identity fails closed (R2 C1, H2, H3, M7)

The single most important fix. Today every database control asks
`private.is_demo_account(auth.uid())`, which reads the `demo_accounts` marker
row. Both read predicates open with `not private.is_demo_account(...) or ...`,
so **if the marker row disappears, a live demo token becomes an ordinary
authenticated reader** with global-fact and bucket-wide Storage access. The
signed `manzil_demo` claim the API already mints is ignored by the database.

1. **`private.has_demo_claim()`** — `auth.jwt() ->> 'manzil_demo' = 'true'`.
   Safe as a *restriction*: a forged JWT cannot reach PostgREST without the
   project signature. Never used to grant.
2. **`private.demo_identity()`** returning one of `none` / `ok` / `broken`:
   - `none` — no claim and no marker → ordinary user, current behaviour.
   - `ok` — claim present **and** subject matches the singleton marker **and**
     `demo_enabled` **and** generation matches → Demo Hunt reads only.
   - `broken` — claim present but marker missing, duplicated, mismatched, or
     generation stale → **zero non-reference reads, all writes refused**.
   Marker-without-claim (a real account marked demo) stays treated as demo.
3. Rewrite the four call sites onto it: `demo_readable_property`,
   `demo_readable_storage_object`, `member_role`, `demo_write_guard`, plus the
   seven RPC entry guards.
4. **Generation / epoch (H2).** `site_settings.demo_generation bigint`,
   incremented on **every** toggle in either direction. Minted into the token as
   `manzil_demo_gen`; required to match in the predicates. This kills token
   revival across a disable→re-enable cycle and gives an operator a revocation
   lever that does not depend on `exp`.
5. **TTL bound (H3).** `demo_session_ttl_seconds` becomes a constrained int
   (60 ≤ ttl ≤ 1800 — Owner may pick the ceiling); out-of-range fails at
   startup, not at mint time. `max(60, …)` is removed.
6. **JWT profile pinning (M7).** Verification requires UUID `sub`,
   `role='authenticated'`, expected `aud` and `iss`, sane `iat`, and the
   generation claim. Reject malformed profiles at the API rather than letting
   PostgREST's UUID cast decide.

Tests (behavioural, same live JWT): marker deleted; singleton changed to another
UUID; `demo_hunt_id` nulled; disable→re-enable; principal deleted and recreated
mid-reconcile. Every one must return zero global facts, zero Storage objects,
and refuse writes.

## Phase B — Public endpoints are bounded and concurrency-safe (R2 C2, M1, M2, M6)

`issue_demo_session` does `count(*)` → decide → `insert` with no lock. Under
READ COMMITTED concurrent callers all read the same below-limit count and all
issue. Separately, **every refused request inserts a durable row**, including
while Demo Mode is off — an unauthenticated attacker can grow the database
without bound with the kill switch engaged.

1. **Serialize the decision.** `pg_advisory_xact_lock` on a fixed key, or —
   preferred — a bounded counter table keyed `(window_start, client_key)` with a
   single atomic upsert-and-return that increments and decides in one statement.
2. **Stop persisting a row per refusal.** Aggregate refusals into the same
   bounded counter rows. Keep `issued` as telemetry with a stated retention, and
   add a scheduled purge (pg_cron) plus a hard row ceiling.
3. **Validate inputs in SQL (M6):** `p_client_key` format and length, positive
   bounded ceilings. Document the HMAC/user-agent telemetry and its retention in
   the privacy note and runbook.
4. **Stop blocking the event loop (M1).** `demo_config` and
   `create_demo_session` call synchronous `supabase-py` from `async def`
   handlers. Move to a thread pool (or make the handlers sync) and add strict
   upstream timeouts.
5. **`/demo/config` (M2).** Short-TTL cached boolean, counted by the limiter,
   never exposing hunt or principal. Its existence contradicts §16's "the only
   unauthenticated public route" — see Phase D.
6. **Edge limiter.** Per-IP limits in front of `/demo/*` at the deployment edge,
   recorded in `docs/production-deployment-render-supabase.md`; the database
   limiter stays defence in depth, not the first packet sink.
7. **Security headers** (R1, API section): CSP, `frame-ancestors`, `nosniff`,
   referrer policy, HSTS at the edge — required once a public session-bearing
   page exists.

Tests: hundreds of concurrent issuance calls against an enabled disposable
database, asserting neither ceiling is exceeded; sustained refused traffic
asserting bounded storage.

## Phase C — Operational integrity (R2 H1, H4)

1. **Seed upgrade path (H1).** `scripts/seed_demo_hunt.py` inserts
   `DEMO_PRINCIPAL_ID` *before* deleting the stale singleton, so the unique index
   trips and an existing real-account Demo installation cannot be upgraded — and
   preflight then refuses the old row for having an `auth.users` record. Fix:
   one transaction that disables demo, reconciles/deletes the stale marker,
   upserts the virtual principal, asserts no matching `auth.users` row, and runs
   preflight. The obsolete Auth user is removed through an audited path or
   explicitly reported — never silently stranded. Add an upgrade test starting
   from a different singleton bound to a real Auth user.
2. **Atomic toggle + audit (H4).** `PATCH /v1/admin/demo` commits
   `set_demo_enabled` and only then inserts the Admin Audit Log row through a
   separate pool call. Fold both into one transaction (audit insert moved into
   the function, actor validated by the API). Constraint that must survive:
   **emergency disable must never be blockable** — if the audit write can fail
   the disable, we need an explicitly ratified fallback that emits external
   alerting instead. Test: audit failure rolls the setting back.
3. Generation bump (Phase A.4) happens inside this same transaction.

## Phase D — DESIGN conflicts requiring an Owner ruling

Per AGENTS.md these stop implementation rather than get picked silently.

1. **Ordinary-user Storage posture (R2 H5) — RULED 2026-08-06: enforce.**
   DESIGN §8.3 wins: "signed-URL access is granted only in an authenticated Hunt
   context containing that Property." `private.demo_readable_storage_object()`
   loses its `return true` shortcut for non-demo subjects; the object key maps
   to `property_images.property_id` and is authorized by ordinary Hunt
   visibility, with the demo predicate ANDed on top. Malformed keys keep failing
   closed. Safe to widen: the frontend signs with the caller's JWT
   (`features/listings/api.ts:485`), so Storage RLS already governs signing,
   and the worker writes with the service role, which bypasses RLS — the upload
   and ENRICH paths are unaffected. Verify the Floor Plan diagram and drawer
   carousel still render for a real Curator as part of Phase G.
2. **`/demo/config` (R2 M2).** §16 says the session endpoint is the only
   unauthenticated public route; it is not. Fold config into a rate-limited
   session attempt, or amend §16 and log the decision.
3. **`demo_context()` breadth (R2 M3).** It returns `enabled` and `hunt_id` to
   every authenticated caller; the stated need was "am I demo?". Narrow to
   claim-holders, or ratify.

## Phase E — Frontend honesty (R2 M4, M5)

1. `isDemo()` trusts the mere presence of any value under `manzil-demo-token`.
   Validate shape and expiry client-side (UX only — the server stays
   authoritative), clear malformed/expired values, and handle 401 by visibly
   exiting or reissuing.
2. `apiFetch()` resolves every demo unsafe request as `undefined`. Only
   comments, ratings, pins and Visit entries simulate meaningfully; other hooks
   may dereference the result (`usePatchUnitGroupState` does so in `onSuccess`)
   or show success with no visible change. Inventory every visible Curator
   mutation and give each either typed synthetic returns or a consistent
   "Demo only — nothing saved" result. Component tests for Overrides, fees,
   utilities, Interest Status, listing state, comment edit/delete, Visit
   defects and custom items, and checkpoint/job actions — not just the fetch seam.

## Phase F — DM-9: Replay Capture and maps

1. `manzil export-demo-capture <job_id>` — a worker CLI command writing a real
   run's `job_events` timeline plus finished read payload to a static bundle.
   **RULED 2026-08-06:** a fresh real ingest is run for this; the spend is
   accepted. The URL should be one that produces a good timeline, ideally
   including a checkpoint, since DM-9's acceptance requires the replay to
   animate one. The Owner submits it; I export from the resulting Job.
2. Browser `useDemoReplay` driving the existing Tasks UI unchanged; the
   substitution disclosed *before* the visitor confirms.
3. Pre-captured map statics; `loadGoogleMaps()` never called under demo.
4. Acceptance: a demo submission animates stages including a checkpoint and
   creates **zero** `jobs` / `job_events` / `job_stage_costs` rows;
   `maps.googleapis.com` never appears in the network panel.

## Phase G — DM-8: the adversarial pass (R1 H4, R2 H6)

A runnable harness, not more API-level unit tests — R1 is explicit that
API-level tests do not count as evidence for any DM-8 item. Against a fresh,
fully migrated, *enabled* database, driving real HTTP with a real minted token:

- issuance through the real service-role RPC and the real HTTP route;
- PostgREST: in-scope and out-of-scope reads, `cleaned_text`, global facts;
- Storage HTTP: list, in-scope download, out-of-scope download by exact key;
- GoTrue: `/user`, `updateUser`, MFA, logout, reauthenticate → `user_not_found`;
- Realtime: live subscription behaviour across disable and generation rotation;
- every cost-bearing RPC → `42501`, with zero Job / event / cost / external-call
  side effects asserted;
- marker deletion, duplication and mismatch → fail closed (Phase A);
- concurrent issuance and bounded telemetry (Phase B);
- kill switch driven with already-issued access tokens and live subscriptions;
- the *observed* behaviour of a ban on a live token written into the runbook.

Also in this phase: fix the fresh-database fixture defect R2 found —
`test_demo_reads_are_scoped_to_the_demo_hunt` relies on ambient seed data for an
out-of-scope Property and must create its own. And pin the observed privilege
contract (`service_role` may execute `issue_demo_session`, `authenticated` may
not) as a catalogue assertion.

Evidence lands in `docs/demo-mode-dm8-evidence.md`.

## Phase H — Hosted Auth verification (R1 H5)

An executable checker (not dashboard screenshots) asserting on the hosted
project: signup disabled, anonymous signup disabled, manual linking disabled,
secure password change enabled, exact redirect allow-list, JWT TTL, SMTP and
rate limits, email-change confirmation — plus behavioural probes for
unknown-email signup, OTP, and recovery. **Blocked on a hosted/staging project
existing.** Written now, run when one does; the deployed TTL value is recorded
in DM-8 evidence.

## Docs owed on completion

DESIGN §16 (+ §8.3 if Phase D.1 rules that way) and a §20 Decision Log entry per
material change; IMPLEMENTATION §7 DM rows and a version entry; the demo runbook
(kill switch, generation rotation, telemetry retention, ban behaviour).

## Owner rulings, 2026-08-06

1. **Storage posture** — enforce Hunt context for *every* authenticated user.
   DESIGN §8.3 stands; no ratification of the global-image posture. (Phase D.1)
2. **DM-9 capture** — run a fresh real listing to capture from; the cost is
   accepted. (Phase F.1)
3. **Hosted Auth** — no staging project; Phase H ships as an unrun script and is
   recorded as owed evidence blocking enablement.
4. **TTL ceiling** — 30 minutes hard maximum, failing startup above it.
   (Phase A.5)

Still open, and not blocking: whether emergency disable may ever be blocked by
an audit-write failure (Phase C.2) — I will implement disable as unblockable and
flag it if that turns out to conflict with the Admin Audit Log contract.
