# Production deployment checklist

**Companion to:** [production-deployment-render-supabase.md](./production-deployment-render-supabase.md)

**Last verified:** 2026-08-03

Use this document as the chronological operator checklist. The companion runbook holds rationale, warnings, and reference tables.

**Order:** staging first, then production. Never promote staging credentials or database contents into production.

---

## Phase 0 — Prerequisites

### Accounts

- [x] GitHub — Manzil repo pushed (private)
- [x] Render — connected to GitHub
- [x] Supabase — MFA enabled
- [x] OpenRouter — production key + spend limit/alert
- [x] Langfuse Cloud — production project + key pair
- [x] Google Cloud — two separately restricted Maps keys
- [x] Bright Data or ScrapingBee — Tier-3 fetch provider
- [x] SMTP provider — Resend, Postmark, SES, or SendGrid
- [x] Private object store — for the 97 MB ONNX archive
- [x] DNS provider — for final domain



### Names and regions

Pick one region for Render and Supabase (close to each other and expected users).


| Resource            | Example             |
| ------------------- | ------------------- |
| Supabase staging    | `manzil-staging`    |
| Supabase production | `manzil-production` |
| Render project      | `Manzil`            |
| Render frontend     | `manzil-web`        |
| Render API          | `manzil-api`        |
| Frontend domain     | `app.example.com`   |
| API domain          | `api.example.com`   |


Do **not** use `api.example.com` for Supabase. A paid Supabase custom domain, if added later, should use a distinct name such as `data.example.com`.

### Repository infrastructure (before launch)

- [ ] Production multi-stage Dockerfile (uv workspace, `manzil-api[vision-onnx]`, Playwright Chromium, ONNX archive)
- [ ] `.dockerignore` (excludes `.env`, local/eval fixtures, caches; retains workspace packages)
- [ ] ONNX archive uploaded to private object store with stable authenticated URL
- [ ] GitHub Actions `production` environment secret `MANZIL_CLIP_ARCHIVE_URL` set to that authenticated HTTPS URL (required by `docker-api-image`)
- [ ] GitHub Actions `deploy-production-db` job added to CI
- [ ] (After manual deploy is proven) `render.yaml` committed

---



## Phase 1 — Supabase (staging first)



### 1.1 Create staging project

- [x] Dashboard → New project → `manzil-staging`
- [x] Choose closest practical region
- [x] Generate strong database password → store in password manager
- [x] Use Supabase Pro for real production (backups, no auto-pause)



### 1.2 Record credentials (never commit)


| Value                     | Dashboard source                        | Destination                                       |
| ------------------------- | --------------------------------------- | ------------------------------------------------- |
| Project ref               | Project URL                             | GitHub `SUPABASE_PROJECT_ID` (production)         |
| Database password         | Chosen at creation                      | GitHub secret; inside pooler URL                  |
| Project URL               | Settings → API                          | `SUPABASE_URL`; `VITE_SUPABASE_URL`               |
| Publishable key           | Settings → API Keys                     | `SUPABASE_ANON_KEY`; `VITE_SUPABASE_ANON_KEY`     |
| Legacy `service_role` JWT | Legacy API Keys                         | `SUPABASE_SERVICE_ROLE_KEY` (API only, temporary) |
| Session pooler URL        | Connect → Session pooler, port **5432** | `DATABASE_URL`                                    |


`DATABASE_URL` **must be Supavisor session-mode on port 5432:**

```text
postgresql://postgres.<project-ref>:<password>@aws-<region>.pooler.supabase.com:5432/postgres
```

Do **not** use:

- Direct `db.<ref>.supabase.co:5432` (IPv6; Render is IPv4-only)
- Supavisor transaction mode on port `6543`
- The Supabase API URL as `DATABASE_URL`

If the password has URL-significant characters, copy the exact URL from Supabase or percent-encode the password.

### 1.3 Apply schema

```bash
export SUPABASE_ACCESS_TOKEN='from dashboard account tokens'
export SUPABASE_DB_PASSWORD='staging database password'
supabase link --project-ref '<staging-project-ref>'
supabase db push --dry-run
supabase db push
supabase migration list
```

