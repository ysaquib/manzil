// Single-recipient email invites. Reusable links live in InvitationLinksSection.
// Owner-gating here is UX; the API is owner-only regardless (frontend/AGENTS.md).
import {
  ActionIcon,
  Button,
  CopyButton,
  Group,
  Select,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconLink, IconRefresh } from "@tabler/icons-react";
import { useState } from "react";

import { ConfirmDeleteModal } from "../../components/ConfirmDeleteModal";
import { Section } from "../../components/Section";
import { ApiError } from "../../lib/apiClient";
import {
  invitationLinkForCurrentOrigin,
  useCreateInvite,
  useInvites,
  useResendInvite,
  useRevokeInvite,
  type Invite,
} from "./api";

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
  const resend = useResendInvite(huntId);
  const [confirming, setConfirming] = useState(false);
  const expires = new Date(invite.expires_at).toLocaleDateString();
  const recipient = invite.email ?? "Link-only invite";
  return (
    <Group justify="space-between" wrap="nowrap">
      <Stack gap={0} style={{ minWidth: 0 }}>
        <Text size="sm" truncate>
          {recipient}
        </Text>
        <Text size="xs" c="dimmed">
          {invite.role_granted === "curator" ? "Curator" : "Member"} · email {invite.delivery_status.replaceAll("_", " ")} · expires {expires}
        </Text>
      </Stack>
      <Group gap="xs" wrap="nowrap">
        <CopyButton value={invitationLinkForCurrentOrigin(invite.link)}>
          {({ copied, copy }) => (
            <Tooltip label={copied ? "Copied" : "Copy invite link"}>
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label={`Copy invite link for ${recipient}`}
                onClick={copy}
              >
                <IconLink size={15} />
              </ActionIcon>
            </Tooltip>
          )}
        </CopyButton>
        {["failed", "bounced", "suppressed", "complained"].includes(invite.delivery_status) && (
          <Tooltip label="Resend invitation email">
            <ActionIcon
              variant="subtle"
              color="gray"
              aria-label={`Resend invitation email to ${recipient}`}
              loading={resend.isPending}
              onClick={() =>
                resend.mutate(invite.id, {
                  onSuccess: () => notifications.show({ message: "Invitation queued again", color: "green" }),
                  onError: notifyError("Couldn't resend invitation"),
                })
              }
            >
              <IconRefresh size={15} />
            </ActionIcon>
          </Tooltip>
        )}
        <ActionIcon
          variant="subtle"
          color="red"
          aria-label="revoke invite"
          loading={revoke.isPending}
          onClick={() => setConfirming(true)}
        >
          ✕
        </ActionIcon>
      </Group>

      {/* Reversible: a revoked invite is re-sendable from the form above, so
          this asks for a look and a click rather than a typed name. */}
      <ConfirmDeleteModal
        opened={confirming}
        onClose={() => setConfirming(false)}
        noun={{ singular: "invite", plural: "invites" }}
        title="Revoke this invite?"
        confirmLabel="Revoke invite"
        requireTypedConfirmation={false}
        loading={revoke.isPending}
        warning="The invite link stops working immediately. You can send them a new one from this section."
        targets={[
          {
            id: invite.id,
            label: recipient,
            description: `${
              invite.role_granted === "curator" ? "Curator" : "Member"
            } · expires ${expires}`,
          },
        ]}
        onConfirm={() =>
          revoke.mutate(invite.id, {
            onSuccess: () => setConfirming(false),
            onError: notifyError("Couldn't revoke invite"),
          })
        }
      />
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
        onError: (error) => {
          notifyError("Couldn't create invite")(error);
        },
      },
    );

  return (
    <Section title="Invite by email">
      <Stack gap="sm">
        {/* Two rows on every width, not just on a phone: the address needs the
            whole line to stay readable, and a three-up row at 375px squeezes
            the email to about a dozen characters before it wraps anyway. */}
        <Stack gap="sm">
          <TextInput
            label="Email"
            placeholder="teammate@example.com"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.currentTarget.value)}
          />
          <Group align="flex-end" gap="sm" justify="space-between" wrap="nowrap">
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
            <Button
              onClick={submit}
              loading={createInvite.isPending}
              disabled={!email.trim()}
              style={{ flex: 1, maxWidth: "12rem" }}
            >
              Send invite
            </Button>
          </Group>
        </Stack>

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
