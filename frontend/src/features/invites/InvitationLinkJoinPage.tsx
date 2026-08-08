import { Alert, Card, Center, Loader, Stack, Text, Title } from "@mantine/core";
import { useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { PublicPageShell } from "../../components/PublicPageShell";
import { ApiError } from "../../lib/apiClient";
import { isDemo } from "../../lib/demo";
import { useJoinInvitationLink } from "./api";

const ERROR_MESSAGES: Record<string, string> = {
  invitation_link_deleted: "This Invitation Link was deleted and can no longer be used.",
  invitation_link_expired: "This Invitation Link has expired.",
  invitation_link_exhausted: "This Invitation Link has reached its use limit.",
  invitation_link_not_found: "This Invitation Link does not exist.",
};

export function InvitationLinkJoinPage() {
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const join = useJoinInvitationLink(token);
  const started = useRef(false);

  // demo-guarded: useJoinInvitationLink — a demo visitor can reach this page
  // simply by pasting a link they were sent, and joining is a write the database
  // refuses. Say so plainly rather than attempting it: the demo principal has no
  // account to add to a Hunt, so `onSuccess` would destructure an intercepted,
  // empty response and throw.
  const demo = isDemo();

  useEffect(() => {
    if (!token || started.current || demo) return;
    started.current = true;
    join.mutate(undefined, {
      onSuccess: ({ hunt_id }) => navigate(`/h/${hunt_id}`, { replace: true }),
    });
  }, [demo, join, navigate, token]);

  const errorCode = join.error instanceof ApiError ? join.error.code : "unknown";
  return (
    <PublicPageShell>
      <Center py="xl">
        <Card withBorder w="100%" maw={440}>
          <Stack align="center">
            <Title order={2}>Joining Hunt</Title>
            {demo ? (
              <Alert color="yellow" title="Not available in the demo" w="100%">
                You are browsing the demo, which is read-only and has no account
                behind it. Sign in with your own account to accept this
                invitation.
              </Alert>
            ) : join.error ? (
              <Alert color="red" title="Invitation Link unavailable" w="100%">
                {ERROR_MESSAGES[errorCode] ?? "This Invitation Link could not be used."}
              </Alert>
            ) : (
              <>
                <Loader />
                <Text c="dimmed">Adding you to the Hunt…</Text>
              </>
            )}
          </Stack>
        </Card>
      </Center>
    </PublicPageShell>
  );
}
