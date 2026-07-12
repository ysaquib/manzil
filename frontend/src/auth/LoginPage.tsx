import {
  Alert,
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
import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { PublicPageShell } from "../components/PublicPageShell";
import { supabase } from "../lib/supabase";
import { useAuth } from "./useAuth";

type Mode = "password" | "register" | "magic";

export function LoginPage() {
  const { session } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const returnTo = (location.state as { from?: string } | null)?.from ?? "/";
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
    const result = mode === "register"
      ? await supabase.auth.signUp({ email, password, options: { emailRedirectTo: callback } })
      : await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (result.error) return setError(result.error.message);
    if (mode === "register") setSent(true);
    else navigate(returnTo, { replace: true });
  }

  async function sendLink() {
    setBusy(true);
    setError(null);
    const { error: authError } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: callback },
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
      redirectTo: `${window.location.origin}/auth/reset-password`,
    });
    setBusy(false);
    if (authError) setError(authError.message);
    else setSent(true);
  }

  return <PublicPageShell><Center py="xl"><Card withBorder w="100%" maw={420}><Stack>
    <div><Text fw={600} size="lg">Welcome to Manzil</Text><Text c="dimmed" size="sm">Sign in or create an account.</Text></div>
    <SegmentedControl fullWidth value={mode} onChange={(value) => { setMode(value as Mode); setSent(false); setError(null); }}
      data={[{ value: "password", label: "Sign in" }, { value: "register", label: "Register" }, { value: "magic", label: "Magic link" }]} />
    {sent && mode === "register" ? <Alert title="Confirm your email">Account created. Check your email to confirm your address, then you’ll return here.</Alert> : <>
      {sent && mode === "magic" ? <>
        <Text>Link sent. Check your email and you’ll land right back here, or enter the code below.</Text>
        <TextInput label="Email code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
          onChange={(e) => setCode(e.currentTarget.value.replace(/\D/g, "").slice(0, 6))} />
        <Button loading={busy} disabled={code.length !== 6} onClick={verifyCode}>Verify code</Button>
        <Button variant="subtle" loading={busy} onClick={sendLink}>Resend link and code</Button>
      </> : <>
        <TextInput label="Email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.currentTarget.value)} />
        {mode !== "magic" && <PasswordInput label="Password" autoComplete={mode === "register" ? "new-password" : "current-password"}
          value={password} onChange={(e) => setPassword(e.currentTarget.value)} />}
        <Button loading={busy} disabled={!email || (mode !== "magic" && !password)} onClick={mode === "magic" ? sendLink : submit}>
          {mode === "magic" ? "Send magic link" : mode === "register" ? "Create account" : "Sign in"}
        </Button>
        {mode === "password" && <><Divider /><Button variant="subtle" disabled={!email} loading={busy} onClick={resetPassword}>Forgot password?</Button></>}
      </>}
    </>}
    {error && <Text c="red" size="sm">{error}</Text>}
  </Stack></Card></Center></PublicPageShell>;
}
