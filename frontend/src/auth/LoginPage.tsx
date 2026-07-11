// Magic-link login (Phase 1 plan §1.2, §5.2): one user, email OTP — no password
// or reset flow. Sends signInWithOtp; AuthProvider picks up the session on return.
import { Button, Card, Center, Stack, Text, TextInput } from "@mantine/core";
import { useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { PublicPageShell } from "../components/PublicPageShell";
import { supabase } from "../lib/supabase";
import { useAuth } from "./useAuth";

export function LoginPage() {
  const { session } = useAuth();
  const location = useLocation();
  const returnTo = (location.state as { from?: string } | null)?.from ?? "/";
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (session) return <Navigate to={returnTo} replace />;

  async function sendLink() {
    setError(null);
    const { error: authError } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: `${window.location.origin}${returnTo}` },
    });
    if (authError) setError(authError.message);
    else setSent(true);
  }

  return (
    <PublicPageShell>
      <Center py="xl">
        <Card withBorder w="100%" maw={400}>
          <Stack>
            <div>
              <Text fw={600} size="lg">
                Sign in
              </Text>
              <Text c="dimmed" size="sm">
                No password — we'll email you a link.
              </Text>
            </div>
            {sent ? (
              <Text>Link sent. Check your email and you'll land right back here.</Text>
            ) : (
              <>
                <TextInput
                  label="Email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.currentTarget.value)}
                />
                {error && (
                  <Text c="red" size="sm">
                    {error}
                  </Text>
                )}
                <Button onClick={sendLink} disabled={!email}>
                  Send magic link
                </Button>
              </>
            )}
          </Stack>
        </Card>
      </Center>
    </PublicPageShell>
  );
}
