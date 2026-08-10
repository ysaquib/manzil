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
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useDebouncedValue, useMediaQuery } from "@mantine/hooks";
import { IconExternalLink, IconSearch } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  TablePagination,
  usePageControls,
  usePagerState,
} from "../../components/TablePagination";
import { useAdminHunts, useHuntActivity, type ActivityEntry } from "./api";

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

function HuntDetail({ huntId, name }: { huntId: string; name: string }) {
  const activity = useHuntActivity(huntId);

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
          Open as owner
        </Button>
      </Group>

      <Alert color="accent" mb="sm">
        You are not a member of this Hunt. Opening it shows the Owner&apos;s screens with a
        persistent banner; you stay out of the member list and out of Presence, and Visits are
        read-only.
      </Alert>

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
          <TablePagination state={paged} noun="Hunts" />
          </>
        )}
      </Card>

      {selectedHunt && <HuntDetail huntId={selectedHunt.hunt_id} name={selectedHunt.name} />}
    </Stack>
  );
}