- [ ] Dry-run reviewed
- [ ] Push succeeded
- [ ] Migration list matches expectations

Rules:

- Never run `supabase db reset --linked` on hosted projects
- Never use `--include-seed`
- Never edit applied migrations
- Do not make schema changes in the Dashboard after adopting migrations



### 1.4 Configure Auth

**Authentication → Providers → Email:**

- [x] Email enabled
- [x] **Allow new users to sign up** disabled
- [x] Confirm email enabled
- [x] Anonymous sign-ins disabled

**Authentication → URL Configuration:**

- [x] Site URL set (e.g. `https://app.example.com`)
- [x] Redirect URLs added:

```text
https://app.example.com/auth/callback
https://app.example.com/auth/reset-password
https://app.example.com/invite/**
```

**Authentication → Emails → SMTP Settings:**

- [x] Custom SMTP enabled
- [x] Provider host, port, credentials, From address/name entered
- [x] SPF/DKIM verified at SMTP provider
- [ ] Click/link tracking disabled for Auth mail
- [ ] Magic-link, invite, and password-recovery templates reviewed
- [ ] Test messages sent in staging
- [ ] Rate limits reviewed

Do **not** run `supabase config push` from the repo (local URLs in `config.toml`).

### 1.5 Bootstrap primordial Site Admin

- [x] Create or invite owner email in Authentication → Users
- [x] Complete password setup
- [x] Run in SQL Editor (replace email):

```sql
insert into public.site_admins (user_id, is_primordial, note)
select id, true, 'Production system owner'
from auth.users
where email = 'you@example.com';
```

- [x] Confirm exactly one primordial row:

```sql
select u.email, sa.is_primordial, sa.granted_at
from public.site_admins sa
join auth.users u on u.id = sa.user_id;
```

Future accounts must be provisioned through **Admin → People**, not SQL.

### 1.6 Repeat for production

Only after staging is working:

- [x] Create `manzil-production` (Supabase Pro)
- [x] Record credentials
- [x] Apply schema
- [x] Configure Auth
- [x] Bootstrap primordial admin

---



## Phase 2 — Package the ONNX model



### 2.1 Create archive locally

```bash
tar -C worker/tests/fixtures/vision_benchmark/models/clip-vision-onnx-uint8 \
  -czf /tmp/manzil-clip-vision-uint8.tar.gz \
  model.onnx manifest.json
```



### 2.2 Upload to private storage

- [x] Archive uploaded to private object store or authenticated release location
- [x] Stable URL available for Render build secret `MANZIL_CLIP_ONNX_ARCHIVE_URL`
- [x] URL is stable across automatic deploys (not short-lived signed URLs unless CI refreshes them)



### 2.3 Verify in build

Build must extract the archive and print this digest:

```text
af06481c9b95daa042c9d89f7c2412c845f98aca3706e1cc2d23e7dad853a00b
```

```bash
uv sync --frozen --package manzil-api --extra vision-onnx --no-dev
mkdir -p .manzil/models/clip-vision-uint8
curl -fL --retry 5 "$MANZIL_CLIP_ONNX_ARCHIVE_URL" \
  -o /tmp/manzil-clip-vision-uint8.tar.gz
tar -xzf /tmp/manzil-clip-vision-uint8.tar.gz \
  -C .manzil/models/clip-vision-uint8
uv run --no-sync --package manzil-api python -c \
  'from pathlib import Path; from manzil_worker.vision_onnx import artifact_digest; print(artifact_digest(Path(".manzil/models/clip-vision-uint8")))'
```

Runtime variable: `MANZIL_IMAGE_CLASSIFY_ONNX_DIR=.manzil/models/clip-vision-uint8`

Full artifact contract: [onnx-image-classification.md](./onnx-image-classification.md)

---



## Phase 3 — Connect GitHub to Render

- [x] Render → Account/Workspace Settings → Git Providers
- [x] Connect GitHub and authorize the Render app
- [x] Grant access to Manzil repo only (if practical)
- [x] Create Render project **Manzil** (staging + production environments if available)
- [x] Create production-scoped Environment Group for API secrets (do not link secrets to static site)

Use the **connected repository** flow, not public Git URL.

---



## Phase 4 — Create API Web Service (staging)

