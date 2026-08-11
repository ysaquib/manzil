// System (AD-5): the operator's read-only view of the machine.
//
// Nothing here is editable, deliberately. Changing a model pin is a code change
// and a §20 entry, not a toggle — a settings screen that can silently re-pin a
// stage is how a bill goes wrong quietly. The one control is the orphan scan,
// because a stale lock is an operational fact rather than a configuration one.
//
// Credentials are reported as *presence*, never value, following the convention
// the env probes already use.
import { Badge, Card, Group, Loader, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";
import { Link } from "react-router-dom";

import { useSystem } from "./api";
import classes from "./AdminSystemPage.module.css";

function Health({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "ok" | "warn" | "bad";
}) {
  return (
    <div className={classes.health}>
      <span className={`${classes.dot} ${classes[tone]}`} />
      <div>
        <Text size="xs" c="dimmed" fw={700} tt="uppercase" className={classes.label}>
          {label}
        </Text>
        <Text size="sm" fw={600}>
          {value}
        </Text>
      </div>
    </div>
  );
}

export function AdminSystemPage() {
  const system = useSystem();

  if (system.isPending) return <Loader size="sm" />;
  if (!system.data) return <Text c="dimmed">Could not read system state.</Text>;

  const s = system.data;
  const failureRate = s.finished_24h > 0 ? (100 * s.failed_24h) / s.finished_24h : 0;

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="center">
        <Title order={2}>System</Title>
        <Badge variant="light" color="gray">
          {s.mode} mode
        </Badge>
      </Group>

      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
        <Health
          label="Worker loop"
          value={
            s.worker_status === "live_busy"
              ? `Live · busy (${s.busy_workers}/${s.live_workers})`
              : s.worker_status === "live_idle"
                ? `Live · idle (${s.live_workers})`
                : "Unavailable"
          }
          tone={s.worker_status === "unavailable" ? "bad" : "ok"}
        />
        <Health
          label="Queue"
          value={`${s.queued} queued · ${s.running} running`}
          tone={s.queued > 50 ? "warn" : "ok"}
        />
        <Health
          label="Stale locks"
          value={s.stale_locks === 0 ? "none" : `${s.stale_locks} need release`}
          tone={s.stale_locks === 0 ? "ok" : "warn"}
        />
        <Health
          label="Failures 24h"
          value={`${s.failed_24h} (${failureRate.toFixed(1)}%)`}
          tone={failureRate > 5 ? "bad" : "ok"}
        />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
        <Stack gap="md">
          <Card padding="md" radius="md" withBorder>
            <Group justify="space-between" mb="xs">
              <Title order={5}>Queue</Title>
              {s.stale_locks > 0 && (
                <Text
                  component={Link}
                  to="/admin/jobs"
                  size="xs"
                  c="var(--mantine-primary-color-filled)"
                >
                  Release locks →
                </Text>
              )}
            </Group>
            <Table verticalSpacing={4}>
              <Table.Tbody>
                <Table.Tr>
                  <Table.Td>Oldest queued</Table.Td>
                  <Table.Td ta="end" ff="monospace" fz="xs">
                    {s.oldest_queued_seconds > 0
                      ? `${Math.floor(s.oldest_queued_seconds / 60)}m ${Math.floor(
                          s.oldest_queued_seconds % 60,
                        )}s`
                      : "—"}
                  </Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Td>Finished, 24h</Table.Td>
                  <Table.Td ta="end" ff="monospace" fz="xs">
                    {s.finished_24h}
                  </Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Td>Last migration</Table.Td>
                  <Table.Td ta="end" ff="monospace" fz="xs">
                    {s.last_migration ?? "—"}
                  </Table.Td>
                </Table.Tr>
              </Table.Tbody>
            </Table>
          </Card>

          <Card padding="md" radius="md" withBorder>
            <Group justify="space-between" mb="xs">
              <Title order={5}>External services</Title>
              <Badge size="xs" variant="light" color="gray">
                presence only
              </Badge>
            </Group>
            <Table verticalSpacing={6}>
              <Table.Tbody>
                {s.services.map((service) => (
                  <Table.Tr key={service.name}>
                    <Table.Td>
                      <Text size="sm" fw={600}>
                        {service.name}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {service.detail}
                      </Text>
                    </Table.Td>
                    <Table.Td ta="end">
                      <Badge
                        size="sm"
                        variant="light"
                        color={service.configured ? "green" : "gray"}
                      >
                        {service.configured ? "Key present" : "Not configured"}
                      </Badge>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Card>
        </Stack>

        <Card padding="md" radius="md" withBorder>
          <Group justify="space-between" mb="xs">
            <Title order={5}>Model pins</Title>
            <Badge size="xs" variant="light" color="green">
              {s.priced_models} slugs priced
            </Badge>
          </Group>
          <Table.ScrollContainer minWidth={340}>
            <Table verticalSpacing={4}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Stage</Table.Th>
                  <Table.Th>Slug</Table.Th>
                  <Table.Th ta="end">In · out /Mtok</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {s.model_pins.map((pin) => (
                  <Table.Tr key={pin.stage}>
                    <Table.Td>
                      <Text size="xs" tt="uppercase">
                        {pin.stage}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" ff="monospace" lineClamp={1}>
                        {pin.model.replace(/^[^/]+\//, "")}
                      </Text>
                    </Table.Td>
                    <Table.Td ta="end" ff="monospace" fz="xs" c="dimmed">
                      {pin.input_per_mtok !== null
                        ? `${pin.input_per_mtok.toFixed(2)} · ${pin.output_per_mtok?.toFixed(2)}`
                        : "unpriced"}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <Text size="xs" c="dimmed" mt="xs">
            Read from <Text span ff="monospace" fz="xs">MODEL_PRICES</Text> as loaded, not from
            documentation — a slug that drifts out of the price table is how a bill goes wrong
            quietly. Nothing here is editable.
          </Text>
        </Card>
      </SimpleGrid>
    </Stack>
  );
}
