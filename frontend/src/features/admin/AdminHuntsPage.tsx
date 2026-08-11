// Hunts (AD-4). Every Hunt with the roll-ups only visible from above, and the
// door into the ghost view.
//
// "Open as owner" is a plain link to the Hunt's ordinary URL, not a special
// mode. That is the point of the SELECT-side read predicate: the existing Hunt
// screens already serve a Site Admin, so there is no parallel implementation to
// keep in step. What the admin sees differently — the banner, no Presence,
// read-only Visits — is derived from not being a member, not from how they got
// there.
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useDebouncedValue, useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import {
  IconExternalLink,
  IconLock,
  IconLockOpen,
  IconSearch,
  IconTrash,
} from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  ConfirmDeleteModal,
  type DeletionTarget,
} from "../../components/ConfirmDeleteModal";
import {
  TablePagination,
  usePageControls,
  usePagerState,
} from "../../components/TablePagination";
import { ApiError } from "../../lib/apiClient";
import {
  useAdminHuntManagement,
  useAdminHunts,
  useDeleteAdminHunt,
  useHuntActivity,
  useSetAdminHuntLock,
  useTransferAdminHuntOwnership,
  type ActivityEntry,
  type HuntSummary,
} from "./api";

function relative(iso: string | null): string {
  if (!iso) return "never";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  return `${days}d ago`;
}

const ACTIVITY_LABELS: Record<string, string> = {
  fee_set: "Fee set",
  override_set: "Override",
  member_joined: "Joined",
  member_role_changed: "Role changed",
  member_left: "Left",
  listing_curated: "Listing curated",
  deleted: "Deleted",
  visit_created: "Visit created",
  visit_ended: "Visit ended",
  defect_logged: "Defect logged",
  job_done: "Job done",
  job_failed: "Job failed",
};

