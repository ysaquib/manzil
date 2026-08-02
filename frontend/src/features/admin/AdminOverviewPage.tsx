// Admin Overview (AD-2): the counters, and the short list of things that are
// actually wrong. Charts arrive with AD-5 (`@mantine/charts`), so this page
// deliberately shows numbers and states rather than a chart-shaped placeholder.
import { Alert, Card, Group, Loader, Progress, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";
import { Link } from "react-router-dom";

import { useAdminSummary } from "./api";

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "warning" | "critical";
}) {
  const color =
    tone === "critical" ? "red" : tone === "warning" ? "yellow" : undefined;
  return (
    <Card padding="sm" radius="md" withBorder>
      <Text size="xs" c="dimmed" fw={700} tt="uppercase" style={{ letterSpacing: "0.1em" }}>
        {label}
      </Text>
      <Group gap={6} align="baseline">
        <Text size="1.6rem" fw={600} ff="monospace" c={color} lh={1.2}>
          {value}
        </Text>
        {hint && (
          <Text size="xs" c="dimmed">
            {hint}
          </Text>
        )}
      </Group>
    </Card>
  );
}

export function AdminOverviewPage() {
  const summary = useAdminSummary();

  if (summary.isPending) {
    return <Loader size="sm" />;
  }
  if (summary.isError || !summary.data) {
    return (
      <Alert color="red" title="Could not load the summary">
        {(summary.error as Error | undefined)?.message ?? "Unknown error"}
      </Alert>
    );
  }

  const s = summary.data;
  const creditsPct =
    s.tier3_credits_allowance && s.tier3_credits_allowance > 0
      ? (100 * s.tier3_credits_used) / s.tier3_credits_allowance
      : null;

  return (
    <Stack gap="lg">
      <Title order={2}>Overview</Title>

      <SimpleGrid cols={{ base: 2, sm: 3, lg: 6 }} spacing="sm">
        <Stat label="People" value={s.users.toLocaleString()} />
        <Stat label="Hunts" value={s.hunts.toLocaleString()} />
        <Stat label="Listings" value={s.listings.toLocaleString()} />
        <Stat label="Spend 30d" value={`$${s.spend_usd_30d.toFixed(2)}`} />
        <Stat
          label="Jobs failed"
          value={s.jobs_failed.toLocaleString()}
          hint={`/ ${s.jobs_total.toLocaleString()}`}
          tone={s.jobs_failed > 0 ? "critical" : undefined}
        />
        <Stat
          label="Feedback"
          value={s.feedback_new.toLocaleString()}
          hint="new"
          tone={s.feedback_new > 0 ? "warning" : undefined}
        />
      </SimpleGrid>

      {/* The counter that matters more than the dollars: the free plan is a
          fixed monthly allowance, and exhausting it drops tier 3 off the fetch
          ladder mid-run as what looks like an unexplained failure. */}
      <Card padding="md" radius="md" withBorder>
        <Group justify="space-between" align="baseline" mb="xs">
          <Text fw={600}>Tier-3 credits, this month</Text>
          <Text size="sm" c="dimmed" ff="monospace">
            {s.tier3_credits_used.toLocaleString()}
            {s.tier3_credits_allowance
              ? ` / ${s.tier3_credits_allowance.toLocaleString()}`
              : " (no recorded allowance)"}
          </Text>
        </Group>
        {creditsPct !== null && (
          <Progress
            value={Math.min(creditsPct, 100)}
            color={creditsPct > 85 ? "red" : creditsPct > 60 ? "yellow" : "accent"}
            size="lg"
            radius="sm"
          />
        )}
        <Text size="xs" c="dimmed" mt="xs">
          One tier-3 fetch is one credit. The allowance resets on the 1st.
        </Text>
      </Card>

      {(s.jobs_failed > 0 || s.feedback_new > 0) && (
        <Stack gap="xs">
          <Title order={4}>Needs attention</Title>
          {s.jobs_failed > 0 && (
            <Alert
              color="red"
              icon={<IconAlertTriangle size={18} />}
              title={`${s.jobs_failed} failed ${s.jobs_failed === 1 ? "Job" : "Jobs"}`}
            >
              Cross-Hunt queue control arrives with AD-5. Until then, the Hunt&apos;s own Tasks tab
              can retry them.
            </Alert>
          )}
          {s.feedback_new > 0 && (
            <Alert color="yellow" icon={<IconAlertTriangle size={18} />} title="Unread feedback">
              <Link to="/admin/feedback">
                {s.feedback_new} {s.feedback_new === 1 ? "report" : "reports"} waiting in the inbox
              </Link>
            </Alert>
          )}
        </Stack>
      )}
    </Stack>
  );
}
