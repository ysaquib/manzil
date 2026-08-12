import { BarChart } from "@mantine/charts";
import { Alert, Card, Group, Loader, SegmentedControl, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";

import { formatCalendarDay } from "../../lib/calendarDays";
import { useHuntStatistics, type StatisticsDays } from "./api";

const COST_SERIES = [
  { name: "visible", label: "Visible Jobs", color: "primary.6" },
  { name: "deleted", label: "Deleted Jobs", color: "gray.6" },
];
const JOB_SERIES = [
  { name: "completed", label: "Completed", color: "green.6" },
  { name: "failed", label: "Failed", color: "red.6" },
];
const CALL_SERIES = [
  { name: "llm", label: "Recorded LLM", color: "primary.6" },
  { name: "fetch", label: "Tier-3 fetch", color: "accent.7" },
];

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return <Card padding="sm" withBorder><Text size="xs" c="dimmed" fw={700} tt="uppercase">{label}</Text><Text component="div" size="xl" fw={600} ff="monospace">{value}</Text></Card>;
}

function DeletedPattern() {
  return (
    <defs>
      <pattern id="deleted-job-pattern" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="6" height="6" fill="var(--mantine-color-gray-5)" />
        <line x1="0" y1="0" x2="0" y2="6" stroke="var(--mantine-color-gray-8)" strokeWidth="2" />
      </pattern>
    </defs>
  );
}

export function HuntStatisticsPage() {
  const { huntId = "" } = useParams();
  const [days, setDays] = useState<StatisticsDays>(30);
  const report = useHuntStatistics(huntId, days);

  if (report.isPending) return <Loader size="sm" />;
  if (report.isError || !report.data) return <Alert color="red">Could not load Hunt statistics.</Alert>;

  const { summary, daily } = report.data;
  const finishedJobs = summary.jobs_completed + summary.jobs_failed;
  const completionRate = finishedJobs === 0 ? null : summary.jobs_completed / finishedJobs;
  const billedCostPerCompletedJob = summary.jobs_completed === 0 ? null : summary.billed_cost_usd / summary.jobs_completed;
  const chart = daily.map((point) => ({
    day: formatCalendarDay(point.day),
    visible: Math.max(point.billed_cost_usd - point.deleted_cost_usd, 0),
    deleted: point.deleted_cost_usd,
    listings: point.listing_submissions,
    completed: point.jobs_completed,
    failed: point.jobs_failed,
    llm: point.llm_calls,
    fetch: point.fetch_calls,
  }));

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="center">
        <Title order={2}>Statistics</Title>
        <SegmentedControl
          size="xs"
          value={String(days)}
          onChange={(value) => setDays(Number(value) as StatisticsDays)}
          data={[7, 14, 30, 90, 365].map((value) => ({ value: String(value), label: value === 365 ? "1y" : `${value}d` }))}
        />
      </Group>

      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Stat label="Billed spend" value={`$${summary.billed_cost_usd.toFixed(2)}`} />
        <Stat label="Deleted Job spend" value={`$${summary.deleted_cost_usd.toFixed(2)}`} />
        <Stat label="Listings submitted" value={summary.listing_submissions.toLocaleString()} />
        <Stat
          label="Completion rate"
          value={
            <Text component="span" c={completionRate === null ? "dimmed" : completionRate >= 0.9 ? "green.7" : completionRate >= 0.7 ? "yellow.8" : "red.7"}>
              {completionRate === null ? "—" : `${Math.round(completionRate * 100)}%`}
            </Text>
          }
        />
        <Stat
          label="Job outcomes"
          value={
            <Group gap={8} align="baseline" wrap="nowrap">
              <Text component="span" size="xl" fw={600} ff="monospace" c="green.7">
                {summary.jobs_completed}
              </Text>
              <Text component="span" c="dimmed">/</Text>
              <Text component="span" size="xl" fw={600} ff="monospace" c="red.7">
                {summary.jobs_failed}
              </Text>
            </Group>
          }
        />
        <Stat label="Billed / completed Job" value={billedCostPerCompletedJob === null ? "—" : `$${billedCostPerCompletedJob.toFixed(2)}`} />
        <Stat label="LLM calls" value={summary.llm_calls.toLocaleString()} />
        <Stat label="Tier-3 fetches" value={summary.fetch_calls.toLocaleString()} />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Card padding="md" withBorder>
          <Title order={4} mb="xs">Billed cost</Title>
          <BarChart h={240} data={chart} dataKey="day" type="stacked" series={COST_SERIES} withLegend valueFormatter={(value) => `$${value.toFixed(4)}`} barProps={(series) => series.name === "deleted" ? { fill: "url(#deleted-job-pattern)" } : {}}><DeletedPattern /></BarChart>
        </Card>
        <Card padding="md" withBorder>
          <Title order={4} mb="xs">Listings submitted</Title>
          <BarChart h={240} data={chart} dataKey="day" series={[{ name: "listings", label: "Listings", color: "primary.6" }]} />
        </Card>
        <Card padding="md" withBorder>
          <Title order={4} mb="xs">Jobs by outcome</Title>
          <BarChart h={240} data={chart} dataKey="day" type="stacked" series={JOB_SERIES} withLegend />
        </Card>
        <Card padding="md" withBorder>
          <Title order={4} mb="xs">Recorded calls</Title>
          <BarChart h={240} data={chart} dataKey="day" type="stacked" series={CALL_SERIES} withLegend />
        </Card>
      </SimpleGrid>
      <Text size="xs" c="dimmed">Calendar days are bucketed in {report.data.timezone}. Deleted Jobs remain in aggregate usage and spend, but no individual deleted Job is exposed.</Text>
    </Stack>
  );
}
