import { Alert, Button, Card, Center, Stack, Text, Title } from "@mantine/core";
import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { PublicPageShell } from "../../components/PublicPageShell";
import { useAcceptInvite } from "./api";

export function InviteAcceptPage() {
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const accept = useAcceptInvite(token);

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
            {accept.error && (
              <Alert color="red" title="Invite unavailable">
                This invite has expired, was revoked, or has already been used.
              </Alert>
            )}
            <Button onClick={() => accept.mutate()} loading={accept.isPending}>
              Accept invite
            </Button>
          </Stack>
        </Card>
      </Center>
    </PublicPageShell>
  );
}
