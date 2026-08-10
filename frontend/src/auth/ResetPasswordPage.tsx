import { Alert, Button, Card, Center, PasswordInput, Stack, Title } from "@mantine/core";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PublicPageShell } from "../components/PublicPageShell";
import { supabase } from "../lib/supabase";
import { safeReturnTo } from "./returnTo";

export function ResetPasswordPage() {
  const navigate = useNavigate(); const [params] = useSearchParams(); const [password, setPassword] = useState(""); const [error, setError] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  // A reset that began at an invitation ends at that invitation.
  const returnTo = safeReturnTo(params.get("next"));
  async function save() { setBusy(true); const result = await supabase.auth.updateUser({ password }); setBusy(false); if (result.error) setError(result.error.message); else navigate(returnTo, { replace: true }); }
  // A form, so Enter in the field saves — the same reflex as every other
  // password box on the web.
  return <PublicPageShell><Center py="xl"><Card withBorder maw={420} w="100%"><form onSubmit={(event) => { event.preventDefault(); if (password && !busy) void save(); }}><Stack><Title order={2}>Choose a new password</Title><PasswordInput label="New password" value={password} onChange={(e) => setPassword(e.currentTarget.value)} />{error && <Alert color="red">{error}</Alert>}<Button type="submit" disabled={!password} loading={busy}>Update password</Button></Stack></form></Card></Center></PublicPageShell>;
}
