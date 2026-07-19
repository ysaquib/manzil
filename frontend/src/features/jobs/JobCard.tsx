// One live job card (P1-13, §13.2): type, stage progress, state, cancel /
// retry, inline checkpoint prompt when the job waits on the user. Running
// jobs get a loader + counting-up timer so progress is visibly alive.
import { Badge, Button, Card, Group, Loader, Paper, Stack, Text } from "@mantine/core";

import { CheckpointPromptCard } from "./CheckpointPromptCard";
import { ElapsedTimer } from "./ElapsedTimer";
import type { Job, JobState } from "./api";

export const STATE_COLOR: Record<JobState, string> = {
  queued: "gray",
  running: "grape",
  waiting_user: "yellow",
  done: "green",
  failed: "red",
  cancelled: "gray",
};

export function isCancellable(state: JobState): boolean {
  return state === "queued" || state === "running" || state === "waiting_user";
}

function stateBadgeVariant(state: JobState): "light" | "filled" {
  return state === "failed" ? "filled" : "light";
}

export function JobCard({
  job,
  listingName,
  onCancel,
  onRetry,
  onAnswer,
  busy,
}: {
  job: Job;
  listingName: string | null;
  onCancel: () => void;
  onRetry: () => void;
  onAnswer: (choice: string, text?: string) => void;
  busy: boolean;
}) {
  return (
    <Card>
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap">
            <Badge variant="light" color="gray">
              {job.type}
            </Badge>
            <Text size="sm" fw={600} lineClamp={1}>
              {listingName ?? "—"}
            </Text>
          </Group>
          <Badge color={STATE_COLOR[job.state]} variant={stateBadgeVariant(job.state)}>
            {job.state.replace("_", " ")}
          </Badge>
        </Group>
        <Group gap="xs" justify="space-between" wrap="nowrap">
          <Text size="xs" c="dimmed">
            {job.current_stage ? `stage: ${job.current_stage}` : "not started"}
            {job.attempts > 1 ? ` · attempt ${job.attempts}` : ""}
          </Text>
          {job.state === "running" && (
            <Group gap={8} wrap="nowrap">
              <Loader size="xs" />
              {(job.started_at ?? job.created_at) && (
                <ElapsedTimer since={(job.started_at ?? job.created_at)!} />
              )}
            </Group>
          )}
        </Group>
        {job.error && (
          <Text size="xs" c={"red"}>
            {job.error}
          </Text>
        )}
        {job.state === "waiting_user" && job.checkpoint && (
          <Paper withBorder p="sm" mt="sm">
            <CheckpointPromptCard prompt={job.checkpoint} onAnswer={onAnswer} answering={busy} />
          </Paper>
        )}
        <Group gap="xs" justify="flex-end">
          {job.state === "failed" && (
            <Button size="xs" variant="default" onClick={onRetry} disabled={busy}>
              Retry
            </Button>
          )}
          {isCancellable(job.state) && (
            <Button size="xs" variant="subtle" color={"red"} onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
          )}
        </Group>
      </Stack>
    </Card>
  );
}
