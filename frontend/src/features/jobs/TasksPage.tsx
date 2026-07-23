import { Stack, Tabs } from "@mantine/core";

import { PageHeader } from "../../components/PageHeader";
import { StatusLegend } from "./StatusLegend";
import { TasksActivePage } from "./TasksActivePage";
import { TasksHistoryTab } from "./TasksHistoryTab";

export function TasksPage() {
  return (
    <Stack gap="lg">
      <PageHeader title="Tasks" description="Live progress and retained run history" />
      <StatusLegend />
      <Tabs defaultValue="active">
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
