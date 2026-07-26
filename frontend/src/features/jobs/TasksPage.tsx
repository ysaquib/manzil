// Tasks page. The tab is URL-driven (`?tab=active|history`) so an Overview row
// that failed can link straight to the run that failed rather than dropping you
// on Active to hunt for it (UI Decision Log 2026-07-26).
import { Stack, Tabs } from "@mantine/core";
import { useSearchParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { StatusLegend } from "./StatusLegend";
import { TasksActivePage } from "./TasksActivePage";
import { TasksHistoryTab } from "./TasksHistoryTab";

const TABS = ["active", "history"] as const;
type TaskTab = (typeof TABS)[number];

export function TasksPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("tab");
  const tab: TaskTab = TABS.includes(requested as TaskTab) ? (requested as TaskTab) : "active";

  return (
    <Stack gap="lg">
      <PageHeader title="Tasks" description="Live progress and retained run history" />
      <StatusLegend />
      <Tabs
        value={tab}
        onChange={(next) => {
          // Replace, not push: flipping tabs shouldn't stack history entries
          // between you and the page you arrived from.
          if (next) setSearchParams({ tab: next }, { replace: true });
        }}
      >
        <Tabs.List>
          <Tabs.Tab value="active">Active</Tabs.Tab>
          <Tabs.Tab value="history">History</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="active" pt="md"><TasksActivePage /></Tabs.Panel>
        <Tabs.Panel value="history" pt="md"><TasksHistoryTab /></Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
