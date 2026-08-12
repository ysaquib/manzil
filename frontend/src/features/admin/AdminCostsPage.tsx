// Costs (AD-5). Built on `job_stage_costs` and `tier3_credit_usage`, using
// `@mantine/charts` so the panel reads as part of the app rather than a bolted-on
// dashboard.
//
// The two series are LLM and fetch, and they are kept apart everywhere: a
// blended number cannot answer "how much of this was the model?", which is the
// first question anyone asks of a cost page. Fetch is a thin sliver at current
// volumes and that is honest — the exact figures are in the table below the
// chart rather than exaggerated in the plot.
//
// Totals come from `total_cost_usd`, never from adding the two series up
// (DESIGN §20 v3.80). A Stage that re-runs replaces its `job_stage_costs` row,
// so the series describe the latest attempt at each Stage while the total is
// what the Jobs actually billed — the same number Tasks shows. Where the two
// disagree, the remainder is shown as its own row rather than rounded away.
import { BarChart } from "@mantine/charts";
import {
  Alert,
  Card,
  Group,
  Loader,
  Progress,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";
import { useState } from "react";

import { useCosts, type SpendBucket } from "./api";
import { formatCalendarDay, localCalendarDay } from "../../lib/calendarDays";

// Two categorical series, checked for colourblind separation against both
// themes rather than picked by eye. `accent` is the app's clay.
const SERIES = [
  { name: "llm", label: "LLM", color: "primary.6" },
  { name: "fetch", label: "Fetch (tier 3)", color: "accent.7" },
];

interface BarShapeProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  fill?: string;
  payload?: { isToday?: boolean };
}

function TodayTextureBar({ x = 0, y = 0, width = 0, height = 0, fill, payload }: BarShapeProps) {
  return <rect x={x} y={y} width={width} height={height} fill={payload?.isToday ? "url(#today-cost-pattern)" : fill} />;
}

