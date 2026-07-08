// Magic-link login (Phase 1 plan §1.2, §5.2): one user, email OTP — no password
// or reset flow. Sends signInWithOtp; AuthProvider picks up the session on return.
import { Button, Card, Center, Stack, Text, TextInput, Title } from "@mantine/core";
import { useState } from "react";
import { Navigate } from "react-router-dom";

import { supabase } from "../lib/supabase";
import { useAuth } from "./useAuth";

export function LoginPage() {
  const { session } = useAuth();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (session) return <Navigate to="/" replace />;

  async function sendLink() {
    setError(null);
    const { error: authError } = await supabase.auth.signInWithOtp({ email });
    if (authError) setError(authError.message);
    else setSent(true);
  }

  return (
    <Center h="100vh">
      <Card withBorder shadow="sm" w={360} padding="lg">
        <Stack>
          <Title order={3}>Manzil</Title>
          {sent ? (
            <Text>Check your email for a sign-in link.</Text>
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
  );
}
