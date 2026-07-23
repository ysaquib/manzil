// One live job card (P1-13, §13.2): shared header, five-phase pipeline track,
// inline checkpoint prompt when the job waits on the user. Running jobs get a
// loader + counting-up timer so progress is visibly alive; cancellable jobs get
// a small round stop control beside the timer.
import { ActionIcon, Button, Card, Group, Loader, Paper, Stack, Text, Tooltip } from "@mantine/core";
import { IconPlayerStopFilled } from "@tabler/icons-react";

import { CheckpointPromptCard } from "./CheckpointPromptCard";
import { ElapsedTimer } from "./ElapsedTimer";
import { JobCardHeader } from "./JobCardHeader";
import { PipelineTrack } from "./PipelineTrack";
import { phasesForJob } from "./pipelinePhases";
import type { Job, JobState } from "./api";

// Retained for the histogram/legend colors and existing tests.
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
  const since = job.started_at ?? job.created_at;
  // Right-hand controls in the caption row: live loader + timer (running only),
  // and a small round stop button whenever the job can be cancelled.
  const trailing = isCancellable(job.state) ? (
    <Group gap={8} wrap="nowrap">
      {job.state === "running" && <Loader size="xs" />}
      {job.state === "running" && since && <ElapsedTimer since={since} />}
      <Tooltip label="Cancel" withArrow>
        <ActionIcon
          variant="light"
          color="red"
          radius="xl"
          size="sm"
          onClick={onCancel}
          disabled={busy}
          aria-label="Cancel"
        >
          <IconPlayerStopFilled size={13} />
        </ActionIcon>
      </Tooltip>
    </Group>
  ) : undefined;

  return (
    <Card>
      <Stack gap="md">
        <JobCardHeader state={job.state} type={job.type} title={listingName ?? "—"} />
        <PipelineTrack model={phasesForJob(job)} attempts={job.attempts} trailing={trailing} />
        {job.error && (
          <Text size="xs" c={"red"}>
            {job.error}
          </Text>
        )}
        {job.state === "waiting_user" && job.checkpoint && (
          <Paper withBorder p="sm" style={{ backgroundColor: "var(--mantine-color-yellow-light)" }}>
            <CheckpointPromptCard prompt={job.checkpoint} onAnswer={onAnswer} answering={busy} />
          </Paper>
        )}
        {job.state === "failed" && (
          <Group gap="xs" justify="flex-end">
            <Button size="xs" variant="default" onClick={onRetry} disabled={busy}>
              Retry
            </Button>
          </Group>
        )}
      </Stack>
    </Card>
  );
}