function BucketTable({
  buckets,
  caption,
}: {
  buckets: SpendBucket[];
  caption?: string;
}) {
  if (buckets.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No spend recorded in this window.
      </Text>
    );
  }
  // Only shown when some bucket actually carries a remainder, so the ordinary
  // case keeps four columns.
  const anyUnattributed = buckets.some((bucket) => (bucket.unattributed_cost_usd ?? 0) > 0);
  return (
    <Table.ScrollContainer minWidth={anyUnattributed ? 500 : 420}>
      <Table verticalSpacing={4} highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th />
            <Table.Th ta="end">LLM</Table.Th>
            <Table.Th ta="end">Fetch</Table.Th>
            {anyUnattributed && (
              <Table.Th ta="end">
                <Tooltip
                  multiline
                  w={280}
                  label="Spend from Stages that ran more than once. The per-Stage breakdown keeps only the latest attempt, so this is the rest of the bill — it is included in the total."
                >
                  <Text component="span" size="xs" fw={700} style={{ borderBottom: "1px dotted" }}>
                    Re-runs
                  </Text>
                </Tooltip>
              </Table.Th>
            )}
            <Table.Th ta="end">Total</Table.Th>
            <Table.Th ta="end">Calls</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {buckets.map((bucket) => (
            <Table.Tr key={bucket.label}>
              <Table.Td>
                <Text size="sm">{bucket.label}</Text>
              </Table.Td>
              <Table.Td ta="end" ff="monospace" fz="xs">
                ${bucket.llm_cost_usd.toFixed(4)}
              </Table.Td>
              <Table.Td ta="end" ff="monospace" fz="xs">
                ${bucket.fetch_cost_usd.toFixed(4)}
              </Table.Td>
              {anyUnattributed && (
                <Table.Td ta="end" ff="monospace" fz="xs" c="dimmed">
                  {(bucket.unattributed_cost_usd ?? 0) > 0
                    ? `$${(bucket.unattributed_cost_usd ?? 0).toFixed(4)}`
                    : "—"}
                </Table.Td>
              )}
              <Table.Td ta="end" ff="monospace" fz="xs" fw={600}>
                ${bucket.total_cost_usd.toFixed(4)}
              </Table.Td>
              <Table.Td ta="end" ff="monospace" fz="xs" c="dimmed">
                {bucket.llm_calls}
                {bucket.fetch_calls > 0 && ` / ${bucket.fetch_calls}`}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
        {caption && <Table.Caption>{caption}</Table.Caption>}
      </Table>
    </Table.ScrollContainer>
  );
}

export function AdminCostsPage() {
  const [days, setDays] = useState("14");
  const costs = useCosts(Number(days));

  if (costs.isPending) return <Loader size="sm" />;
  if (costs.isError || !costs.data) {
    return (
      <Alert color="red" title="Could not load costs">
        {(costs.error as Error | undefined)?.message ?? "Unknown error"}
      </Alert>
    );
  }

  const c = costs.data;
  // The channels are the Stage breakdown; the total is what was billed. They
  // differ by re-run Stage attempts, which is stated rather than hidden.
  const llmTotal = c.by_stage.reduce((sum, b) => sum + b.llm_cost_usd, 0);
  const fetchTotal = c.by_stage.reduce((sum, b) => sum + b.fetch_cost_usd, 0);
  const rerunTotal = Math.max((c.total_cost_usd ?? 0) - llmTotal - fetchTotal, 0);
  const creditsPct =
    c.tier3_credits_allowance && c.tier3_credits_allowance > 0
      ? (100 * c.tier3_credits_used) / c.tier3_credits_allowance
      : null;

  const daily = c.daily.map((point) => ({
    day: formatCalendarDay(point.day),
    isToday: point.day === localCalendarDay(),
    llm: Number(point.llm_cost_usd.toFixed(4)),
    fetch: Number(point.fetch_cost_usd.toFixed(4)),
  }));

  const stageBars = c.by_stage.slice(0, 10).map((bucket) => ({
    stage: bucket.label,
    llm: Number(bucket.llm_cost_usd.toFixed(4)),
    fetch: Number(bucket.fetch_cost_usd.toFixed(4)),
  }));

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="center">
        <Title order={2}>Costs</Title>
        <SegmentedControl
          size="xs"
          value={days}
          onChange={setDays}
          data={[
            { value: "7", label: "7d" },
            { value: "14", label: "14d" },
            { value: "30", label: "30d" },
            { value: "90", label: "90d" },
          ]}
        />
      </Group>

      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
        <Card padding="sm" radius="md" withBorder>
          <Group gap={4}>
            <Text size="xs" c="dimmed" fw={700} tt="uppercase">
              Total
            </Text>
            <Tooltip
              multiline
              w={280}
              label="What the Jobs in this window billed — the same figure the Tasks tab shows. LLM and Fetch describe the latest attempt at each Stage, so they can add up to less."
            >
              <IconInfoCircle size={13} style={{ opacity: 0.6 }} />
            </Tooltip>
          </Group>
          <Text size="1.5rem" ff="monospace" fw={600}>
            ${(c.total_cost_usd ?? 0).toFixed(2)}
          </Text>
          {rerunTotal > 0 && (
            <Text size="xs" c="dimmed">
              incl. ${rerunTotal.toFixed(4)} from re-run Stages
            </Text>
          )}
        </Card>
        <Card padding="sm" radius="md" withBorder>
          <Text size="xs" c="dimmed" fw={700} tt="uppercase">
            LLM
          </Text>
          <Text size="1.5rem" ff="monospace" fw={600}>
            ${llmTotal.toFixed(2)}
          </Text>
        </Card>
        <Card padding="sm" radius="md" withBorder>
          <Text size="xs" c="dimmed" fw={700} tt="uppercase">
            Fetch
          </Text>
          <Text size="1.5rem" ff="monospace" fw={600}>
            ${fetchTotal.toFixed(4)}
          </Text>
        </Card>
        <Card padding="sm" radius="md" withBorder>
          <Text size="xs" c="dimmed" fw={700} tt="uppercase">
            Tier-3 credits
          </Text>
          <Text size="1.5rem" ff="monospace" fw={600}>
            {c.tier3_credits_used.toLocaleString()}
          </Text>
        </Card>
      </SimpleGrid>

      <Card padding="md" radius="md" withBorder>
        <Title order={5} mb="xs">
          Daily spend, split by what was bought
        </Title>
        {rerunTotal > 0 && (
          <Text size="xs" c="dimmed" mb={4}>
            The two series are the per-Stage breakdown, so they sit ${rerunTotal.toFixed(4)} below
            the window total — re-run Stages bought no single channel.
          </Text>
        )}
        {daily.length === 0 ? (
          <Text size="sm" c="dimmed">
            Nothing recorded in this window.
          </Text>
        ) : (
          <BarChart
            h={220}
            data={daily}
            dataKey="day"
            type="stacked"
            withLegend
            series={SERIES}
            valueFormatter={(value) => `$${value.toFixed(4)}`}
            barProps={{ shape: TodayTextureBar }}
          >
            <defs>
              <pattern id="today-cost-pattern" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="7" height="7" fill="var(--mantine-primary-color-filled)" />
                <line x1="0" y1="0" x2="0" y2="7" stroke="var(--mantine-color-body)" strokeWidth="2" opacity="0.55" />
              </pattern>
            </defs>
          </BarChart>
        )}
        <Group gap={6} mt="xs">
          <span
            aria-hidden
            data-testid="today-cost-texture"
            style={{ width: 14, height: 10, borderRadius: 2, background: "repeating-linear-gradient(45deg, var(--mantine-primary-color-filled), var(--mantine-primary-color-filled) 3px, var(--mantine-color-body) 3px, var(--mantine-color-body) 5px)" }}
          />
          <Text size="xs" c="dimmed">Today · in progress</Text>
        </Group>
      </Card>

      <Card padding="md" radius="md" withBorder>
        <Title order={5} mb="xs">
          Bright Data credits, this month
        </Title>
        {creditsPct !== null ? (
          <>
            <Progress
              value={Math.min(creditsPct, 100)}
              color={creditsPct > 85 ? "red" : creditsPct > 60 ? "yellow" : "accent"}
              size="lg"
              radius="sm"
            />
            <Group justify="space-between" mt={6}>
              <Text size="xs" c="dimmed" ff="monospace">
                {c.tier3_credits_used.toLocaleString()} /{" "}
                {c.tier3_credits_allowance?.toLocaleString()}
              </Text>
              <Text size="xs" c="dimmed">
                One tier-3 fetch is one credit. Resets on the 1st.
              </Text>
            </Group>
          </>
        ) : (
          <Text size="sm" c="dimmed">
            No allowance recorded for the configured provider.
          </Text>
        )}
      </Card>

      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
        <Card padding="md" radius="md" withBorder>
          <Title order={5} mb="xs">
            By stage
          </Title>
          {stageBars.length > 0 && (
            <BarChart
              h={200}
              data={stageBars}
              dataKey="stage"
              type="stacked"
              orientation="vertical"
              series={SERIES}
              valueFormatter={(value) => `$${value.toFixed(4)}`}
            />
          )}
          <BucketTable buckets={c.by_stage} />
        </Card>

        <Card padding="md" radius="md" withBorder>
          <Title order={5} mb="xs">
            By Hunt
          </Title>
          <BucketTable buckets={c.by_hunt} />
        </Card>
      </SimpleGrid>

      <Card padding="md" radius="md" withBorder>
        <Group gap={6} mb="xs">
          <Title order={5}>By model</Title>
          {/* Said out loud rather than buried: this is not history. */}
          <Tooltip
            multiline
            w={280}
            label="Stage spend grouped under each stage's current pin. A stage that was re-pinned files its older spend under the new model — per-call attribution lives in Langfuse."
          >
            <IconInfoCircle size={15} style={{ opacity: 0.6 }} />
          </Tooltip>
        </Group>
        <BucketTable
          buckets={c.by_model}
          caption={
            c.grouped_by_current_pin
              ? "Grouped by each stage's current pin, not by the model that actually ran."
              : undefined
          }
        />
      </Card>
    </Stack>
  );
}
