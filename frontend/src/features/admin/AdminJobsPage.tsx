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
  Divider,
  Drawer,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconAlertTriangle, IconLockOpen } from "@tabler/icons-react";
import { useMediaQuery } from "@mantine/hooks";
import { useState } from "react";

import { TablePagination, usePagedRows } from "../../components/TablePagination";
import { ConfirmDeleteModal } from "../../components/ConfirmDeleteModal";
import {
  useAdminDeleteJob,
  useAdminJob,
  useAdminJobs,
  useJobAction,
  useReleaseLocks,
  type JobRow,
} from "./api";
import { JobWarnings } from "../jobs/JobWarnings";

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
          onClick={(event) => {
            event.stopPropagation();
            action.mutate({ jobId: job.id, action: "retry" });
          }}
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
          onClick={(event) => {
            event.stopPropagation();
            action.mutate({ jobId: job.id, action: "cancel" });
          }}
        >
          Cancel
        </Button>
      )}
    </Group>
  );
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function AdminJobDrawer({ jobId, onClose }: { jobId: string | null; onClose: () => void }) {
  const detail = useAdminJob(jobId);
  const action = useJobAction();
  const deleteJob = useAdminDeleteJob();
  const [deleteOpened, setDeleteOpened] = useState(false);
  const job = detail.data;

  return (
    <Drawer opened={jobId !== null} onClose={onClose} position="right" size="xl" title="Job detail">
      {detail.isPending && <Loader size="sm" />}
      {detail.error && <Alert color="red">Could not load this Job.</Alert>}
      {job && (
        <Stack gap="md">
          <Group justify="space-between" align="flex-start">
            <div>
              <Text fw={700}>{job.listing_name ?? job.hunt_name ?? "Hunt-wide Job"}</Text>
              <Text size="xs" ff="monospace" c="dimmed">{job.id}</Text>
            </div>
            <Badge variant="light" color={STATE_COLOR[job.state] ?? "gray"}>
              {job.state.replace("_", " ")}
            </Badge>
          </Group>

          {job.error && <Alert color="red" title="Terminal error">{job.error}</Alert>}
          <JobWarnings warnings={job.warnings} />

          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
            <Text size="sm"><Text span c="dimmed">Hunt: </Text>{job.hunt_name ?? "—"}</Text>
            <Text size="sm"><Text span c="dimmed">Type: </Text>{job.type}</Text>
            <Text size="sm"><Text span c="dimmed">Stage: </Text>{job.current_stage ?? "—"}</Text>
            <Text size="sm"><Text span c="dimmed">Attempts: </Text>{job.attempts}</Text>
            <Text size="sm">
              <Text span c="dimmed">Requested by: </Text>
              {job.requested_by_name ?? job.requested_by_email ?? (job.requested_by ? job.requested_by.slice(0, 8) : "Scheduler")}
            </Text>
            <Text size="sm"><Text span c="dimmed">Duration: </Text>{formatDuration(job.duration_seconds)}</Text>
            <Text size="sm"><Text span c="dimmed">Started: </Text>{job.started_at ? new Date(job.started_at).toLocaleString() : "—"}</Text>
            <Text size="sm"><Text span c="dimmed">Finished: </Text>{job.finished_at ? new Date(job.finished_at).toLocaleString() : "—"}</Text>
          </SimpleGrid>

          <Divider />
          <Title order={4}>Plan</Title>
          {job.plan ? (
            <pre style={{ margin: 0, overflowX: "auto", fontSize: 12 }}>{JSON.stringify(job.plan, null, 2)}</pre>
          ) : <Text size="sm" c="dimmed">No plan manifest was recorded.</Text>}

          <Divider />
          <Title order={4}>Timeline</Title>
          {job.events.length === 0 ? <Text size="sm" c="dimmed">No events recorded.</Text> : (
            <Stack gap="xs">
              {job.events.map((event, index) => (
                <Card key={`${event.at}-${event.stage}-${index}`} padding="xs" withBorder>
                  <Group justify="space-between" gap="xs">
                    <Text size="sm" fw={600}>{event.stage} · {event.event.replaceAll("_", " ")}</Text>
                    <Text size="xs" c="dimmed">{new Date(event.at).toLocaleString()}</Text>
                  </Group>
                  {Object.keys(event.detail).length > 0 && (
                    <pre style={{ marginBottom: 0, overflowX: "auto", fontSize: 11 }}>{JSON.stringify(event.detail, null, 2)}</pre>
                  )}
                </Card>
              ))}
            </Stack>
          )}

          <Divider />
          <Group justify="space-between"><Title order={4}>Stage costs</Title><Text fw={700}>${job.cost_actual_usd.toFixed(4)} billed</Text></Group>
          {job.stage_costs.length === 0 ? <Text size="sm" c="dimmed">No Stage costs recorded.</Text> : (
            <Table.ScrollContainer minWidth={920}>
              <Table verticalSpacing="xs">
                <Table.Thead><Table.Tr><Table.Th>Stage</Table.Th><Table.Th ta="end">LLM</Table.Th><Table.Th ta="end">Fetch</Table.Th><Table.Th ta="end">Calls</Table.Th><Table.Th ta="end">Tokens in/out</Table.Th><Table.Th ta="end">Cache read/write</Table.Th><Table.Th>Providers</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>{job.stage_costs.map((cost) => (
                  <Table.Tr key={cost.stage}>
                    <Table.Td ff="monospace" fz="xs">{cost.stage}</Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs">${cost.llm_cost_usd.toFixed(6)}</Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs">${cost.fetch_cost_usd.toFixed(6)}</Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs">{cost.llm_calls} / {cost.fetch_calls}</Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs">{cost.input_tokens} / {cost.output_tokens}</Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs">{cost.cache_read_tokens} / {cost.cache_write_tokens}</Table.Td>
                    <Table.Td fz="xs">{Object.entries(cost.fetch_calls_by_provider).map(([name, calls]) => `${name}: ${calls}`).join(" · ") || "—"}</Table.Td>
                  </Table.Tr>
                ))}</Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}

          <Group justify="flex-end">
            {(job.state === "failed" || job.state === "cancelled") && (
              <Button variant="default" loading={action.isPending} onClick={() => action.mutate({ jobId: job.id, action: "retry" })}>Retry</Button>
            )}
            {job.state !== "done" && job.state !== "cancelled" && (
              <Button variant="subtle" color="red" loading={action.isPending} onClick={() => action.mutate({ jobId: job.id, action: "cancel" })}>Cancel</Button>
            )}
            {["failed", "cancelled", "done"].includes(job.state) && (
              <Button color="red" variant="light" onClick={() => setDeleteOpened(true)}>Delete Job</Button>
            )}
          </Group>
          <ConfirmDeleteModal
            opened={deleteOpened}
            onClose={() => setDeleteOpened(false)}
            targets={[{ id: job.id, label: `${job.listing_name ?? job.hunt_name ?? "Unscoped Job"} · ${job.id.slice(0, 8)}` }]}
            noun={{ singular: "Job", plural: "Jobs" }}
            warning="This removes the Job from admin product views. Its billed cost, Stage costs, timeline, and audit record remain in Postgres."
            loading={deleteJob.isPending}
            onConfirm={() => deleteJob.mutate(job.id, { onSuccess: onClose })}
          />
        </Stack>
      )}
    </Drawer>
  );
}

export function AdminJobsPage() {
  const [state, setState] = useState<string | null>("failed");
  const [staleOnly, setStaleOnly] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const jobs = useAdminJobs(staleOnly ? null : state, staleOnly);
  // demo-guarded: useReleaseLocks — `releaseLocks.data?.detail` is read below,
  // and an intercepted demo write would leave `isSuccess` true with nothing to
  // show: an empty "it worked" alert for an operation that did not run. No
  // guard is added here because the whole panel is unreachable for a demo
  // subject by a *database* control rather than a frontend one — the demo
  // principal is not a Site Admin, and `private.is_site_admin()` is itself
  // demo-aware (DESIGN §16 0a), so `/admin/me` answers false and AdminLayout
  // redirects before this page mounts.
  const releaseLocks = useReleaseLocks();
  const isCompact = useMediaQuery("(max-width: 48em)") ?? false;

  const staleCount = (jobs.data ?? []).filter((job) => job.stale).length;
  const paged = usePagedRows(jobs.data ?? [], "admin-jobs");

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center" wrap="wrap" gap="xs">
        <Title order={2}>Jobs</Title>
        <Group gap="xs" wrap="wrap">
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
          <>
          {isCompact ? (
            <Stack gap="xs" p="xs">
              {paged.items.map((job) => (
                <Card key={job.id} padding="sm" radius="sm" withBorder>
                  <Group justify="space-between" align="flex-start" wrap="nowrap">
                    <div style={{ minWidth: 0 }}>
                      <Text size="xs" ff="monospace">
                        {job.id.slice(0, 8)}
                      </Text>
                      <Text size="sm" fw={600} truncate>
                        {job.listing_name ?? job.hunt_name ?? "Unscoped Job"}
                      </Text>
                      {job.listing_name && (
                        <Text size="xs" c="dimmed" truncate>
                          {job.hunt_name ?? "—"}
                        </Text>
                      )}
                    </div>
                    <Group gap={4} justify="flex-end">
                      <Badge size="sm" variant="light" color={STATE_COLOR[job.state] ?? "gray"}>
                        {job.state.replace("_", " ")}
                      </Badge>
                      {job.stale && <Badge size="sm" color="yellow">stale</Badge>}
                    </Group>
                  </Group>
                  <Text size="xs" mt="xs">
                    {job.type} · <Text span ff="monospace">{job.current_stage ?? "—"}</Text>
                  </Text>
                  {job.error && <Text size="xs" c="red" mt={4} lineClamp={2}>{job.error}</Text>}
                  <Group justify="space-between" align="flex-end" mt="sm">
                    <Text size="xs" c="dimmed" ff="monospace">
                      try {job.attempts} · ${job.cost_actual_usd.toFixed(4)} · {age(job.created_at)}
                    </Text>
                    <JobActions job={job} />
                  </Group>
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    mt="xs"
                    onClick={() => setSelectedJobId(job.id)}
                  >
                    Inspect details
                  </Button>
                </Card>
              ))}
            </Stack>
          ) : (
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
                {paged.items.map((job) => (
                  <Table.Tr
                    key={job.id}
                    onClick={() => setSelectedJobId(job.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") setSelectedJobId(job.id);
                    }}
                    tabIndex={0}
                    role="button"
                    aria-label={`Inspect ${job.listing_name ?? job.hunt_name ?? "Job"}`}
                    style={{ cursor: "pointer" }}
                  >
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
          <TablePagination state={paged} noun="Jobs" />
          </>
        )}
      </Card>
      <AdminJobDrawer jobId={selectedJobId} onClose={() => setSelectedJobId(null)} />
    </Stack>
  );
}