Dashboard → **New → Web Service** → Manzil repo.


| Setting        | Value                    |
| -------------- | ------------------------ |
| Name           | `manzil-api`             |
| Branch         | `main`                   |
| Region         | Closest to Supabase      |
| Root directory | *(blank — repo root)*    |
| Runtime        | **Docker** (recommended) |
| Instance       | **Standard (2 GB)**      |
| Health check   | `/v1/health`             |
| Auto-deploy    | After CI Checks Pass     |
| Instances      | **exactly 1**            |


**Start command:**

```bash
uv run --no-sync --package manzil-api uvicorn manzil_api.main:app \
  --host 0.0.0.0 --port "$PORT" --workers 1
```

Do **not** increase Uvicorn workers or Render instances.

### 4.1 API environment variables


| Variable                                 | Value                                | Secret?         |
| ---------------------------------------- | ------------------------------------ | --------------- |
| `DATABASE_URL`                           | Session pooler URL, port 5432        | yes             |
| `SUPABASE_URL`                           | `https://<ref>.supabase.co`          | no              |
| `SUPABASE_ANON_KEY`                      | Publishable key                      | no              |
| `SUPABASE_SERVICE_ROLE_KEY`              | Legacy JWT service_role              | **yes**         |
| `MANZIL_WORKER_INPROCESS`                | `true`                               | no              |
| `API_ENVIRONMENT`                        | `production`                         | no              |
| `API_CORS_ORIGINS`                       | `https://app.example.com`            | no              |
| `MANZIL_FRONTEND_URL`                    | `https://app.example.com`            | no              |
| `MANZIL_MODE`                            | `workflow`                           | no              |
| `MANZIL_LLM_MODE`                        | `live`                               | no              |
| `MANZIL_IMAGE_CLASSIFY_ONNX_DIR`         | `.manzil/models/clip-vision-uint8`   | no              |
| `MANZIL_CLIP_ONNX_ARCHIVE_URL`           | Model archive URL                    | **yes** (build) |
| `OPENROUTER_API_KEY`                     | Production-scoped key                | **yes**         |
| `LANGFUSE_PUBLIC_KEY`                    | Production project                   | sensitive       |
| `LANGFUSE_SECRET_KEY`                    | Production project                   | **yes**         |
| `LANGFUSE_HOST`                          | e.g. `https://us.cloud.langfuse.com` | no              |
| `GOOGLE_MAPS_API_KEY`                    | Server-side key                      | **yes**         |
| `MANZIL_TIER3_PROVIDER`                  | `brightdata` or `scrapingbee`        | no              |
| `BRIGHTDATA_API_KEY` / `BRIGHTDATA_ZONE` | If Bright Data — zone name, **not** the key's name | yes / yes |
| `SCRAPINGBEE_API_KEY`                    | If ScrapingBee                       | **yes**         |


Do **not** set `MANZIL_MODEL_`* overrides in production.

- [ ] All required variables set
- [ ] No server secrets on the static site



### 4.2 Google Maps keys

- [x] `GOOGLE_MAPS_API_KEY` — server-side, API service only, restricted to server Maps APIs
- [x] `VITE_GOOGLE_MAPS_API_KEY` — browser key, referrer-restricted to `https://app.example.com/*`
- [x] Budgets and alerts configured
- [x] No IP restriction on server key until stable egress exists

---



## Phase 5 — Create frontend Static Site (staging)

Dashboard → **New → Static Site** → same repo.


| Setting           | Value                                          |
| ----------------- | ---------------------------------------------- |
| Name              | `manzil-web`                                   |
| Branch            | `main`                                         |
| Root directory    | `frontend`                                     |
| Build command     | `pnpm install --frozen-lockfile && pnpm build` |
| Publish directory | `dist`                                         |
| Auto-deploy       | After CI Checks Pass                           |


**SPA rewrite (required):**


| Source | Destination   | Action  |
| ------ | ------------- | ------- |
| `/*`   | `/index.html` | Rewrite |




### 5.1 Frontend build variables


