// Single-recipient email invites. Reusable links live in InvitationLinksSection.
// Owner-gating here is UX; the API is owner-only regardless (frontend/AGENTS.md).
import {
  ActionIcon,
  Button,
  Group,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { Section } from "../../components/Section";
import { ApiError } from "../../lib/apiClient";
import { useCreateInvite, useInvites, useRevokeInvite, type Invite } from "./api";

function notifyError(title: string) {
  return (error: unknown) =>
    notifications.show({
      title,
      message: error instanceof ApiError ? error.message : "Unexpected error",
      color: "red",
    });
}

function PendingInvite({ invite, huntId }: { invite: Invite; huntId: string }) {
  const revoke = useRevokeInvite(huntId);
  const expires = new Date(invite.expires_at).toLocaleDateString();
  return (
    <Group justify="space-between" wrap="nowrap">
      <Stack gap={0} style={{ minWidth: 0 }}>
        <Text size="sm" truncate>
          {invite.email ?? "Link-only invite"}
        </Text>
        <Text size="xs" c="dimmed">
          {invite.role_granted === "curator" ? "Curator" : "Member"} · expires {expires}
        </Text>
      </Stack>
      <Group gap="xs" wrap="nowrap">
        <ActionIcon
          variant="subtle"
          color="red"
          aria-label="revoke invite"
          loading={revoke.isPending}
          onClick={() =>
            revoke.mutate(invite.id, { onError: notifyError("Couldn't revoke invite") })
          }
        >
          ✕
        </ActionIcon>
      </Group>
    </Group>
  );
}

export function InvitesSection({ huntId }: { huntId: string }) {
  const { data: invites = [] } = useInvites(huntId);
  const createInvite = useCreateInvite(huntId);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"member" | "curator">("member");

  const submit = () =>
    createInvite.mutate(
      { email: email.trim(), role },
      {
        onSuccess: () => {
          setEmail("");
          notifications.show({ message: "Invite created", color: "green" });
        },
        onError: notifyError("Couldn't create invite"),
      },
    );

  return (
    <Section title="Invite by email">
      <Stack gap="sm">
        <Group align="flex-end" gap="sm">
          <TextInput
            label="Email"
            placeholder="teammate@example.com"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.currentTarget.value)}
            style={{ flex: 1 }}
          />
          <Select
            label="Role"
            w={130}
            data={[
              { value: "member", label: "Member" },
              { value: "curator", label: "Curator" },
            ]}
            value={role}
            allowDeselect={false}
            onChange={(value) => value && setRole(value as "member" | "curator")}
          />
          <Button onClick={submit} loading={createInvite.isPending} disabled={!email.trim()}>
            Send invite
          </Button>
        </Group>

        {invites.length > 0 && (
          <Stack gap="xs">
            <Text size="xs" fw={600} c="dimmed">
              Pending
            </Text>
            {invites.map((invite) => (
              <PendingInvite key={invite.id} invite={invite} huntId={huntId} />
            ))}
          </Stack>
        )}
        {invites.length === 0 && (
          <Text size="xs" c="dimmed">
            No pending invites.
          </Text>
        )}
      </Stack>
    </Section>
  );
}
