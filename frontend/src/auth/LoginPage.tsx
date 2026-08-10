import {
  Button,
  Card,
  Center,
  Divider,
  PasswordInput,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { PublicPageShell } from "../components/PublicPageShell";
import { TryDemoButton } from "../features/demo/TryDemoButton";
import { supabase } from "../lib/supabase";
import { isResumableTarget, nextQuery, safeReturnTo } from "./returnTo";
import { useAuth } from "./useAuth";

type Mode = "password" | "magic";

export function LoginPage() {
  const { session } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // `?next=` first, router state second. The query parameter is what survives a
  // reload or a link opened in a second tab; the state is what older redirects
  // (and anything that navigates programmatically) still hand over.
  const returnTo = safeReturnTo(
    params.get("next") ?? (location.state as { from?: string } | null)?.from,
  );
  const resuming = isResumableTarget(returnTo);
  const [mode, setMode] = useState<Mode>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (session) return <Navigate to={returnTo} replace />;

  const callback = `${window.location.origin}/auth/callback?next=${encodeURIComponent(returnTo)}`;
  async function submit() {
    setBusy(true);
    setError(null);
    const result = await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (result.error) return setError(result.error.message);
    navigate(returnTo, { replace: true });
  }

  async function sendLink() {
    setBusy(true);
    setError(null);
    const { error: authError } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: callback,
        // Authentication only. Account provisioning belongs exclusively to
        // the audited Site Admin People API (DESIGN FR13 / PR-1).
        shouldCreateUser: false,
      },
    });
    setBusy(false);
    if (authError) setError(authError.message);
    else setSent(true);
  }

  async function verifyCode() {
    setBusy(true);
    setError(null);
    const { error: authError } = await supabase.auth.verifyOtp({ email, token: code, type: "email" });
    setBusy(false);
    if (authError) setError(authError.message);
    else navigate(returnTo, { replace: true });
  }

  async function resetPassword() {
    setBusy(true);
    setError(null);
    const { error: authError } = await supabase.auth.resetPasswordForEmail(email, {
      // Carry the invitation through the reset too: someone who cannot remember
      // their password is exactly the person who will otherwise finish this
      // detour on the homepage wondering where the Hunt went.
      redirectTo: `${window.location.origin}/auth/reset-password${nextQuery(returnTo)}`,
    });
    setBusy(false);
    if (authError) setError(authError.message);
    else setSent(true);
  }

  // Real <form>s, so Enter in any field runs the primary action. Every
  // secondary button inside one needs `type="button"` spelled out: a bare
  // <button> in a form submits it, and Mantine does not set a default.
  const codeReady = code.length === 6;
  const credentialsReady = Boolean(email) && (mode === "magic" || Boolean(password));

  function onSubmitCode(event: FormEvent) {
    event.preventDefault();
    if (busy || !codeReady) return;
    void verifyCode();
  }

  function onSubmitCredentials(event: FormEvent) {
    event.preventDefault();
    if (busy || !credentialsReady) return;
    void (mode === "magic" ? sendLink() : submit());
  }

  return <PublicPageShell><Center py="xl"><Card withBorder w="100%" maw={420}><Stack>
    {/* Someone who arrived by clicking an invitation needs to be told that
        signing in is a step on the way, not a different errand. */}
    <div><Text fw={600} size="lg">{resuming ? "Sign in to accept your invitation" : "Welcome to Manzil"}</Text><Text c="dimmed" size="sm">
      {resuming
        ? "You'll go straight to the Hunt once you're signed in. Accounts are created by an administrator."
        : "Sign in with an account created by an administrator."}
    </Text></div>
    <SegmentedControl fullWidth value={mode} onChange={(value) => { setMode(value as Mode); setSent(false); setError(null); }}
      data={[{ value: "password", label: "Sign in" }, { value: "magic", label: "Magic link" }]} />
    <>
      {sent && mode === "magic" ? <>
        <Text>Link sent. Check your email and you’ll land right back here, or enter the code below.</Text>
        <form onSubmit={onSubmitCode}><Stack>
          <TextInput label="Email code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
            onChange={(e) => setCode(e.currentTarget.value.replace(/\D/g, "").slice(0, 6))} />
          <Button type="submit" loading={busy} disabled={!codeReady}>Verify code</Button>
        </Stack></form>
        <Button type="button" variant="subtle" loading={busy} onClick={sendLink}>Resend link and code</Button>
      </> : <>
        <form onSubmit={onSubmitCredentials}><Stack>
          <TextInput label="Email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.currentTarget.value)} />
          {mode !== "magic" && <PasswordInput label="Password" autoComplete="current-password"
            value={password} onChange={(e) => setPassword(e.currentTarget.value)} />}
          <Button type="submit" loading={busy} disabled={!credentialsReady}>
            {mode === "magic" ? "Send magic link" : "Sign in"}
          </Button>
        </Stack></form>
        {mode === "password" && <><Divider /><Button type="button" variant="subtle" disabled={!email} loading={busy} onClick={resetPassword}>Forgot password?</Button></>}
      </>}
    </>
    {error && <Text c="red" size="sm">{error}</Text>}
    <TryDemoButton />
  </Stack></Card></Center></PublicPageShell>;
}