| Variable                   | Value                       |
| -------------------------- | --------------------------- |
| `VITE_SUPABASE_URL`        | `https://<ref>.supabase.co` |
| `VITE_SUPABASE_ANON_KEY`   | Publishable key             |
| `VITE_API_BASE_URL`        | `https://api.example.com`   |
| `VITE_GOOGLE_MAPS_API_KEY` | Browser-restricted key      |
| `VITE_APP_VERSION`         | Optional commit/release ID  |


Vite values are compiled at build time — changing one requires **Save, rebuild, and deploy**.

- [x] All build variables set
- [x] No server secrets on static site

---



## Phase 6 — GitHub Actions migration gate



### 6.1 Protect `main`

- [ ] Require pull requests
- [ ] Require CI checks
- [ ] Disallow force pushes
- [ ] Require resolved conversations
- [ ] (Optional) Signed commits and CODEOWNERS for migrations/deployment config



### 6.2 Create GitHub `production` environment

**Secrets:**

- [x] `SUPABASE_ACCESS_TOKEN`
- [x] `SUPABASE_DB_PASSWORD`

**Variable:**

- [x] `SUPABASE_PROJECT_ID` = production project ref

(Optional) Require reviewer before deploy.

### 6.3 Add `deploy-production-db` job

Add to `.github/workflows/ci.yml` (or equivalent), gated on CI success:

```yaml
deploy-production-db:
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  needs: [lint, typecheck, test, collaboration-security, frontend]
  runs-on: ubuntu-latest
  environment: production
  concurrency:
    group: production-database
    cancel-in-progress: false
  env:
    SUPABASE_ACCESS_TOKEN: ${{ secrets.SUPABASE_ACCESS_TOKEN }}
    SUPABASE_DB_PASSWORD: ${{ secrets.SUPABASE_DB_PASSWORD }}
    SUPABASE_PROJECT_ID: ${{ vars.SUPABASE_PROJECT_ID }}
  steps:
    - uses: actions/checkout@v7
    - uses: supabase/setup-cli@v3
      with:
        version: 2.98.2
    - run: supabase link --project-ref "$SUPABASE_PROJECT_ID"
    - run: supabase db push --dry-run
    - run: supabase db push
    - run: supabase migration list
```

- [ ] Job added and merged
- [ ] Both Render services set to **After CI Checks Pass**

---



## Phase 7 — Custom domains



### 7.1 Frontend

- [x] `manzil-web` → Settings → Custom Domains → add `app.example.com`
- [x] Create CNAME at DNS provider
- [x] Verify in Render; wait for TLS



### 7.2 API

- [x] `manzil-api` → Settings → Custom Domains → add `api.example.com`
- [x] Create CNAME at DNS provider
- [x] Verify in Render; wait for TLS

Keep Cloudflare proxying **off** until verification succeeds. If CAA records exist, permit `letsencrypt.org` and `pki.goog`.

### 7.3 Update all origin references

After domains are live, update and **redeploy/rebuild**:

- [x] API `API_CORS_ORIGINS=https://app.example.com`
- [x] API `MANZIL_FRONTEND_URL=https://app.example.com`
- [x] Frontend `VITE_API_BASE_URL=https://api.example.com`
- [x] Supabase Auth Site URL and redirect allow-list
- [x] Google browser-key referrer restrictions
- [x] SMTP/email branding and links

---



## Phase 8 — Staging acceptance

Run in order. All must pass before production.

- [ ] 1. `GET /v1/health` → `{"status":"ok"}`
- [ ] 2. `/openapi.json` visible in staging (hidden when `API_ENVIRONMENT=production`)
- [ ] 3. Deep link such as `/admin` loads (no SPA 404)
- [ ] 4. Unknown-email sign-up/OTP cannot create an account
- [ ] 5. Primordial admin signs in and opens Admin → People
- [ ] 6. Second account provisioned via Admin → People; SMTP message and password redirect verified
- [ ] 7. Hunt, Rubric, and Listing created through UI
- [ ] 8. One Job claimed and progresses; no duplicate claimant
- [ ] 9. Langfuse receives every LLM call; OpenRouter charges staging-scoped key
- [ ] 10. Images land in private `property-images` Storage bucket
- [ ] 11. IMAGE_CLASSIFY emits `image_classify_onnx_complete`, correct digest, no LLM classifier call
- [ ] 12. Gallery displays ONNX scene and kitchen probability
- [ ] 13. Top three `kitchen_score` eligible images become VISION targets; anchored VISION result appears
- [ ] 14. Tier-2 Playwright fetch works (Chromium and Linux deps packaged)
- [ ] 15. Google Maps ENRICH and frontend map work with separate keys
- [ ] 16. Realtime and Visit Presence work with two browsers
- [ ] 17. API redeploy during queued Job → Job resumes at persisted Stage boundary
- [ ] 18. RLS verified (ordinary member, other Hunt, Site Admin Ghost View)
- [ ] 19. Supabase Security Advisor, logs, Render memory, OpenRouter spend, Langfuse traces reviewed

