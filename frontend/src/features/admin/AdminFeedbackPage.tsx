// Feedback inbox (AD-2) — the first admin surface with real value, and the
// cheapest, because `feedback` was designed for this reader in P3-16 and has
// never had a client SELECT policy.
//
// A report is only actionable if you can get back to where it was written, so
// the route (drawer params and all), the build and the browser are shown on the
// card rather than hidden behind a detail view. That is the whole feature.
import {
  Alert,
  Badge,
  Card,
  Chip,
  Group,
  Loader,
  Menu,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { IconChevronDown, IconInbox } from "@tabler/icons-react";
import { useState } from "react";

import { TablePagination, usePagedRows } from "../../components/TablePagination";
import {
  FEEDBACK_CATEGORY_LABELS,
  TRIAGE_STATES,
  useAdminFeedback,
  useFeedbackCounts,
  useSetTriage,
  type FeedbackReport,
  type TriageState,
} from "./api";

const CATEGORY_COLOR: Record<string, string> = {
  bug: "gray",
  wrong_data: "red",
  confusing: "yellow",
  feature: "accent",
  other: "gray",
};

const TRIAGE_COLOR: Record<TriageState, string> = {
  new: "primary",
  seen: "gray",
  actioned: "green",
  wont_fix: "gray",
};

function ReportCard({ report }: { report: FeedbackReport }) {
  const setTriage = useSetTriage();

  return (
    <Card
      padding="sm"
      radius="md"
      withBorder
      style={
        report.triage === "new"
          ? { borderInlineStartWidth: 3, borderInlineStartColor: "var(--mantine-primary-color-filled)" }
          : undefined
      }
    >
      <Group gap="xs" wrap="wrap" mb={6}>
        <Badge size="sm" variant="light" color={CATEGORY_COLOR[report.category] ?? "gray"}>
          {FEEDBACK_CATEGORY_LABELS[report.category] ?? report.category}
        </Badge>
        <Text size="sm" fw={600}>
          {report.reporter_name ?? report.reporter_email ?? "Unknown reporter"}
        </Text>
        <Text size="xs" c="dimmed">
          {report.hunt_name ?? "no Hunt"} · {new Date(report.created_at).toLocaleString()}
        </Text>

        <Menu position="bottom-end" withinPortal>
          <Menu.Target>
            <UnstyledButton style={{ marginInlineStart: "auto" }}>
              <Badge
                size="sm"
                variant="light"
                color={TRIAGE_COLOR[report.triage]}
                rightSection={<IconChevronDown size={12} />}
                style={{ cursor: "pointer" }}
              >
                {TRIAGE_STATES.find((s) => s.value === report.triage)?.label ?? report.triage}
              </Badge>
            </UnstyledButton>
          </Menu.Target>
          <Menu.Dropdown>
            {TRIAGE_STATES.map((state) => (
              <Menu.Item
                key={state.value}
                disabled={state.value === report.triage || setTriage.isPending}
                onClick={() => setTriage.mutate({ id: report.id, triage: state.value })}
              >
                {state.label}
              </Menu.Item>
            ))}
          </Menu.Dropdown>
        </Menu>
      </Group>

      <Text size="sm" mb={6} style={{ whiteSpace: "pre-wrap" }}>
        {report.body}
      </Text>

      <Text size="xs" c="dimmed" ff="monospace" style={{ wordBreak: "break-all" }}>
        {[report.route, report.app_version, report.user_agent].filter(Boolean).join(" · ") ||
          "no context recorded"}
      </Text>
    </Card>
  );
}

export function AdminFeedbackPage() {
  const [triage, setTriage] = useState<TriageState | null>("new");
  const reports = useAdminFeedback(triage);
  const counts = useFeedbackCounts();
  const paged = usePagedRows(reports.data ?? [], "admin-feedback");

  return (
    <Stack gap="md">
      <Title order={2}>Feedback</Title>

      <Chip.Group
        multiple={false}
        value={triage ?? "all"}
        onChange={(value) => setTriage(value === "all" ? null : (value as TriageState))}
      >
        <Group gap="xs">
          {TRIAGE_STATES.map((state) => (
            <Chip key={state.value} value={state.value} variant="light" size="sm">
              {state.label}
              {counts.data?.[state.value] ? ` ${counts.data[state.value]}` : ""}
            </Chip>
          ))}
          <Chip value="all" variant="light" size="sm">
            All
          </Chip>
        </Group>
      </Chip.Group>

      {reports.isPending && <Loader size="sm" />}

      {reports.isError && (
        <Alert color="red" title="Could not load the inbox">
          {(reports.error as Error | undefined)?.message ?? "Unknown error"}
        </Alert>
      )}

      {reports.data?.length === 0 && (
        <Card padding="lg" radius="md" withBorder>
          <Group gap="sm">
            <IconInbox size={20} stroke={1.5} />
            <Text c="dimmed" size="sm">
              {triage === "new"
                ? "Nothing new. Everything submitted has been looked at."
                : "No reports in this state."}
            </Text>
          </Group>
        </Card>
      )}

      <Stack gap="xs">
        {paged.items.map((report) => (
          <ReportCard key={report.id} report={report} />
        ))}
      </Stack>
      <TablePagination state={paged} noun="reports" />
    </Stack>
  );
}
