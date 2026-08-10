import { Alert, Button, Card, Center, Stack, Text, Title } from "@mantine/core";
import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { PublicPageShell } from "../../components/PublicPageShell";
import { isDemo } from "../../lib/demo";
import { useAcceptInvite } from "./api";

export function InviteAcceptPage() {
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const accept = useAcceptInvite(token);

  // demo-guarded: useAcceptInvite — the same treatment InvitationLinkJoinPage
  // got, and for the same reason. A demo visitor reaches this page by pasting a
  // link they were sent; accepting is a write the database refuses, and the
  // demo principal has no account to add to a Hunt in the first place. Left
  // alone the button would spin forever: the intercepted POST resolves as
  // `undefined`, so `accept.data` never becomes truthy and the redirect below
  // never fires.
  const demo = isDemo();

  useEffect(() => {
    if (accept.data) navigate(`/h/${accept.data.hunt_id}`, { replace: true });
  }, [accept.data, navigate]);

  return (
    <PublicPageShell>
      <Center py="xl">
        <Card withBorder w="100%" maw={440}>
          <Stack>
            <Title order={2}>Join this Hunt</Title>
            <Text c="dimmed">Accept the invitation to collaborate on this apartment Hunt.</Text>
            {demo ? (
              <Alert color="yellow" title="Not available in the demo">
                You are browsing the demo, which is read-only and has no account
                behind it. Sign in with your own account to accept this
                invitation.
              </Alert>
            ) : (
              accept.error && (
                <Alert color="red" title="Invite unavailable">
                  This invite has expired, was revoked, or has already been used.
                </Alert>
              )
            )}
            <Button
              onClick={() => accept.mutate()}
              loading={accept.isPending}
              disabled={demo}
            >
              Accept invite
            </Button>
          </Stack>
        </Card>
      </Center>
    </PublicPageShell>
  );
}
