import { Button, Card, Center, Stack, Text, TextInput, Title } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { PublicPageShell } from "../components/PublicPageShell";
import { apiFetch } from "../lib/apiClient";
import { useAuth } from "./useAuth";
import { useProfile } from "./profile";

export function OnboardingPage() {
  const { session } = useAuth();
  const profile = useProfile(session?.user.id);
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!session) return <Navigate to="/login" replace />;
  if (profile.data) return <Navigate to={params.get("next") || "/"} replace />;
  async function save() {
    setBusy(true); setError(null);
    try {
      await apiFetch("/v1/profile", { method: "PUT", body: { default_display_name: name } });
      await qc.invalidateQueries({ queryKey: ["profile", session!.user.id] });
      navigate(params.get("next") || "/", { replace: true });
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save your name"); }
    finally { setBusy(false); }
  }
  return <PublicPageShell><Center py="xl"><Card withBorder maw={440} w="100%"><Stack>
    <Title order={2}>What should we call you?</Title>
    <Text c="dimmed">This is your default display name in Hunts. You can set a different name in any Hunt without changing this default.</Text>
    <TextInput autoFocus label="Default display name" maxLength={80} value={name} onChange={(e) => setName(e.currentTarget.value)} />
    {error && <Text c="red" size="sm">{error}</Text>}
    <Button loading={busy} disabled={!name.trim()} onClick={save}>Continue</Button>
    <Button component={Link} to="/signout" variant="subtle" color="gray">Sign out</Button>
  </Stack></Card></Center></PublicPageShell>;
}
