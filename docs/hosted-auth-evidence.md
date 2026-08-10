# Hosted Auth verification — evidence

Run: 2026-08-09T21:51:57.514170-04:00
Project ref: `glpbxuslcrnnegbdnwml`
Auth endpoint: `https://glpbxuslcrnnegbdnwml.supabase.co`

Produced by `scripts/check_hosted_auth.py`. `supabase/config.toml`
configures only the local stack; these are assertions against the hosted
project's declared configuration and its observed behaviour.

**15 of 15 checks passed.**

| Area | Check | Result | Detail |
|---|---|---|---|
| config | public sign-up is disabled | ✅ | disable_signup = True (expected True) — the Admin API is the only account-creation path (DESIGN §16) |
| config | anonymous sign-in is disabled | ✅ | external_anonymous_users_enabled = False (expected False) — an anonymous user is a real auth.users row a stranger can create |
| config | manual identity linking is disabled | ✅ | security_manual_linking_enabled = False (expected False) — linking lets a session attach a new identity to an existing account |
| config | changing a password requires reauthentication | ✅ | security_update_password_require_reauthentication = True (expected True) — DM-2; without it a stolen session is a permanent account takeover |
| config | an email change is confirmed on both addresses | ✅ | mailer_secure_email_change_enabled = True (expected True) — otherwise one confirmation moves an account to an attacker's inbox |
| config | email addresses are not auto-confirmed | ✅ | mailer_autoconfirm = False (expected False) — auto-confirm would make an unverified address a usable identity |
| config | access tokens are short-lived | ✅ | jwt_exp = 3600s (expected ≤ 3600) — bounds how long a leaked token works |
| config | the redirect allow-list is exact | ✅ | 3 entries, 0 wildcard(s) — a wildcard turns a redirect into an open one |
| config | the deployed frontend is on the allow-list | ✅ | https://manzil.yusufsaquib.com against ['https://manzil.yusufsaquib.com/invite/**', 'https://manzil.yusufsaquib.com/auth/reset-password', 'https://manzil.yusufsaquib.com/auth/callback'] |
| config | rate limits are configured | ✅ | {"rate_limit_anonymous_users": 30, "rate_limit_sms_sent": 30, "rate_limit_verify": 30, "rate_limit_token_refresh": 150, "rate_limit_otp": 30, "rate_limit_email_sent": 30, "rate_limit_web3": 30} |
| behaviour | an unknown email cannot sign itself up | ✅ | POST /signup -> 422 {"code":422,"error_code":"signup_disabled","msg":"Signups not allowed for this instance"} |
| behaviour | anonymous sign-in is refused | ✅ | POST /signup (no credentials) -> 422 {"code":422,"error_code":"anonymous_provider_disabled","msg":"Anonymous sign-ins are disabled"} |
| behaviour | OTP cannot create an account even when asked to | ✅ | POST /otp (create_user=true) -> 422 {"code":422,"error_code":"signup_disabled","msg":"Signups not allowed for this instance"} |
| behaviour | recovery does not disclose whether an address has an account | ✅ | POST /recover -> 200 {} (a uniform response is the correct one) |
| behaviour | magic links cannot create an account | ✅ | POST /magiclink -> 422 {"code":422,"error_code":"signup_disabled","msg":"Signups not allowed for this instance"} |