---



## Phase 9 — Production launch

- [ ] 1. Freeze merges briefly
- [ ] 2. Target commit green in GitHub Actions
- [ ] 3. Supabase Pro, MFA, SMTP, Auth signup gate, redirects, production secrets confirmed
- [ ] 4. Production migration workflow run; `migration list` inspected
- [ ] 5. Render API deployed; `/v1/health` and stable logs confirmed
- [ ] 6. Exactly one in-process worker claimant confirmed
- [ ] 7. Frontend deployed/rebuilt with final API and Supabase URLs
- [ ] 8. Custom-domain TLS and SPA rewrites verified
- [ ] 9. Primordial admin signed in
- [ ] 10. One real Listing run end-to-end (Job, Storage, ONNX, VISION, SCORE, costs, traces)
- [ ] 11. Intended users provisioned via Admin → People
- [ ] 12. Temporary staging/Render origins removed from production Auth and CORS
- [ ] 13. Merges unfrozen

---



## Phase 10 — Ongoing operations



### Rollback

- Render: rollback to prior deployment
- Database: migrations are **forward-only** — code rollback must match applied schema
- Never use `supabase db reset` on production
- If ONNX archive is missing or digest is wrong, fail the build; roll back to last known-good deployment



### Worker invariants

- `MANZIL_WORKER_INPROCESS=true`
- One Uvicorn worker, one Render instance
- Stale locks: Admin → Jobs release/requeue after confirming worker is gone



### Secret rotation

1. Create new key
2. Update staging → verify
3. Update production → redeploy
4. Verify health and one real operation
5. Revoke old key

Rotate immediately if any secret appears in git, logs, screenshots, or frontend build.

### Monitoring (minimum)

- [ ] Render — health, restarts, memory, deploy failures, logs
- [ ] Supabase — connections, Security Advisor, Auth failures, Storage, backups
- [ ] OpenRouter — balance, spend limits, errors
- [ ] Langfuse — missing traces, cost, latency, Stage failures
- [ ] Google Maps — budgets, unauthorized traffic
- [ ] Bright Data/ScrapingBee — credits
- [ ] Manzil Admin — failed, retrying, checkpointed, stale-lock Jobs

Note: `/v1/health` is liveness only. A separate readiness endpoint is recommended before relying on automated uptime checks alone.

---



## Secret placement quick reference


| Secret/value          | GitHub          | Render API        | Render frontend  | Supabase  |
| --------------------- | --------------- | ----------------- | ---------------- | --------- |
| Supabase access token | prod env secret | —                 | —                | source    |
| DB password           | prod env secret | in `DATABASE_URL` | never            | source    |
| `DATABASE_URL`        | —               | **secret**        | never            | source    |
| Publishable key       | —               | yes               | yes (public)     | source    |
| Service-role JWT      | —               | **secret**        | never            | source    |
| OpenRouter key        | —               | **secret**        | never            | —         |
| Langfuse key pair     | —               | **secret**        | never            | —         |
| Google server key     | —               | **secret**        | never            | —         |
| Google browser key    | —               | —                 | public build var | —         |
| Tier-3 provider key   | —               | **secret**        | never            | —         |
| ONNX archive URL      | —               | build secret      | never            | —         |
| SMTP password         | —               | —                 | —                | Auth SMTP |


No production secret in `.env`, `frontend/.env.local`, `render.yaml`, Dockerfile, workflow YAML, migration SQL, or Vite output.
