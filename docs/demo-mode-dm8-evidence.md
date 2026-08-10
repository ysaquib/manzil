# DM-8 adversarial pass — evidence

Run: 2026-08-10T01:30:38.289281-04:00
Target: `https://glpbxuslcrnnegbdnwml.supabase.co`
API plane: `https://api.manzil.yusufsaquib.com`
Demo principal: `ac8d9199-be47-4d23-b0a3-9b9ce528b316` · Demo Hunt: `b10950c6-e4c8-4c20-a3f2-9011a8605a86`

Produced by `scripts/dm8_adversarial.py`, which drives PostgREST, Storage,
GoTrue, Realtime and FastAPI over HTTP with a token minted exactly as a
visitor's is. API-level tests do not count as evidence for DM-8; nothing
here uses a TestClient or an in-process import.

**52 of 52 attempted checks passed.**

Every block below opens with a *precondition* row: the token was re-minted
at the database's current demo generation and proved to read the Demo Hunt
**before** anything was asserted about what it cannot do. A refusal recorded
without that control is not evidence — finding `R1` was exactly a harness
reporting PASS for a token that had already gone dark for an unrelated reason.

| Plane | Check | Result | Detail |
|---|---|---|---|
| Self-test | precondition: the token reads the Demo Hunt before the security checks run | ✅ | GET /properties?id=eq.<in-scope> -> 200, 1 rows |
| Self-test | a validly-signed token at a stale generation reads nothing | ✅ | 0 Properties visible at generation 29 while the database is at 30 |
| PostgREST | precondition: the token reads the Demo Hunt before reading global facts | ✅ | GET /properties?id=eq.<in-scope> -> 200, 1 rows |
| PostgREST | only Demo Hunt Properties are visible | ✅ | 1 Properties visible; in-scope present, out-of-scope absent |
| PostgREST | asking for an out-of-scope Property by id returns nothing | ✅ | 200 [] |
| PostgREST | cleaned_text is not selectable | ✅ | 403 — column grant revoked for authenticated |
| PostgREST | only the Demo Hunt is visible | ✅ | visible hunts: ['b10950c6-e4c8-4c20-a3f2-9011a8605a86'] |
| PostgREST | precondition: the token reads the Demo Hunt before attempting writes | ✅ | GET /properties?id=eq.<in-scope> -> 200, 1 rows |
| PostgREST | INSERT into comments is refused | ✅ | 403 (42501 insufficient_privilege) |
| PostgREST | INSERT into hunt_listings is refused | ✅ | 403 (42501 insufficient_privilege) |
| PostgREST | INSERT into properties is refused | ✅ | 403 (42501 insufficient_privilege) |
| PostgREST | INSERT into site_settings is refused | ✅ | 403 (42501 insufficient_privilege) |
| PostgREST | INSERT into demo_accounts is refused | ✅ | 403 (42501 insufficient_privilege) |
| PostgREST | a zero-row DELETE is still refused | ✅ | 403 — the statement guard fires on statements, not rows |
| PostgREST | precondition: the token reads the Demo Hunt before calling the cost-bearing RPCs | ✅ | GET /properties?id=eq.<in-scope> -> 200, 1 rows |
| PostgREST | submit_listing refuses a demo subject at entry | ✅ | 403 42501 (assert_not_demo, at entry) |
| PostgREST | answer_job_checkpoint refuses a demo subject at entry | ✅ | 403 42501 (assert_not_demo, at entry) |
| PostgREST | set_listing_source_policy refuses a demo subject at entry | ✅ | 403 42501 (assert_not_demo, at entry) |
| PostgREST | correct_auto_resolved_checkpoint refuses a demo subject at entry | ✅ | 403 42501 (assert_not_demo, at entry) |
| PostgREST | no Job, Job Event or cost row was created | ✅ | jobs 2→2, events 1→1, costs 0→0 |
| Storage | precondition: the token reads the Demo Hunt before reaching for objects | ✅ | GET /properties?id=eq.<in-scope> -> 200, 1 rows |
| Storage | listing the bucket does not reveal out-of-scope objects | ✅ | 200, 1 entries; no out-of-scope Property id present |
| Storage | signing an in-scope object succeeds | ✅ | 200 for properties/2c50abbf-25dd-4c45-aaff-e64642d2abaa/dm8e12a616f.webp |
| Storage | signing an out-of-scope object is refused | ✅ | 400 for properties/06b34c7d-766b-43e2-891c-0f4fca3eeb5f/dm8aab1ba02.webp |
| GoTrue | precondition: the token reads the Demo Hunt before probing the account endpoints | ✅ | GET /properties?id=eq.<in-scope> -> 200, 1 rows |
| GoTrue | GET /user is refused | ✅ | 403 |
| GoTrue | PUT /user (password) is refused | ✅ | 403 |
| GoTrue | PUT /user (email) is refused | ✅ | 403 |
| GoTrue | POST /logout (global) is refused | ✅ | 403 |
| GoTrue | POST /reauthenticate is refused | ✅ | 403 |
| GoTrue | POST /factors (MFA enrol) is refused | ✅ | 403 |
| Realtime | precondition: the token reads the Demo Hunt before subscribing | ✅ | GET /properties?id=eq.<in-scope> -> 200, 1 rows |
| Realtime | a change in the Demo Hunt reaches a subscribed demo token | ✅ | subscribed=True; a service-role INSERT into comments was delivered over the websocket |
| Realtime | with the switch off, a token minted at the current generation receives nothing | ✅ | subscribed=True; the same INSERT was NOT delivered; the only inconsistency in this token is demo_enabled = false |
| Realtime | after a generation rotation, a pre-rotation token receives nothing | ✅ | subscribed=True; the INSERT was NOT delivered; demo enabled and the marker intact, so the stale generation alone darkens it |
| FastAPI | GET /v1/demo/config reports the demo as available | ✅ | 200 {"enabled":true} (cached briefly; the cache gates the button, never access) |
| FastAPI | POST /v1/demo/session mints a token over real HTTP | ✅ | 200 |
| FastAPI | the issued token carries the demo claim and a generation | ✅ | gen=32, ttl=1800s |
| FastAPI | the issued TTL is within the bounded range | ✅ | 1800s (bound: 60..1800) |
| FastAPI | precondition: the token reads the Demo Hunt before an unsafe route is called | ✅ | GET /properties?id=eq.<in-scope> -> 200, 1 rows |
| FastAPI | an unsafe route answers 403 demo_read_only | ✅ | 403 {"detail":"Demo mode is read-only. Nothing you change here is saved.","code":"de |
| Issuance | 25 concurrent callers cannot exceed a global ceiling of 5 | ✅ | 4 issued of 4 concurrent attempts (without the advisory lock this over-issues under READ COMMITTED) |
| Issuance | sixty requests on one client key add at most two counter rows | ✅ | 1 new counter rows after 60 requests on a single key (the old per-request log added one row each) |
| Kill switch | precondition: the token reads the Demo Hunt before the marker row is deleted | ✅ | GET /properties?id=eq.<in-scope> -> 200, 1 rows |
| Kill switch | deleting the marker row darkens a live token | ✅ | 0 Properties visible with no demo_accounts row (before the C1 fix: every Property in the database) |
| Kill switch | precondition: the token reads the Demo Hunt before the singleton names another subject | ✅ | GET /properties?id=eq.<in-scope> -> 200, 1 rows |
| Kill switch | a singleton naming a different subject darkens the token | ✅ | 0 Properties visible |
| Kill switch | precondition: the token reads the Demo Hunt before the demo is switched off | ✅ | GET /properties?id=eq.<in-scope> -> 200, 1 rows |
| Kill switch | switching the demo off darkens a token minted at the current generation | ✅ | 0 Properties visible; marker intact and generation current, so demo_enabled = false is the only inconsistency |
| Kill switch | precondition: the token reads the Demo Hunt before a disable/re-enable cycle | ✅ | GET /properties?id=eq.<in-scope> -> 200, 1 rows |
| Kill switch | a token issued before a disable does not revive after re-enabling | ✅ | disabled: 0 rows; re-enabled with the old token: 0 rows; freshly minted: 1 rows |
| Kill switch | a token signed with the wrong secret is rejected outright | ✅ | PostgREST refused the forged token (HTTP error rather than an empty result) |

## Observed behaviour worth recording in the runbook

- **A ban is not a control.** GoTrue honours `PUT /auth/v1/user` for any
  validly-signed JWT, banned or not (DESIGN §20 v3.55). The demo principal
  is safe because it has no `auth.users` row at all, which is why every
  GoTrue probe above answers `user_not_found` rather than `user_banned`.
- **Disabling is a revocation.** Every toggle rotates
  `site_settings.demo_generation`, so tokens issued before a disable stay
  dark after a re-enable rather than resuming until `exp`. The two effects
  are separated above: one check mints *after* the toggle so only the
  switch can darken it, another keeps a pre-rotation token so only the
  generation can.
- **Losing the marker row is safe.** Deleting `demo_accounts` mid-session
  darkens live tokens instead of promoting them to ordinary readers.
- **The RPC guards are entry guards.** Each of the four refusals above was
  attributed to `private.assert_not_demo` by the error detail naming the
  function. The statement trigger would also refuse these calls, with the
  same status and SQLSTATE — which is why the weaker assertion cannot tell
  whether DESIGN §16 control 4 still exists.
