// The way in (DM-7, DESIGN §16).
//
// Rendered only when `GET /v1/demo/config` says the demo is on, so a disabled
// demo is not merely refused but invisible — the endpoint answers 404 for the
// same reason.
//
// No credentials are shipped to the browser. `POST /v1/demo/session` mints a
// short-lived token for a subject with no account (§20 v3.55); there is nothing
// here to steal and nothing to sign in to.
import { Button, Divider, Stack, Text } from "@mantine/core";
import { IconEye } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import { apiFetch, ApiError } from "../../lib/apiClient";
import { enterDemo } from "../../lib/demo";

interface DemoConfig {
  enabled: boolean;
}

interface DemoSession {
  access_token: string;
  expires_in: number;
  hunt_id: string | null;
}

export function TryDemoButton() {
  const [offered, setOffered] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<DemoConfig>("/v1/demo/config")
      .then((config) => {
        if (!cancelled) setOffered(config.enabled);
      })
      // A demo that cannot be reached is simply not offered. This must never
      // surface an error on the sign-in page: it is not the visitor's problem
      // and they are usually here to sign in, not to browse.
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (!offered) return null;

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const session = await apiFetch<DemoSession>("/v1/demo/session", { method: "POST" });
      enterDemo(session.access_token, session.hunt_id);
    } catch (exc) {
      setBusy(false);
      setError(
        exc instanceof ApiError && exc.code === "demo_rate_limited"
          ? "The demo is busy right now — try again in a minute."
          : "The demo is unavailable right now.",
      );
    }
  }

  return (
    <Stack gap="xs">
      <Divider label="or" labelPosition="center" />
      <Button
        variant="light"
        leftSection={<IconEye size={16} />}
        loading={busy}
        onClick={start}
      >
        Try the demo
      </Button>
      <Text c="dimmed" size="xs" ta="center">
        Explore a real apartment hunt. No account, nothing saved.
      </Text>
      {error && (
        <Text c="red" size="sm" ta="center">
          {error}
        </Text>
      )}
    </Stack>
  );
}
