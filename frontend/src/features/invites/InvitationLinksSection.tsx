import {
  Accordion,
  ActionIcon,
  Button,
  CopyButton,
  Group,
  Modal,
  NumberInput,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { Section } from "../../components/Section";
import { ApiError } from "../../lib/apiClient";
import {
  type InvitationLink,
  invitationLinkForCurrentOrigin,
  useCreateInvitationLink,
  useDeleteInvitationLink,
  useInvitationLinks,
  usePatchInvitationLink,
} from "./api";

function dateInputValue(date: Date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function expirationTimestamp(date: string) {
  return new Date(`${date}T23:59:59.999`).toISOString();
}

function defaultExpiryDate() {
  const expiry = new Date();
  expiry.setDate(expiry.getDate() + 7);
  return dateInputValue(expiry);
}

function todayDate() {
  return dateInputValue(new Date());
}

function errorNotification(title: string, error: unknown) {
  notifications.show({
    title,
    message: error instanceof ApiError ? error.message : "Unexpected error",
    color: "red",
  });
}

function LinkRow({ link, huntId }: { link: InvitationLink; huntId: string }) {
  const patchLink = usePatchInvitationLink(huntId);
  const deleteLink = useDeleteInvitationLink(huntId);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [name, setName] = useState(link.name ?? "");
  const [unlimited, setUnlimited] = useState(link.max_uses === null);
  const [maxUses, setMaxUses] = useState<number>(link.max_uses ?? Math.max(1, link.use_count + 1));
  const [expires, setExpires] = useState<string | null>(dateInputValue(new Date(link.expires_at)));
  const shareLink = invitationLinkForCurrentOrigin(link.link);

  const save = () => {
    if (!expires) return;
    patchLink.mutate(
      {
        id: link.id,
        body: {
          name: name.trim() || null,
          max_uses: unlimited ? null : maxUses,
          expires_at: expirationTimestamp(expires),
        },
      },
      {
        onSuccess: () => setEditing(false),
        onError: (error) => errorNotification("Couldn't update Invitation Link", error),
      },
    );
  };

  return (
    <Stack gap="xs">
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <Stack gap={2}>
          <Text size="sm" fw={600}>
            {link.name ?? "Invitation Link"}
          </Text>
          <Text size="xs" c="dimmed">
            {link.use_count} / {link.max_uses ?? "unlimited"} uses · Created{" "}
            {new Date(link.created_at).toLocaleDateString()} · expires{" "}
            {new Date(link.expires_at).toLocaleDateString()}
          </Text>
        </Stack>
        <Group gap="xs">
          <CopyButton value={shareLink}>
            {({ copied, copy }) => (
              <Button size="xs" variant="default" onClick={copy}>
                {copied ? "Copied" : "Copy"}
              </Button>
            )}
          </CopyButton>
          <Button size="xs" variant="subtle" onClick={() => setEditing((value) => !value)}>
            Edit
          </Button>
          <ActionIcon
            color="red"
            variant="subtle"
            aria-label="Delete Invitation Link"
            onClick={() => setConfirmDelete(true)}
          >
            ✕
          </ActionIcon>
        </Group>
      </Group>

      {editing && (
        <Stack gap="sm">
          <TextInput
            label="Name"
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            maxLength={80}
          />
          <Group align="flex-end" wrap="wrap">
            <NumberInput
              label="Use limit"
              min={1}
              value={unlimited ? "" : maxUses}
              disabled={unlimited}
              onChange={(value) => typeof value === "number" && setMaxUses(value)}
            />
            <Button variant="default" onClick={() => setUnlimited((value) => !value)}>
              {unlimited ? "Set a limit" : "Make unlimited"}
            </Button>
            <DatePickerInput
              label="Expires"
              value={expires}
              onChange={setExpires}
              minDate={todayDate()}
              valueFormat="MMM D, YYYY"
            />
            <Button onClick={save} loading={patchLink.isPending} disabled={!expires}>
              Save
            </Button>
          </Group>
        </Stack>
      )}

      <Accordion variant="contained">
        <Accordion.Item value="joins">
          <Accordion.Control>Joined with this link ({link.joins.length})</Accordion.Control>
          <Accordion.Panel>
            {link.joins.length === 0 ? (
              <Text size="sm" c="dimmed">No one has joined with this link.</Text>
            ) : (
              <Stack gap="xs">
                {link.joins.map((join) => (
                  <Group key={join.user_id} justify="space-between">
                    <Text size="sm">{join.display_name}</Text>
                    <Text size="xs" c="dimmed">{new Date(join.joined_at).toLocaleDateString()}</Text>
                  </Group>
                ))}
              </Stack>
            )}
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>

      <Modal opened={confirmDelete} onClose={() => setConfirmDelete(false)} title="Delete Invitation Link?">
        <Stack>
          <Text size="sm">The link will stop working immediately. Its join history stays recorded.</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmDelete(false)}>Cancel</Button>
            <Button
              color="red"
              loading={deleteLink.isPending}
              onClick={() =>
                deleteLink.mutate(link.id, {
                  onSuccess: () => setConfirmDelete(false),
                  onError: (error) => errorNotification("Couldn't delete Invitation Link", error),
                })
              }
            >
              Delete link
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

export function InvitationLinksSection({ huntId }: { huntId: string }) {
  const { data: links = [] } = useInvitationLinks(huntId);
  const createLink = useCreateInvitationLink(huntId);
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [expires, setExpires] = useState<string | null>(defaultExpiryDate());
  const [unlimited, setUnlimited] = useState(true);
  const [maxUses, setMaxUses] = useState(1);
  const active = links.filter((link) => link.status === "active");
  const inactive = links.filter((link) => link.status !== "active");

  const openCreate = () => {
    setName(`Invitation Link ${active.length + 1}`);
    setExpires(defaultExpiryDate());
    setUnlimited(true);
    setMaxUses(1);
    setCreateOpen(true);
  };

  const create = () => {
    if (!expires) return;
    createLink.mutate(
      {
        name: name.trim() || null,
        max_uses: unlimited ? null : maxUses,
        expires_at: expirationTimestamp(expires),
      },
      {
        onSuccess: (link) => {
          void navigator.clipboard?.writeText(invitationLinkForCurrentOrigin(link.link));
          notifications.show({ message: "Invitation Link created and copied", color: "green" });
          setCreateOpen(false);
        },
        onError: (error) => errorNotification("Couldn't create Invitation Link", error),
      },
    );
  };

  return (
    <Section title="Invitation links">
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          Anyone with an active link can join this Hunt as a Member.
        </Text>
        <Button variant="subtle" size="compact-sm" onClick={openCreate} style={{ alignSelf: "flex-start" }}>
          Create invitation link
        </Button>

        <Stack gap="sm">
          <Text size="xs" fw={600} c="dimmed">Active</Text>
          {active.length ? active.map((link) => <LinkRow key={link.id} link={link} huntId={huntId} />) : <Text size="sm" c="dimmed">No active Invitation Links.</Text>}
        </Stack>
        {inactive.length > 0 && (
          <Stack gap="sm">
            <Text size="xs" fw={600} c="dimmed">Inactive</Text>
            {inactive.map((link) => <LinkRow key={link.id} link={link} huntId={huntId} />)}
          </Stack>
        )}
      </Stack>

      <Modal
        opened={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Create invitation link"
        transitionProps={{ duration: 0 }}
      >
        <Stack gap="sm">
          <TextInput
            label="Name"
            description="Optional label for your own reference."
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            maxLength={80}
          />
          <Group align="flex-end" wrap="wrap">
            <NumberInput
              label="Use limit"
              min={1}
              disabled={unlimited}
              value={unlimited ? "" : maxUses}
              onChange={(value) => typeof value === "number" && setMaxUses(value)}
            />
            <Button variant="default" onClick={() => setUnlimited((value) => !value)}>
              {unlimited ? "Set a limit" : "Make unlimited"}
            </Button>
          </Group>
          <DatePickerInput
            label="Expires"
            value={expires}
            onChange={setExpires}
            minDate={todayDate()}
            valueFormat="MMM D, YYYY"
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={create} loading={createLink.isPending} disabled={!expires}>
              Create and copy link
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Section>
  );
}
