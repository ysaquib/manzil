# Security

Manzil is a personal apartment-hunting tool that is **publicly viewable, not publicly usable**. There is no self-serve signup. The hosted site at [manzil.yusufsaquib.com](https://manzil.yusufsaquib.com) is a read-only Demo Mode session over one curated Hunt: visitors cannot create an account, submit a listing, enqueue a Job, or spend any pipeline budget.

This document is here so the security posture is explicit. I am a solo maintainer and do **not** run a vulnerability-bounty program or a guaranteed response SLA. Reports are still welcome if you find something real.

## Reporting a vulnerability

Please **do not** open a public GitHub issue, pull request, or discussion for a security problem.

Email **[contact@yusufsaquib.com](mailto:contact@yusufsaquib.com)** with:

- A description of the issue and the impact you expect
- Steps to reproduce, or a proof of concept that stays within the hosted demo or a local clone you control
- Affected URL, endpoint, or table/policy if you have it
- Whether you already have a workaround

I will acknowledge mail I can act on. There is no timeline I can honestly promise.

Do not include secrets you found in a public channel. If you believe a key or token has leaked from this project, say so in the first line of the email and rotate nothing on my behalf.

## What is in scope

Reports that change who can read or write Hunt data, mint an account, or spend money on the pipeline are the ones that matter:

- Bypassing Demo Mode write refusal, read scoping, or the kill switch
- Creating an `auth.users` row through public signup, magic link, or OTP
- Reading another Hunt's rows, Storage objects, or cleaned Source text with a demo or ordinary member JWT
- SSRF, service-role key exposure, or an unauthenticated route that enqueues a Job
- Prompt-injection that causes a **tool action** (extraction stages are supposed to have zero tools)

## What is not in scope

Please skip these, or treat them as ordinary issues rather than security reports:

- Missing features, scoring disagreements, or listing-site ToS questions
- The demo being read-only, or the absence of public registration — those are design
- UI-only checks that a determined client can ignore (RLS is the boundary; the frontend is UX)
- Dependency CVEs with no demonstrated path in this repo
- Social engineering, physical access, or attacking listing aggregators rather than Manzil
- Theoretical issues in a local `supabase start` stack that require already-held service-role credentials

## How the hosted app is meant to be locked down

The design source of truth is [`DESIGN.md`](DESIGN.md) §16. The short version:

| Control | Intent |
|---|---|
| **RLS is the security boundary** | Frontend checks are never enforcement. Per-hunt tables join through membership; global facts are client-read-only; the worker holds the service role. |
| **No public accounts** | Site Admins provision users. Magic link and OTP must authenticate an existing account only (`shouldCreateUser: false`). |
| **Demo Mode is a database fact** | A Demo Account is a short-lived virtual principal with no `auth.users` row. Reads are scoped to the published Hunt; writes are refused by trigger; money-spending RPCs reject the subject; disabling demo darkens already-issued tokens. |
| **Scraped pages are untrusted** | Extraction has no tools. VERIFY requires page evidence. Fetches go through VALIDATE_URL and an SSRF guard. |
| **Secrets stay server-side** | The browser holds the Supabase anon key only. API keys live in the host environment. |

If the live demo and this document disagree, treat the running site as the incident and this file as the intended design.

## Supported versions

Only the deployment at [manzil.yusufsaquib.com](https://manzil.yusufsaquib.com) and the current `master` branch are in view. Older tags and forks are unsupported.

Running your own instance is allowed under the [AGPLv3](LICENSE.md). You are responsible for its keys, RLS, and account provisioning. I cannot patch forks I do not operate.
