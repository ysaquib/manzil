# Production deployment: Render + Supabase

**Status:** deployment runbook; production infrastructure is not yet committed

**Last verified:** 2026-08-03

This runbook deploys the current Manzil architecture:

- a Render Static Site for the React/Vite frontend;
- one Render Web Service for FastAPI **and its in-process worker**;
- one hosted Supabase project for Postgres, Auth, Storage, Realtime, and RLS;
- the pinned ONNX artifact packaged into the API build;
- GitHub Actions as the pre-deploy quality and database-migration gate.

The intended production topology is:

```text
https://app.example.com             Render Static Site (frontend)
            |
            +-- HTTPS --> https://api.example.com
            |                    Render Web Service
            |                    FastAPI + exactly one Uvicorn process
            |                    + in-process durable Job worker
            |
            +-- HTTPS/WSS --> https://<project-ref>.supabase.co
                                 Auth + PostgREST + Realtime + Storage

Render API -- Supavisor session-mode :5432 --> Supabase Postgres
```

Do not create a separate Render Background Worker yet. The repository has no
standalone production worker entry point, and the current scheduler runs inside
the API lifespan. `MANZIL_WORKER_INPROCESS=true` and one Uvicorn worker are
therefore deployment invariants, not tuning suggestions.

## 1. What remains before production

The application features and PR-1 admin-only provisioning code have landed, but
the following deployment work remains:

1. Create separate hosted Supabase **staging** and **production** projects.
2. Add a production API Dockerfile or prove the equivalent Render native-runtime
   build. Docker is recommended because the worker needs Playwright Chromium,
   ONNX Runtime, and their Linux system libraries. The repository currently has
   no production API Dockerfile yet. The committed `render.yaml` owns the
   frontend service, rewrite, and security headers only.
3. Put the 97 MB ONNX archive in a private, stable object/release store and make
   it available during the Render build. Render secret files cannot hold the
   archive (their combined limit is 1 MB), but **must** hold the small download
   credential or authenticated URL used to fetch it. Do not put that secret in
   a Render environment variable: Docker services translate environment
   variables into build arguments, which risks retaining the credential in
   image metadata or a build layer.
4. Validate the API memory envelope on Render. The measured ONNX subprocess
   peak is about 213 MB before counting FastAPI, Python, and a possible
   Playwright browser. Render Free and Starter web instances currently have
   512 MB; use **Standard (2 GB)** for the initial deployment and downsize only
   after observing real Jobs.
5. Configure production Supabase Auth, redirects, custom SMTP, and the immutable
   primordial Site Admin.
6. Add the production database migration job to GitHub Actions.
7. Create the Render frontend and API services, connect the repository, add
   environment variables, and choose **After CI Checks Pass**.
8. Connect `app.example.com` and `api.example.com`, then update CORS, Auth URL
   configuration, Google Maps restrictions, and email templates to those final
   HTTPS origins.
9. Run the staging and production acceptance checklists in this document.
10. Migrate `SupabaseImageStore` from the legacy JWT `service_role` key to a
    current `sb_secret_...` key before Supabase disables legacy keys. The current
    raw Storage client sends the key in both `apikey` and Bearer headers, so this
    is an engineering change, not just an environment-variable swap.

