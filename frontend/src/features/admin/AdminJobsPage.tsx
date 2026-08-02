// Jobs (AD-5): the queue as something to act on, across every Hunt.
//
// The one state worth designing around is a **stale lock** — a `running` Job
// whose worker died. It stays running forever, holding a claim nobody will
// release, and it is invisible in a per-Hunt Tasks tab because from there it
// just looks slow. So it gets its own filter and its own bulk action.
import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Switch,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconAlertTriangle, IconLockOpen } from "@tabler/icons-react";
import { useState } from "react";

import { useAdminJobs, useJobAction, useReleaseLocks, type JobRow } from "./api";

const STATES = ["failed", "running", "queued", "waiting_user", "done", "cancelled"];

const STATE_COLOR: Record<string, string> = {
  failed: "red",
  running: "green",
  queued: "gray",
  waiting_user: "yellow",
  done: "gray",
  cancelled: "gray",
};

function age(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86_400)}d`;
}

function JobActions({ job }: { job: JobRow }) {
  const action = useJobAction();
  const retryable = job.state === "failed" || job.state === "cancelled";
  const cancellable = job.state !== "done" && job.state !== "cancelled";

  return (
    <Group gap={4} wrap="nowrap">
      {retryable && (
        <Button
          size="compact-xs"
          variant="default"
          loading={action.isPending}
          onClick={() => action.mutate({ jobId: job.id, action: "retry" })}
        >
          Retry
        </Button>
      )}
      {cancellable && (
        <Button
          size="compact-xs"
          variant="subtle"
          color="red"
          loading={action.isPending}
          onClick={() => action.mutate({ jobId: job.id, action: "cancel" })}
        >
          Cancel
        </Button>
      )}
    </Group>
  );
}

export function AdminJobsPage() {
  const [state, setState] = useState<string | null>("failed");
  const [staleOnly, setStaleOnly] = useState(false);
  const jobs = useAdminJobs(staleOnly ? null : state, staleOnly);
  const releaseLocks = useReleaseLocks();

  const staleCount = (jobs.data ?? []).filter((job) => job.stale).length;

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={2}>Jobs</Title>
        <Group gap="xs">
          <Switch
            size="xs"
            label="Stale locks only"
            checked={staleOnly}
            onChange={(event) => setStaleOnly(event.currentTarget.checked)}
          />
          <Button
            size="xs"
            variant="default"
            leftSection={<IconLockOpen size={14} />}
            loading={releaseLocks.isPending}
            onClick={() => releaseLocks.mutate()}
          >
            Release stale locks
          </Button>
        </Group>
      </Group>

      {!staleOnly && (
        <Group gap={4}>
          {STATES.map((value) => (
            <Button
              key={value}
              size="compact-xs"
              variant={state === value ? "light" : "subtle"}
              color={state === value ? "primary" : "gray"}
              onClick={() => setState(value)}
            >
              {value.replace("_", " ")}
            </Button>
          ))}
          <Button
            size="compact-xs"
            variant={state === null ? "light" : "subtle"}
            color={state === null ? "primary" : "gray"}
            onClick={() => setState(null)}
          >
            all
          </Button>
        </Group>
      )}

      {staleCount > 0 && !staleOnly && (
        <Alert color="yellow" icon={<IconAlertTriangle size={16} />}>
          {staleCount} Job{staleCount === 1 ? "" : "s"} {staleCount === 1 ? "is" : "are"} holding a
          stale lock — the worker that claimed them is gone. Releasing re-queues them; nothing is
          known to be wrong with the work itself.
        </Alert>
      )}

      {releaseLocks.isSuccess && (
        <Alert color="green">{releaseLocks.data?.detail}</Alert>
      )}

      <Card padding={0} radius="md" withBorder>
        {jobs.isPending && (
          <Group p="md">
            <Loader size="sm" />
          </Group>
        )}
        {jobs.data?.length === 0 && (
          <Text p="md" size="sm" c="dimmed">
            No Jobs in this state.
          </Text>
        )}
        {jobs.data && jobs.data.length > 0 && (
          <Table.ScrollContainer minWidth={760}>
            <Table highlightOnHover verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Job</Table.Th>
                  <Table.Th>Hunt</Table.Th>
                  <Table.Th>Type · stage</Table.Th>
                  <Table.Th>State</Table.Th>
                  <Table.Th ta="end">Try</Table.Th>
                  <Table.Th ta="end">Cost</Table.Th>
                  <Table.Th ta="end">Age</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {jobs.data.map((job) => (
                  <Table.Tr key={job.id}>
                    <Table.Td>
                      <Text size="xs" ff="monospace">
                        {job.id.slice(0, 8)}
                      </Text>
                      {job.listing_name && (
                        <Text size="xs" c="dimmed" lineClamp={1}>
                          {job.listing_name}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{job.hunt_name ?? "—"}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs">
                        {job.type} · <Text span ff="monospace">{job.current_stage ?? "—"}</Text>
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4}>
                        <Badge size="sm" variant="light" color={STATE_COLOR[job.state] ?? "gray"}>
                          {job.state.replace("_", " ")}
                        </Badge>
                        {job.stale && (
                          <Badge size="sm" variant="light" color="yellow">
                            stale lock
                          </Badge>
                        )}
                      </Group>
                      {job.error && (
                        <Text size="xs" c="red" lineClamp={1} maw={280}>
                          {job.error}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs">
                      {job.attempts}
                    </Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs">
                      ${job.cost_actual_usd.toFixed(4)}
                    </Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs">
                      {age(job.created_at)}
                    </Table.Td>
                    <Table.Td>
                      <JobActions job={job} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Card>
    </Stack>
  );
}