function ActivityRow({ entry }: { entry: ActivityEntry }) {
  return (
    <Table.Tr>
      <Table.Td w={140}>
        <Text size="xs" c="dimmed" ff="monospace">
          {new Date(entry.occurred_at).toLocaleString()}
        </Text>
      </Table.Td>
      <Table.Td w={130}>
        <Badge size="xs" variant="light" color={entry.kind === "deleted" ? "red" : "gray"}>
          {ACTIVITY_LABELS[entry.kind] ?? entry.kind}
        </Badge>
      </Table.Td>
      <Table.Td>
        <Text size="sm">{entry.subject_label ?? "—"}</Text>
      </Table.Td>
    </Table.Tr>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Unexpected error";
}

function HuntDetail({ hunt, onDeleted }: { hunt: HuntSummary; onDeleted: () => void }) {
  const { hunt_id: huntId, name } = hunt;
  const activity = useHuntActivity(huntId);
  const management = useAdminHuntManagement(huntId);
  const transfer = useTransferAdminHuntOwnership(huntId);
  const deleteHunt = useDeleteAdminHunt();
  const setLock = useSetAdminHuntLock(huntId);
  const [transferTarget, setTransferTarget] = useState<string | null>(null);
  const [transferOpen, setTransferOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const transferOptions = (management.data?.members ?? [])
    .filter((member) => member.role !== "owner")
    .map((member) => ({ value: member.user_id, label: member.display_name }));
  const transferName =
    transferOptions.find((option) => option.value === transferTarget)?.label ?? "this member";
  const blockedReason = (management.data?.deletion_blockers ?? []).join(" · ") || undefined;
  const locked = management.data?.locked_at !== null && management.data?.locked_at !== undefined;
  const deleteTarget: DeletionTarget = {
    id: huntId,
    label: name,
    description: `${hunt.members} members · ${hunt.listings} Listings · ${hunt.jobs} Jobs`,
    blockedReason,
  };

  return (
    <Card padding="md" radius="md" withBorder>
      <Group justify="space-between" align="center" mb="sm">
        <Title order={5}>{name}</Title>
        <Button
          component={Link}
          to={`/h/${huntId}`}
          size="xs"
          leftSection={<IconExternalLink size={14} />}
        >
          {management.data?.caller_is_member ? "Open Hunt" : "Open as owner"}
        </Button>
      </Group>

      {management.isPending ? (
        <Loader size="xs" mb="sm" />
      ) : management.data?.caller_is_member ? (
        <Alert color="gray" mb="sm">
          You belong to this Hunt. Opening it uses your assigned Hunt role; Site Admin powers
          remain here in the audited panel.
        </Alert>
      ) : (
        <Alert color="accent" mb="sm">
          You are not a member of this Hunt. Opening it shows the Owner&apos;s screens with a
          persistent banner; you stay out of the member list and out of Presence, and Visits are
          read-only.
        </Alert>
      )}

      <Title order={6} mb={4}>
        Hunt management
      </Title>
      <Stack gap="xs" mb="md">
        {locked && (
          <Alert color="yellow" icon={<IconLock size={16} />} title="This Hunt is locked">
            Every Hunt member has read-only access. Unlock it before transferring ownership,
            archiving, restoring, deleting, or changing Hunt data.
          </Alert>
        )}
        <Group justify="space-between" align="center" wrap="wrap">
          <Text size="sm" c="dimmed" maw={520}>
            Locking cancels unfinished Jobs and makes the whole Hunt read-only until a Site Admin
            unlocks it.
          </Text>
          <Button
            variant="default"
            color={locked ? undefined : "yellow"}
            leftSection={locked ? <IconLockOpen size={14} /> : <IconLock size={14} />}
            loading={setLock.isPending}
            disabled={management.isPending || management.isError}
            onClick={() =>
              setLock.mutate(!locked, {
                onSuccess: () =>
                  notifications.show({
                    message: locked ? `${name} unlocked.` : `${name} locked.`,
                    color: locked ? "green" : "yellow",
                  }),
                onError: (error) =>
                  notifications.show({
                    title: `Couldn't ${locked ? "unlock" : "lock"} the Hunt`,
                    message: errorMessage(error),
                    color: "red",
                  }),
              })
            }
          >
            {locked ? "Unlock Hunt" : "Lock Hunt"}
          </Button>
        </Group>
        <Group align="flex-end" wrap="wrap">
          <Select
            label="New Owner"
            placeholder={transferOptions.length ? "Choose an existing member" : "No other members"}
            data={transferOptions}
            value={transferTarget}
            onChange={setTransferTarget}
            searchable
            disabled={management.isPending || management.isError || locked}
            flex={1}
            miw={220}
          />
          <Button
            variant="default"
            disabled={!transferTarget || locked}
            onClick={() => setTransferOpen(true)}
          >
            Transfer ownership
          </Button>
        </Group>
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Text size="sm" c="dimmed" maw={520}>
            The new Owner must already belong to the Hunt. The current Owner becomes a Curator.
          </Text>
          <Button
            color="red"
            variant="light"
            leftSection={<IconTrash size={14} />}
            disabled={management.isPending || management.isError || locked}
            onClick={() => setDeleteOpen(true)}
          >
            Delete Hunt permanently
          </Button>
        </Group>
        {blockedReason && !locked && (
          <Alert color="yellow" title="Deletion is currently blocked">
            {blockedReason}
          </Alert>
        )}
        {management.isError && (
          <Alert color="red" title="Hunt management unavailable">
            The member roster and deletion safety checks could not be loaded. Try again before
            changing this Hunt.
          </Alert>
        )}
      </Stack>

      <Title order={6} mb={4}>
        Recent activity
      </Title>
      {activity.isPending && <Loader size="xs" />}
      {activity.data?.length === 0 && (
        <Text size="sm" c="dimmed">
          Nothing recorded yet.
        </Text>
      )}
      {activity.data && activity.data.length > 0 && (
        <Table.ScrollContainer minWidth={420}>
          <Table verticalSpacing={4}>
            <Table.Tbody>
              {activity.data.slice(0, 25).map((entry, index) => (
                <ActivityRow key={`${entry.occurred_at}-${index}`} entry={entry} />
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      <Modal
        opened={transferOpen}
        onClose={() => setTransferOpen(false)}
        title="Transfer Hunt ownership?"
        centered
      >
        <Stack gap="md">
          <Text size="sm">
            <Text span fw={600}>{transferName}</Text> becomes the Owner of {name}. The current
            Owner becomes a Curator.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setTransferOpen(false)}>
              Cancel
            </Button>
            <Button
              loading={transfer.isPending}
              onClick={() => {
                if (!transferTarget) return;
                transfer.mutate(transferTarget, {
                  onSuccess: () => {
                    setTransferOpen(false);
                    setTransferTarget(null);
                    notifications.show({
                      message: `${transferName} now owns ${name}.`,
                      color: "green",
                    });
                  },
                  onError: (error) =>
                    notifications.show({
                      title: "Couldn't transfer ownership",
                      message: errorMessage(error),
                      color: "red",
                    }),
                });
              }}
            >
              Transfer ownership
            </Button>
          </Group>
        </Stack>
      </Modal>

      <ConfirmDeleteModal
        opened={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        noun={{ singular: "Hunt", plural: "Hunts" }}
        title="Delete this Hunt permanently?"
        confirmLabel="Permanently delete Hunt"
        targets={[deleteTarget]}
        loading={deleteHunt.isPending}
        warning="This permanently removes the Hunt, every Listing association, score, comment, rating, Visit, Job, Rubric, invite, and Hunt-scoped Extraction. Shared Properties, Sources, Floor Plans, images, and Catalog facts remain."
        onConfirm={() =>
          deleteHunt.mutate(
            { huntId, confirmationName: name },
            {
              onSuccess: () => {
                setDeleteOpen(false);
                onDeleted();
                notifications.show({ message: `${name} deleted.`, color: "green" });
              },
              onError: (error) =>
                notifications.show({
                  title: "Couldn't delete the Hunt",
                  message: errorMessage(error),
                  color: "red",
                }),
            },
          )
        }
      >
        <Text size="sm" c="dimmed">
          Impact: {hunt.members} memberships, {hunt.listings} Listings, {hunt.jobs} Jobs, and all
          Visits and collaboration records owned by this Hunt.
        </Text>
      </ConfirmDeleteModal>
    </Card>
  );
}

export function AdminHuntsPage() {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const isCompact = useMediaQuery("(max-width: 48em)") ?? false;
  // Server-side now: this route carries per-Hunt roll-ups, so filtering in the
  // browser meant fetching the whole installation first.
  const [debouncedSearch] = useDebouncedValue(search.trim(), 250);
  const pager = usePagerState("admin-hunts");
  const hunts = useAdminHunts({
    search: debouncedSearch,
    limit: pager.pageSize,
    offset: pager.offset,
  });
  const rows = hunts.data?.items ?? [];
  const paged = usePageControls(pager, hunts.data?.total);

  // A new search is a new list; staying on page 7 of the old one would show an
  // empty table and blame the search.
  const { setPage } = pager;
  useEffect(() => setPage(1), [debouncedSearch, setPage]);

  const selectedHunt = rows.find((hunt) => hunt.hunt_id === selected);

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center" wrap="wrap" gap="xs">
        <Title order={2}>Hunts</Title>
        <TextInput
          size="xs"
          w={isCompact ? "100%" : 240}
          placeholder="Search Hunt or owner…"
          leftSection={<IconSearch size={14} />}
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
        />
      </Group>

      <Card padding={0} radius="md" withBorder>
        {hunts.isPending && (
          <Group p="md">
            <Loader size="sm" />
          </Group>
        )}
        {hunts.data && rows.length === 0 && (
          <Text p="md" size="sm" c="dimmed">
            {debouncedSearch ? "No Hunt matches that search." : "No Hunts yet."}
          </Text>
        )}
        {rows.length > 0 && (
          <>
          {isCompact ? (
            <Stack gap="xs" p="xs">
              {rows.map((hunt) => (
                <Card
                  key={hunt.hunt_id}
                  padding="sm"
                  radius="sm"
                  withBorder
                  onClick={() => setSelected(hunt.hunt_id)}
                  bg={
                    selected === hunt.hunt_id
                      ? "var(--mantine-color-primary-light)"
                      : undefined
                  }
                  style={{ cursor: "pointer" }}
                >
                  <Group justify="space-between" align="flex-start" wrap="nowrap">
                    <div>
                      <Group gap={4} mb={2}>
                        <Text size="sm" fw={600}>
                          {hunt.name}
                        </Text>
                        {hunt.locked_at && <Badge size="xs" color="yellow">Locked</Badge>}
                        {hunt.archived_at && <Badge size="xs" color="gray">Archived</Badge>}
                      </Group>
                      <Text size="xs" c="dimmed">
                        {hunt.owner_name ?? "No owner"} · active {relative(hunt.last_activity_at)}
                      </Text>
                    </div>
                    <Anchor
                      component={Link}
                      to={`/h/${hunt.hunt_id}`}
                      size="xs"
                      onClick={(event) => event.stopPropagation()}
                    >
                      Open
                    </Anchor>
                  </Group>
                  <Group justify="space-between" mt="sm" gap="xs">
                    <Text size="xs" c="dimmed">
                      {hunt.members} members · {hunt.listings} Listings · {hunt.jobs} Jobs
                    </Text>
                    <Text size="xs" ff="monospace" fw={600}>
                      ${hunt.total_cost_usd.toFixed(2)}
                    </Text>
                  </Group>
                </Card>
              ))}
            </Stack>
          ) : (
          <Table.ScrollContainer minWidth={720}>
            <Table highlightOnHover verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Hunt</Table.Th>
                  <Table.Th>Owner</Table.Th>
                  <Table.Th ta="end">Members</Table.Th>
                  <Table.Th ta="end">Listings</Table.Th>
                  <Table.Th ta="end">Jobs</Table.Th>
                  {/* The split is the point: a blended number cannot answer
                      "how much of this was the model?" */}
                  <Table.Th ta="end">LLM</Table.Th>
                  <Table.Th ta="end">Fetch</Table.Th>
                  <Table.Th ta="end">Total</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((hunt) => (
                  <Table.Tr
                    key={hunt.hunt_id}
                    onClick={() => setSelected(hunt.hunt_id)}
                    style={{ cursor: "pointer" }}
                    bg={
                      selected === hunt.hunt_id
                        ? "var(--mantine-color-primary-light)"
                        : undefined
                    }
                  >
                    <Table.Td>
                      <Text size="sm" fw={600}>
                        {hunt.name}
                      </Text>
                      <Group gap={4} mt={2}>
                        {hunt.locked_at && <Badge size="xs" color="yellow">Locked</Badge>}
                        {hunt.archived_at && <Badge size="xs" color="gray">Archived</Badge>}
                      </Group>
                      <Text size="xs" c="dimmed">
                        active {relative(hunt.last_activity_at)}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{hunt.owner_name ?? "—"}</Text>
                    </Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs">
                      {hunt.members}
                    </Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs">
                      {hunt.listings}
                    </Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs">
                      {hunt.jobs}
                    </Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs">
                      ${hunt.llm_cost_usd.toFixed(2)}
                    </Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs">
                      ${hunt.fetch_cost_usd.toFixed(4)}
                    </Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs" fw={600}>
                      ${hunt.total_cost_usd.toFixed(2)}
                    </Table.Td>
                    <Table.Td>
                      <Anchor
                        component={Link}
                        to={`/h/${hunt.hunt_id}`}
                        size="xs"
                        onClick={(event) => event.stopPropagation()}
                      >
                        Open
                      </Anchor>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          )}
          <TablePagination state={paged} noun="Hunts" />
          </>
        )}
      </Card>

      {selectedHunt && (
        <HuntDetail
          key={selectedHunt.hunt_id}
          hunt={selectedHunt}
          onDeleted={() => setSelected(null)}
        />
      )}
    </Stack>
  );
}
