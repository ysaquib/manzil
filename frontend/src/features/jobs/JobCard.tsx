// One live job card (P1-13, §13.2): type, stage progress, state, cancel /
// retry, inline checkpoint prompt when the job waits on the user.
import { Badge, Button, Card, Divider, Group, Stack, Text } from "@mantine/core";

import { semantic } from "../../theme";
import { CheckpointPromptCard } from "./CheckpointPromptCard";
import type { Job, JobState } from "./api";

export const STATE_COLOR: Record<JobState, string> = {
  queued: "gray",
  running: semantic.active,
  waiting_user: semantic.waiting,
  done: "green",
  failed: semantic.danger,
  cancelled: "gray",
};

export function isCancellable(state: JobState): boolean {
  return state === "queued" || state === "running" || state === "waiting_user";
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
          <Badge color={STATE_COLOR[job.state]} variant="filled">
            {job.state.replace("_", " ")}
          </Badge>
        </Group>
        <Group gap="xs">
          <Text size="xs" c="dimmed">
            {job.current_stage ? `stage: ${job.current_stage}` : "not started"}
            {job.attempts > 1 ? ` · attempt ${job.attempts}` : ""}
          </Text>
        </Group>
        {job.error && (
          <Text size="xs" c={semantic.danger}>
            {job.error}
          </Text>
        )}
        {job.state === "waiting_user" && job.checkpoint && (
          <>
            <Divider />
            <CheckpointPromptCard prompt={job.checkpoint} onAnswer={onAnswer} answering={busy} />
          </>
        )}
        <Group gap="xs" justify="flex-end">
          {job.state === "failed" && (
            <Button size="xs" variant="default" onClick={onRetry} disabled={busy}>
              Retry
            </Button>
          )}
          {isCancellable(job.state) && (
            <Button size="xs" variant="subtle" color={semantic.danger} onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
          )}
        </Group>
      </Stack>
    </Card>
  );
}
