// Invites surface (P2-8, DESIGN §13.1) — owner only. Create an invite (optional
// email + role), then share the returned link; list and revoke pending invites.
// Owner-gating here is UX; the API is owner-only regardless (frontend/AGENTS.md).
import {
  ActionIcon,
  Alert,
  Button,
  CopyButton,
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

function InviteLink({ link }: { link: string }) {
  return (
    <Group gap="xs" wrap="nowrap">
      <TextInput readOnly value={link} style={{ flex: 1 }} aria-label="Invite link" />
      <CopyButton value={link}>
        {({ copied, copy }) => (
          <Button variant="default" onClick={copy}>
            {copied ? "Copied" : "Copy link"}
          </Button>
        )}
      </CopyButton>
    </Group>
  );
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
        <CopyButton value={invite.link}>
          {({ copied, copy }) => (
            <Button size="xs" variant="subtle" onClick={copy}>
              {copied ? "Copied" : "Copy link"}
            </Button>
          )}
        </CopyButton>
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
  const [lastLink, setLastLink] = useState<string | null>(null);

  const submit = () =>
    createInvite.mutate(
      { email: email.trim() || undefined, role },
      {
        onSuccess: (invite) => {
          setLastLink(invite.link);
          setEmail("");
          notifications.show({ message: "Invite created", color: "green" });
        },
        onError: notifyError("Couldn't create invite"),
      },
    );

  return (
    <Section title="Invites">
      <Stack gap="sm">
        <Group align="flex-end" gap="sm">
          <TextInput
            label="Email (optional)"
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
          <Button onClick={submit} loading={createInvite.isPending}>
            Create invite
          </Button>
        </Group>

        {lastLink && (
          <Alert color="green" title="Invite ready — share this link">
            <Stack gap="xs">
              <Text size="xs" c="dimmed">
                Anyone with this link can join. It expires; revoke it below if you change your mind.
              </Text>
              <InviteLink link={lastLink} />
            </Stack>
          </Alert>
        )}

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