Render documents its service, monorepo, health-check, environment, and domain
behavior in [Web Services](https://render.com/docs/web-services),
[Static Sites](https://render.com/docs/static-sites),
[Monorepo Support](https://render.com/docs/monorepo-support), and
[Custom Domains](https://render.com/docs/custom-domains). Supabase's production
baseline is its [Production Checklist](https://supabase.com/docs/guides/deployment/going-into-prod).

## 2. Accounts, regions, and names

Create or confirm these accounts:

- GitHub, with the Manzil repository pushed to a private repository;
- Render, connected to that GitHub organization/account;
- Supabase, with MFA enabled on the account;
- OpenRouter, with billing/credits and a production-scoped API key;
- Langfuse Cloud, with a production project and API key pair;
- Google Cloud, with Maps billing and two separately restricted keys;
- Bright Data Web Unlocker, or ScrapingBee if intentionally selected;
- an SMTP provider such as Resend, Postmark, SES, or SendGrid;
- a private object store or authenticated release location for the ONNX archive;
- a DNS provider for the final domain.

Choose the Render and Supabase regions geographically close to one another and
to the expected users. Give services unambiguous names, for example:

```text
Supabase: manzil-staging, manzil-production
Render project: Manzil
Render environments: staging, production
Render services: manzil-web, manzil-api
Domains: app.example.com, api.example.com
```

Do not use `api.example.com` for both FastAPI and a Supabase custom domain. If a
paid Supabase custom domain is later desired, use a distinct name such as
`data.example.com`. A Supabase custom domain is optional and is a paid add-on;
the default `<project-ref>.supabase.co` URL is correct for launch.

## 3. Create and configure hosted Supabase

### 3.1 Create the projects

In the Supabase Dashboard:

1. Create `manzil-staging` first.
2. Choose the closest practical region.
3. Generate a strong database password and store it in a password manager.
4. Repeat for `manzil-production` only after staging is working.
5. For a real production deployment, use Supabase Pro so the project does not
   pause and has daily backups. Free projects may pause after low activity and
   do not provide the same backup posture. See [Supabase pricing](https://supabase.com/pricing)
   and [Database Backups](https://supabase.com/docs/guides/platform/backups).

Record, without committing, these values for each environment:

| Value | Dashboard source | Destination |
|---|---|---|
| Project ref | Project URL/dashboard URL | GitHub `SUPABASE_PROJECT_ID` |
| Database password | the value chosen at project creation | GitHub `SUPABASE_DB_PASSWORD` only |
| Project URL | Connect or Settings → API | Render API `SUPABASE_URL`; frontend `VITE_SUPABASE_URL` |
| Publishable key | Settings → API Keys | Render API `SUPABASE_ANON_KEY`; frontend `VITE_SUPABASE_ANON_KEY` |
| Legacy `service_role` JWT | Settings → API Keys → Legacy API Keys | Render API `SUPABASE_SERVICE_ROLE_KEY` temporarily |
| Session pooler URL | Connect → Session pooler | Render API `DATABASE_URL` |

Supabase now recommends `sb_publishable_...` and `sb_secret_...` keys. The
publishable key can be used in Manzil's variables that retain the older
`*_ANON_KEY` names. Do **not** put an `sb_secret_...` value into the frontend.
For the server key, Manzil temporarily needs the legacy JWT `service_role` value
until the raw Storage code is adapted. Both server key types bypass RLS and must
never enter Vite variables, logs, screenshots, source control, or browser code.
See [Understanding API keys](https://supabase.com/docs/guides/getting-started/api-keys).

### 3.2 Use the correct Render database URL

Render is currently IPv4-only, while Supabase's direct database endpoint is
IPv6 unless an IPv4 add-on is purchased. For `DATABASE_URL`, copy the
**Supavisor session-mode** connection string on port `5432`:

```text
postgresql://postgres.<project-ref>:<password>@aws-<region>.pooler.supabase.com:5432/postgres
```

Do not use:

- the direct `db.<project-ref>.supabase.co:5432` URL on ordinary Render;
- Supavisor transaction mode on port `6543`, because asyncpg prepared-statement
  behavior and the long-lived worker pool make session mode the safer contract;
- the public Supabase API URL as `DATABASE_URL`.

Supabase documents the connection modes and Render's IPv4 limitation in
[Connect to your database](https://supabase.com/docs/guides/database/connecting-to-postgres)
and [IPv4/IPv6 compatibility](https://supabase.com/docs/guides/troubleshooting/supabase--your-network-ipv4-and-ipv6-compatibility-cHe3BP).

If the password contains URL-significant characters, use the exact URL copied
from Supabase or percent-encode the password. Never assemble it in a checked-in
file. Require TLS and certificate verification: retain the Dashboard URL's SSL
parameters, or append `sslmode=verify-full` (use `?sslmode=verify-full` when the
URL has no query string). Do not deploy with `sslmode=disable`, and do not use a
client setting that skips certificate verification. Test this exact URL from
staging before launch; a TLS failure is a deployment failure, not a reason to
weaken verification.

### 3.3 Apply the schema

From a clean checkout, using staging first:

```bash
export SUPABASE_ACCESS_TOKEN='from dashboard account tokens'
export SUPABASE_DB_PASSWORD='staging database password'
supabase link --project-ref '<staging-project-ref>'
supabase db push --dry-run
supabase db push
supabase migration list
```

Important rules:

- Never run `supabase db reset --linked` against staging or production. Remote
  reset is destructive.
- Do not use `--include-seed`. `supabase/seed.sql` is for local reset only;
  hosted Catalog changes arrive through committed catalog-sync migrations.
- Never edit an applied migration.
- After adopting migrations, do not make ordinary schema changes with the
  Dashboard SQL/Table editors. Supabase tracks deployed migrations separately
  and dashboard-only changes cause drift.
- Apply database migrations before deploying code that requires them.

The `property-images` private Storage bucket, its policy, RLS, functions,
Realtime publications, and Catalog rows are created by the committed
migrations. Verify rather than recreating them manually. Supabase's supported
workflow is documented in [Database Migrations](https://supabase.com/docs/guides/deployment/database-migrations).

### 3.4 Configure Auth

In Authentication settings for each hosted project:

1. Authentication → Providers → Email:
   - keep Email enabled;
   - disable **Allow new users to sign up** at the global account-creation gate;
   - enable Confirm email;
   - keep anonymous sign-ins disabled.
2. Authentication → URL Configuration:
   - Site URL: `https://app.example.com`;
   - add the narrow production redirects required by the implemented flows:

```text
https://app.example.com/auth/callback
https://app.example.com/auth/reset-password
https://app.example.com/invite/**
https://app.example.com/join/**
```

The two token-path wildcards are required because Hunt invites and managed
Invitation Links return to unique `/invite/<token>` and `/join/<token>` paths.
The callback entry must also accept the frontend's `?next=/invite/...` or
`?next=/join/...` query string; verify it with Supabase's redirect-URL glob
tester and, if an exact callback entry does not match query strings in the
hosted configuration, use the narrow
`https://app.example.com/auth/callback**` pattern. Do not use a blanket
production `/**` allow-list. Keep localhost redirects only in staging if they
are genuinely needed. Supabase recommends exact production paths in
[Redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls).

3. Authentication → Emails → SMTP Settings:
   - enable custom SMTP;
   - enter the provider host, port, username, password, From address, and From
     name;
   - verify the sending domain's SPF/DKIM records at the SMTP provider;
   - disable click/link tracking for Auth mail.
4. Review the magic-link, invite, and password-recovery templates. Preserve the
   link and token variables expected by the application. Send real staging
   messages before production.
5. Review Authentication → Rate Limits after SMTP is enabled.

Supabase's built-in mail server is not a production service and ordinarily
limits delivery to project-team addresses with a very low rate limit. See
[Custom SMTP](https://supabase.com/docs/guides/auth/auth-smtp).

Do not blindly run `supabase config push` from the current repository: the
committed `supabase/config.toml` contains local Site URLs and redirect URLs.
Hosted Auth configuration should remain a dashboard deployment step until the
repository gains environment-specific production config.

### 3.5 Bootstrap the primordial Site Admin

Public sign-up is intentionally disabled, so bootstrap exactly one account:

1. In Supabase Authentication → Users, create or invite the production owner
   email through the Dashboard's administrative path.
2. Complete password setup and confirm that the account exists.
3. In SQL Editor, run this once with the real email. The block fails rather
   than silently doing nothing if the email is wrong, refuses to create a
   second primordial admin, and refuses to bootstrap on top of a non-primordial
   first row:

```sql
do $$
declare
  target_user_id uuid;
begin
  select id into strict target_user_id
  from auth.users
  where lower(email) = lower('you@example.com');

  if exists (select 1 from public.site_admins) then
    raise exception 'site_admins is not empty; stop and investigate';
  end if;

  insert into public.site_admins (user_id, is_primordial, note)
  values (target_user_id, true, 'Production system owner');
end
$$;
```

4. Confirm that there is exactly one admin and it is the intended primordial
   account. Treat zero rows, multiple rows, the wrong email, or `false` as a
   failed bootstrap:

```sql
select u.email, sa.is_primordial, sa.granted_at
from public.site_admins sa
join auth.users u on u.id = sa.user_id;
```

The first/primordial admin is immutable. Subsequent accounts must be provisioned
through Manzil Admin → People, not the SQL editor.

## 4. Package the ONNX artifact

The required artifact is deliberately gitignored. Create the release archive
from the verified local model:

```bash
tar -C worker/tests/fixtures/vision_benchmark/models/clip-vision-onnx-uint8 \
  -czf /tmp/manzil-clip-vision-uint8.tar.gz \
  model.onnx manifest.json
```

Upload it to a private object store or authenticated release location. Put the
small download credential (or authenticated stable URL) in a Render **secret
file** named `manzil_clip_archive_url`; do not use an environment variable or
Docker `ARG`. It must be stable across automatic deploys; short-lived signed
URLs are unsuitable unless CI refreshes them before every build. Restrict the
credential to read-only access to this one object where the provider permits.

The Dockerfile must use a BuildKit secret mount in the same `RUN` instruction
that downloads and verifies the artifact, so the secret is absent from the
resulting image and intermediate layers. For example (the production
Dockerfile must also install `curl` and CA certificates):

```dockerfile
# syntax=docker/dockerfile:1.7
RUN --mount=type=secret,id=manzil_clip_archive_url \
    set -eu; \
    archive_url="$(cat /run/secrets/manzil_clip_archive_url)"; \
    mkdir -p .manzil/models/clip-vision-uint8; \
    curl --proto '=https' --tlsv1.2 --fail --location --retry 5 \
      "$archive_url" -o /tmp/manzil-clip-vision-uint8.tar.gz; \
    tar -xzf /tmp/manzil-clip-vision-uint8.tar.gz \
      -C .manzil/models/clip-vision-uint8 \
      --no-same-owner --no-same-permissions; \
    uv run --no-sync --package manzil-api python -c \
      'from pathlib import Path; from manzil_worker.vision_onnx import artifact_digest; expected="af06481c9b95daa042c9d89f7c2412c845f98aca3706e1cc2d23e7dad853a00b"; actual=artifact_digest(Path(".manzil/models/clip-vision-uint8")); assert actual == expected, f"ONNX artifact digest mismatch: {actual}"'; \
    rm -f /tmp/manzil-clip-vision-uint8.tar.gz
```

The build must fail unless the digest is:

```text
af06481c9b95daa042c9d89f7c2412c845f98aca3706e1cc2d23e7dad853a00b
```

Set runtime `MANZIL_IMAGE_CLASSIFY_ONNX_DIR` to:

```text
.manzil/models/clip-vision-uint8
```

No persistent disk is required for a build-time model: it becomes part of that
deployment's immutable filesystem. Render's runtime filesystem is otherwise
ephemeral. If a disk is used instead, note that Render disks are unavailable to
build/pre-deploy commands and prevent multi-instance scaling. See
[Render deploy filesystem behavior](https://render.com/docs/deploys) and
[Persistent Disks](https://render.com/docs/disks).

The full artifact contract is in `docs/onnx-image-classification.md`.

## 5. Connect GitHub to Render

In Render:

1. Dashboard → Account/Workspace Settings → Git Providers.
2. Connect GitHub and install/authorize the Render GitHub app.
3. Grant access only to the Manzil repository if practical.
4. Create a Render Project named `Manzil`, with staging and production
   environments if the selected plan supports them.
5. Create a production-scoped Environment Group for API secrets, or add secrets
   directly to the API service. Do not link API secrets to the static site.

Use the connected-repository flow, not the public Git URL flow. Connected repos
support automatic deploys and previews; public URL services do not.

For the initial launch, configuring the two services in the Dashboard is less
risky than inventing an untested Blueprint. Once the build is proven, commit a
`render.yaml` that mirrors it. Render Blueprints are rooted at `render.yaml` and
support `buildCommand`, `startCommand`, `healthCheckPath`, domains, build
filters, and `autoDeployTrigger: checksPass`; see the
[Blueprint specification](https://render.com/docs/blueprint-spec).

## 6. Create the Render API Web Service

Dashboard → New → Web Service → select the Manzil repository.

Use these settings:

| Setting | Value |
|---|---|
| Name | `manzil-api` |
| Branch | `main` |
| Region | closest practical region to Supabase |
| Root directory | leave blank/repository root |
| Runtime | Docker recommended; Python only after native build is proven |
| Instance | Standard, initially |
| Health check | `/v1/health` |
| Auto-deploy | After CI Checks Pass |
| Instances | exactly 1 |

The monorepo root must remain the build context because `uv.lock`, `shared/`,
`worker/`, and `api/` are all required. Do not set root directory to `api/`.
Use build filters later if desired; API rebuild inputs include at least:

```text
api/**
worker/**
shared/**
pyproject.toml
uv.lock
render.yaml
<production Dockerfile/build script>
```

The start command is exactly one process:

```bash
uv run --no-sync --package manzil-api uvicorn manzil_api.main:app \
  --host 0.0.0.0 --port "$PORT" --workers 1
```

Render requires the server to bind to `0.0.0.0` and the provided `PORT`. Do not
use Render's `WEB_CONCURRENCY` to increase Uvicorn workers: every process would
start another queue claimant and scheduler.

### 6.1 API environment variables

Add these under the API service's Environment page. Render makes environment
variables available during builds and runtime; secret values should be entered
in Render, never committed. See [Render environment variables and secrets](https://render.com/docs/configure-environment-variables).

| Variable | Value/source | Secret? | Required? |
|---|---|---:|---:|
| `PYTHON_VERSION` | a fully qualified supported Python 3.12 release | no | yes for native runtime |
| `DATABASE_URL` | Supabase Session pooler URL, port 5432 | yes | yes |
| `SUPABASE_URL` | `https://<project-ref>.supabase.co` | no | yes |
| `SUPABASE_ANON_KEY` | Supabase publishable key | public but configure here | yes |
| `SUPABASE_SERVICE_ROLE_KEY` | legacy JWT service-role key, temporarily | **yes** | yes |
| `MANZIL_WORKER_INPROCESS` | `true` | no | yes |
| `API_ENVIRONMENT` | `production` | no | yes |
| `API_CORS_ORIGINS` | `https://app.example.com` | no | yes |
| `MANZIL_FRONTEND_URL` | `https://app.example.com` | no | yes |
| `MANZIL_MODE` | `workflow` | no | yes |
| `MANZIL_LLM_MODE` | `live` | no | yes |
| `MANZIL_IMAGE_CLASSIFY_ONNX_DIR` | `.manzil/models/clip-vision-uint8` | no | yes |
| Render secret file `manzil_clip_archive_url` | authenticated stable model archive URL | **yes** | build-time yes |
| `OPENROUTER_API_KEY` | production-scoped OpenRouter key | **yes** | yes |
| `LANGFUSE_PUBLIC_KEY` | production Langfuse project | sensitive | yes |
| `LANGFUSE_SECRET_KEY` | production Langfuse project | **yes** | yes |
| `LANGFUSE_HOST` | region host, e.g. `https://us.cloud.langfuse.com` | no | yes |
| `GOOGLE_MAPS_API_KEY` | server-side Maps key | **yes** | yes for ENRICH |
| `MANZIL_TIER3_PROVIDER` | `brightdata` or `scrapingbee` | no | yes |
| `BRIGHTDATA_API_KEY` | Bright Data API token | **yes** | if Bright Data selected |
| `BRIGHTDATA_ZONE` | normally `web_unlocker1` | no | if Bright Data selected |
| `SCRAPINGBEE_API_KEY` | ScrapingBee key | **yes** | only if selected |

Do not set any `MANZIL_MODEL_*` overrides in production. Model pins are code and
DESIGN decisions. Do not add provider-vendor keys: OpenRouter is the sole LLM
gateway.

Create the OpenRouter key specifically for production and give it a bounded
spending limit/alert. OpenRouter keys and credits are described in its
[official FAQ](https://openrouter.ai/docs/faq). Create Langfuse keys under the
production project's settings; key pairs are project-scoped according to
[Langfuse's API documentation](https://langfuse.com/docs/api-and-data-platform/features/public-api).

### 6.2 Google Maps keys

Create two different Google keys:

- `GOOGLE_MAPS_API_KEY`: server-side key, stored only on the Render API;
- `VITE_GOOGLE_MAPS_API_KEY`: browser key compiled into the frontend.

Restrict the browser key by Website/HTTP referrer:

```text
https://app.example.com/*
```

and restrict it to Maps JavaScript API and the browser libraries the app uses.
Restrict the server key to the server-side Maps APIs used by ENRICH. Render does
not promise a fixed outbound IP by default, so do not add an IP restriction
until a stable-egress design exists. Set budgets and alerts. Google explicitly
recommends separate keys and both application/API restrictions in its
[Maps API security guidance](https://developers.google.com/maps/api-security-best-practices).

## 7. Create the Render frontend Static Site

Dashboard → New → Static Site → select the same repository.

Use:

| Setting | Value |
|---|---|
| Name | `manzil-web` |
| Branch | `main` |
| Root directory | `frontend` |
| Build command | `pnpm install --frozen-lockfile && pnpm build` |
| Publish directory | `dist` |
| Auto-deploy | After CI Checks Pass |

Add a Render rewrite for React Router:

| Source | Destination | Action |
|---|---|---|
| `/*` | `/index.html` | Rewrite |

Without it, direct visits and refreshes on `/admin`, `/h/...`, `/invite/...`,
and `/auth/...` return a static-site 404. See
[Static Site Redirects and Rewrites](https://render.com/docs/redirects-rewrites).

### 7.1 Frontend build variables

Every `VITE_*` value is public and recoverable from the built JavaScript.

| Variable | Value | Secret? |
|---|---|---:|
| `VITE_SUPABASE_URL` | `https://<project-ref>.supabase.co` | no |
| `VITE_SUPABASE_ANON_KEY` | Supabase publishable key | no |
| `VITE_API_BASE_URL` | `https://api.example.com` | no |
| `VITE_GOOGLE_MAPS_API_KEY` | referrer/API-restricted browser key | public by design |
| `VITE_APP_VERSION` | optional commit/release identifier | no |

Never place `DATABASE_URL`, the Supabase server key, OpenRouter, Langfuse
secret, Bright Data, SMTP, model archive credential, or server Maps key on the
Static Site.

Vite values are compiled at build time. Changing one requires **Save, rebuild,
and deploy**, not only a runtime restart.

## 8. GitHub Actions and deployment ordering

The existing `.github/workflows/ci.yml` already runs lint, typecheck, local
Supabase-backed API/worker tests, the RLS matrix, and frontend tests/build. Keep
CI token-free with `MANZIL_LLM_MODE=replay`.

Add a protected GitHub Environment named `production`, ideally with a required
reviewer. Add these **environment secrets**:

```text
SUPABASE_ACCESS_TOKEN
SUPABASE_DB_PASSWORD
```

Add this non-secret environment variable:

```text
SUPABASE_PROJECT_ID=<production project ref>
```

The access token comes from Supabase Dashboard → Account → Access Tokens. The
database password is the project-specific password. Supabase recommends these
as encrypted Actions secrets in its [Managing Environments](https://supabase.com/docs/guides/deployment/managing-environments)
guide.

Add a `deploy-production-db` job to the existing CI workflow, or an equivalent
workflow that cannot run before CI succeeds:

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

Then set both Render services to **After CI Checks Pass**. Render waits for all
GitHub checks on the commit; a failed database deployment therefore prevents
the application deploy. Render documents this option in
[Deploying on Render](https://render.com/docs/deploys).

Protect `main` in GitHub:

- require pull requests;
- require the existing CI checks;
- disallow force pushes;
- require conversations to resolve;
- optionally require signed commits and CODEOWNERS review for migrations and
  deployment configuration.

Do not store Render runtime secrets in GitHub unless a workflow needs them. Do
not store Supabase migration credentials in Render. Each platform should hold
only the credentials it consumes.

## 9. Connect custom domains

### 9.1 Frontend

In `manzil-web` → Settings → Custom Domains:

1. Add `app.example.com`.
2. At the DNS provider, create the exact CNAME target Render displays.
3. Return to Render and click Verify.
4. Wait for managed TLS issuance.

### 9.2 API

In `manzil-api` → Settings → Custom Domains:

1. Add `api.example.com`.
2. Add the Render-provided CNAME at the DNS provider.
3. Verify and wait for TLS.

Render automatically redirects HTTP to HTTPS and manages certificates. If CAA
records exist on the domain, permit `letsencrypt.org` and `pki.goog` as Render
documents. Keep Cloudflare proxying disabled until Render verification and TLS
work; enable it later only after following Render's Cloudflare-specific rules.

After the domains are live, update and rebuild/redeploy:

- API `API_CORS_ORIGINS=https://app.example.com`;
- API `MANZIL_FRONTEND_URL=https://app.example.com`;
- frontend `VITE_API_BASE_URL=https://api.example.com`;
- Supabase Auth Site URL and redirect allow-list;
- Google browser-key referrer restrictions;
- SMTP/email branding and links.

Keep the Render `onrender.com` URLs available during staging. After custom
domains are proven, optionally disable the Render subdomains. If they remain
enabled, do not add them to production Auth/CORS unless they are intentionally
supported alternate origins.

## 10. First staging deployment

Deploy staging before production, with separate Supabase, Render, Langfuse,
OpenRouter, Maps, provider, SMTP, and model-download credentials.

Verify in this order:

1. `GET https://<staging-api>/v1/health` returns `{"status":"ok"}`.
2. `/openapi.json` is visible in staging but hidden after `API_ENVIRONMENT=production`.
3. The frontend loads through a deep link such as `/admin` without a 404.
4. Unknown-email sign-up/OTP cannot create an account.
5. The primordial admin can sign in and open Admin → People.
6. Provision a second test account through Admin → People; verify the SMTP
   message and password setup redirect.
7. Create a Hunt, Rubric, and Listing through the UI.
8. Confirm one Job is claimed and progresses; confirm no duplicate claimant.
9. Confirm Langfuse receives every LLM call and OpenRouter usage is charged to
   the production/staging-scoped key as expected.
10. Confirm images land in the private `property-images` Storage bucket.
11. Confirm IMAGE_CLASSIFY emits `image_classify_onnx_complete`, makes no LLM
    classifier call, and persists the expected artifact digest.
12. Confirm the gallery displays ONNX scene and kitchen probability.
13. Confirm the three highest `kitchen_score` eligible images become kitchen
    VISION targets and the anchored VISION result appears.
14. Exercise a Tier-2 Playwright fetch. This proves Chromium and its Linux
    dependencies were actually packaged.
15. Exercise Google Maps ENRICH and the frontend map with the two separate keys.
16. Exercise Realtime with two browsers and the Visit Presence path.
17. Restart/redeploy the API during a queued Job; confirm the durable Job
    resumes at a persisted Stage boundary.
18. Verify RLS with an ordinary member, another Hunt, and a Site Admin Ghost
    View. Frontend hiding is not evidence; unauthorized reads/writes must fail.
19. Review Supabase Security Advisor, database logs, Auth logs, Storage access,
    Render logs/memory, OpenRouter spend, and Langfuse traces.

Do not promote staging credentials or database contents into production.

## 11. Production launch sequence

1. Freeze merges briefly.
2. Confirm the exact commit is green in GitHub Actions.
3. Confirm Supabase Pro/backups, MFA, SMTP, Auth signup gate, redirects, and
   production secrets.
4. Run the production migration workflow and inspect `migration list`.
5. Deploy the Render API; wait for `/v1/health` and stable logs.
6. Confirm exactly one in-process worker claimant.
7. Deploy/rebuild the frontend against the final API/Supabase URLs.
8. Verify custom-domain TLS and SPA rewrites.
9. Bootstrap/sign in as the primordial admin.
10. Run a small real Listing end to end and inspect its Job, image Storage,
    canonical ONNX classification, VISION output, SCORE, costs, and traces.
11. Provision intended users through Admin → People.
12. Remove any temporary staging/Render origins from production Auth and CORS.
13. Unfreeze merges.

## 12. Operations, rollback, and secret rotation

### Application rollback

Render supports rollback to an earlier deployment, but database migrations are
forward-only. Because Manzil requires DB-before-code ordering, a code rollback
must remain compatible with the already-applied schema. Do not try to repair a
bad production deployment with `supabase db reset` or by editing migration
history casually.

### Failed model deployment

If the ONNX archive is missing or its digest is wrong, fail the build. Do not
start Uvicorn without it and do not restore the LLM classifier through an env
toggle. Roll back to the previous known-good Render deployment/artifact.

### Worker safety

- Keep `MANZIL_WORKER_INPROCESS=true`.
- Keep one Uvicorn worker and one Render instance.
- On shutdown, the API stops claiming and drains the in-flight Job.
- If a process dies, use Admin → Jobs stale-lock release/requeue after verifying
  the worker is gone.

### Rotation order

For secrets that support overlap:

1. create a new key;
2. update staging and verify;
3. update production and redeploy;
4. verify health and one real operation;
5. revoke the old key.

Rotate immediately if a secret appears in Git history, logs, screenshots, a
frontend build, or a public issue. Rewriting Git history does not make a leaked
credential safe.

### Monitoring

At minimum, monitor:

- Render health, restarts, memory, CPU, deploy failures, and logs;
- Supabase database size/connections, Security Advisor, Auth failures, Storage,
  Realtime limits, and backups;
- OpenRouter balance, per-key spend limit, and model errors;
- Langfuse missing traces, cost, latency, and Stage failures;
- Google Maps budgets/quotas and unauthorized-key traffic;
- Bright Data/ScrapingBee credits;
- failed, retrying, checkpointed, and stale-lock Jobs in Manzil Admin.

The current `/v1/health` endpoint is liveness only; it does not query Postgres,
verify the model, or prove the worker loop is advancing. A separate readiness
endpoint and alerting integration are worthwhile follow-up work before relying
on automated uptime checks alone. Render recommends that HTTP health checks
exercise operation-critical dependencies in its [Health Checks](https://render.com/docs/health-checks)
guide.

## 13. Secret-placement summary

| Secret/value | GitHub | Render API | Render frontend | Supabase | DNS/provider |
|---|---:|---:|---:|---:|---:|
| Supabase access token | production environment secret | no | no | issued there | no |
| Supabase DB password | production environment secret | only inside pooler URL | no | issued there | no |
| `DATABASE_URL` | no | **secret** | never | source | no |
| Supabase publishable key | no | yes | yes, public | source | no |
| Supabase service-role JWT | no | **secret** | never | source | no |
| OpenRouter key | no | **secret** | never | no | OpenRouter source |
| Langfuse public/secret pair | no | **secret** | never | no | Langfuse source |
| Google server key | no | **secret** | never | no | Google source |
| Google browser key | no | never | public build variable | no | Google source |
| Tier-3 provider key | no | **secret** | never | no | provider source |
| ONNX archive credential/URL | no | **BuildKit-mounted secret file; never env/ARG** | never | optional object store | object-store source |
| SMTP password | no | no | never | Auth SMTP setting | SMTP source |
| Render deploy hook | only if using hook-based CD | source | source | no | Render source |

No production secret belongs in `.env`, `frontend/.env.local`, `render.yaml`, a
Dockerfile, GitHub workflow YAML, Supabase migration SQL, or Vite output.

## 14. Recommended infrastructure commits

Before performing the production launch, add and review these repository-owned
deployment inputs:

1. a production multi-stage Dockerfile that installs the uv workspace,
   `manzil-api[vision-onnx]`, Playwright Chromium/system libraries, and the
   verified ONNX archive without retaining download credentials;
2. a `.dockerignore` that excludes `.env`, local/eval fixtures, caches, `.git`,
   and unrelated artifacts while retaining all required workspace packages;
3. `render.yaml` after the manual service has proven the exact commands;
4. the protected production database deployment job shown above;
5. a readiness endpoint that checks a trivial Postgres query and reports model
   configuration without exposing paths or secrets;
6. a staging smoke workflow or documented manual release sign-off;
7. an engineering migration from the legacy Supabase `service_role` JWT to a
   named `sb_secret_...` server key.

Those are the remaining infrastructure/code deliverables. The domain, provider
accounts, hosted Auth switches, SMTP verification, secrets, billing, and first
production acceptance run remain operator actions and must not be encoded with
real values in the repository.
