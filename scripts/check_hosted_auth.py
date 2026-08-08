#!/usr/bin/env python
"""Verify a hosted Supabase project's Auth posture (R1 H5, PR-1, DESIGN §16).

`supabase/config.toml` configures the **local** stack and nothing else. Every
account-provisioning guarantee in DESIGN §16 — public sign-up disabled, unknown
emails unable to become accounts through OTP or recovery, secure password
change — is enforced by the hosted project's own settings, and a public demo
turns any drift there into an account-creation exposure rather than an
inconvenience.

Both security reviews are explicit that dashboard screenshots are not evidence.
This produces executable results in two independent ways:

  * **Declared config** — read from the Management API, so the assertion is
    against what the project is actually configured to do.
  * **Observed behaviour** — unauthenticated probes against the project's own
    GoTrue, so the assertion is against what it actually does. Config can be
    right while behaviour is wrong (a provider default changing under you), and
    behaviour can look right for the wrong reason.

Usage:

    export SUPABASE_PROJECT_REF=abcdefghijklmnop
    export SUPABASE_ACCESS_TOKEN=sbp_...          # a personal access token
    export SUPABASE_URL=https://abcdefghijklmnop.supabase.co
    export SUPABASE_ANON_KEY=eyJ...
    export MANZIL_FRONTEND_URL=https://app.example.com
    uv run python scripts/check_hosted_auth.py

Either half may be run alone: without a PAT it runs behavioural probes only,
without a URL it checks declared config only. Both halves must pass before Demo
Mode is enabled on that project.

**Probes create nothing.** They deliberately use an address at a domain reserved
by RFC 2606, and every one of them is a request that *must fail*. If a probe
succeeds, that is the finding.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

MANAGEMENT_API = "https://api.supabase.com"
# RFC 2606 reserves example.test; nothing can receive mail there, so a probe
# that unexpectedly succeeds cannot also email a real person.
PROBE_EMAIL = f"dm8-probe-{uuid.uuid4().hex[:10]}@example.test"


@dataclass
class Finding:
    area: str
    name: str
    passed: bool
    detail: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def record(self, area: str, name: str, passed: bool, detail: str) -> None:
        self.findings.append(Finding(area, name, passed, detail))
        colour = "\033[32mPASS\033[0m" if passed else "\033[31mFAIL\033[0m"
        print(f"  {colour}  {name} — {detail}")

    def skip(self, why: str) -> None:
        self.skipped.append(why)
        print(f"  \033[33mSKIP\033[0m  {why}")

    @property
    def failed(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed]


# ── Declared configuration ───────────────────────────────────────────────────


def check_declared_config(ref: str, token: str, frontend_url: str | None, report: Report) -> None:
    print("\nDeclared configuration (Management API)")
    response = httpx.get(
        f"{MANAGEMENT_API}/v1/projects/{ref}/config/auth",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if response.status_code != 200:
        report.record(
            "config",
            "Auth configuration is readable",
            False,
            f"{response.status_code} {response.text[:160]}",
        )
        return

    config: dict[str, Any] = response.json()

    def flag(key: str, expected: Any, name: str, why: str) -> None:
        actual = config.get(key)
        report.record(
            "config",
            name,
            actual == expected,
            f"{key} = {actual!r} (expected {expected!r}) — {why}",
        )

    flag(
        "disable_signup",
        True,
        "public sign-up is disabled",
        "the Admin API is the only account-creation path (DESIGN §16)",
    )
    flag(
        "external_anonymous_users_enabled",
        False,
        "anonymous sign-in is disabled",
        "an anonymous user is a real auth.users row a stranger can create",
    )
    flag(
        "security_manual_linking_enabled",
        False,
        "manual identity linking is disabled",
        "linking lets a session attach a new identity to an existing account",
    )
    flag(
        "security_update_password_require_reauthentication",
        True,
        "changing a password requires reauthentication",
        "DM-2; without it a stolen session is a permanent account takeover",
    )
    flag(
        "mailer_secure_email_change_enabled",
        True,
        "an email change is confirmed on both addresses",
        "otherwise one confirmation moves an account to an attacker's inbox",
    )
    flag(
        "mailer_autoconfirm",
        False,
        "email addresses are not auto-confirmed",
        "auto-confirm would make an unverified address a usable identity",
    )

    ttl = config.get("jwt_exp")
    report.record(
        "config",
        "access tokens are short-lived",
        isinstance(ttl, int) and ttl <= 3600,
        f"jwt_exp = {ttl}s (expected ≤ 3600) — bounds how long a leaked token works",
    )

    if frontend_url:
        allow_list = str(config.get("uri_allow_list") or "")
        entries = [item.strip() for item in allow_list.split(",") if item.strip()]
        wildcards = [item for item in entries if item in ("*", "**") or item.startswith("*")]
        report.record(
            "config",
            "the redirect allow-list is exact",
            bool(entries) and not wildcards,
            f"{len(entries)} entries, {len(wildcards)} wildcard(s) — "
            "a wildcard turns a redirect into an open one",
        )
        report.record(
            "config",
            "the deployed frontend is on the allow-list",
            any(entry.rstrip("/*").startswith(frontend_url.rstrip("/")) for entry in entries),
            f"{frontend_url} against {entries}",
        )
    else:
        report.skip("redirect allow-list: set MANZIL_FRONTEND_URL to check it")

    limits = {
        key: value for key, value in config.items() if key.startswith("rate_limit_")
    }
    report.record(
        "config",
        "rate limits are configured",
        bool(limits),
        json.dumps(limits) if limits else "no rate_limit_* keys returned",
    )


# ── Observed behaviour ───────────────────────────────────────────────────────


def check_observed_behaviour(url: str, anon_key: str, report: Report) -> None:
    print("\nObserved behaviour (unauthenticated probes against GoTrue)")
    headers = {"apikey": anon_key, "Content-Type": "application/json"}
    client = httpx.Client(base_url=f"{url.rstrip('/')}/auth/v1", headers=headers, timeout=30)

    with client:
        signup = client.post(
            "/signup", json={"email": PROBE_EMAIL, "password": f"Pw-{uuid.uuid4().hex}"}
        )
        # 200 with a user body would mean an unknown email just became an account.
        created = signup.status_code == 200 and '"id"' in signup.text
        report.record(
            "behaviour",
            "an unknown email cannot sign itself up",
            not created,
            f"POST /signup -> {signup.status_code} {signup.text[:120]}",
        )

        anon = client.post("/signup", json={})
        report.record(
            "behaviour",
            "anonymous sign-in is refused",
            anon.status_code != 200,
            f"POST /signup (no credentials) -> {anon.status_code} {anon.text[:120]}",
        )

        otp = client.post(
            "/otp", json={"email": PROBE_EMAIL, "create_user": True}
        )
        # The frontend sends `shouldCreateUser: false`; this asks for the
        # opposite on purpose, because the control has to be the server's.
        report.record(
            "behaviour",
            "OTP cannot create an account even when asked to",
            otp.status_code != 200 or "error" in otp.text.lower(),
            f"POST /otp (create_user=true) -> {otp.status_code} {otp.text[:120]}",
        )

        recover = client.post("/recover", json={"email": PROBE_EMAIL})
        report.record(
            "behaviour",
            "recovery does not disclose whether an address has an account",
            recover.status_code in (200, 429),
            f"POST /recover -> {recover.status_code} {recover.text[:120]} "
            "(a uniform response is the correct one)",
        )

        magic = client.post("/magiclink", json={"email": PROBE_EMAIL})
        report.record(
            "behaviour",
            "magic links cannot create an account",
            magic.status_code != 200 or "error" in magic.text.lower(),
            f"POST /magiclink -> {magic.status_code} {magic.text[:120]}",
        )


def write_evidence(path: str, report: Report, ref: str | None, url: str | None) -> None:
    lines = [
        "# Hosted Auth verification — evidence",
        "",
        f"Run: {datetime.now().astimezone().isoformat()}",
        f"Project ref: `{ref or 'not checked'}`",
        f"Auth endpoint: `{url or 'not checked'}`",
        "",
        "Produced by `scripts/check_hosted_auth.py`. `supabase/config.toml`",
        "configures only the local stack; these are assertions against the hosted",
        "project's declared configuration and its observed behaviour.",
        "",
        f"**{len(report.findings) - len(report.failed)} of {len(report.findings)} checks passed.**",
        "",
        "| Area | Check | Result | Detail |",
        "|---|---|---|---|",
    ]
    for finding in report.findings:
        detail = finding.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {finding.area} | {finding.name} | {'✅' if finding.passed else '❌'} | {detail} |"
        )
    if report.skipped:
        lines += ["", "## Not exercised", ""] + [f"- {item}" for item in report.skipped]
    lines.append("")
    with open(path, "w") as handle:
        handle.write("\n".join(lines))
    print(f"\nEvidence written to {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", default="docs/hosted-auth-evidence.md")
    args = parser.parse_args()

    ref = os.environ.get("SUPABASE_PROJECT_REF")
    token = os.environ.get("SUPABASE_ACCESS_TOKEN")
    url = os.environ.get("SUPABASE_URL")
    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    frontend_url = os.environ.get("MANZIL_FRONTEND_URL")

    if url and ("localhost" in url or "127.0.0.1" in url):
        sys.exit(
            "SUPABASE_URL points at the local stack. This script exists to check a "
            "*hosted* project, whose settings config.toml does not govern."
        )

    report = Report()

    if ref and token:
        check_declared_config(ref, token, frontend_url, report)
    else:
        report.skip(
            "declared configuration: set SUPABASE_PROJECT_REF and SUPABASE_ACCESS_TOKEN"
        )

    if url and anon_key:
        check_observed_behaviour(url, anon_key, report)
    else:
        report.skip("observed behaviour: set SUPABASE_URL and SUPABASE_ANON_KEY")

    if not report.findings:
        sys.exit(
            "Nothing was checked. Provide a Management API token, an anon key, or both."
        )

    write_evidence(args.evidence, report, ref, url)

    if report.failed:
        print(f"\n\033[31m{len(report.failed)} check(s) FAILED\033[0m")
        for finding in report.failed:
            print(f"  - [{finding.area}] {finding.name}: {finding.detail}")
        return 1
    print(f"\n\033[32mAll {len(report.findings)} checks passed.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
