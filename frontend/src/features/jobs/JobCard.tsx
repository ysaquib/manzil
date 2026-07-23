// One live job card (P1-13, §13.2): shared header, five-phase pipeline track,
// cancel / retry, inline checkpoint prompt when the job waits on the user.
// Running jobs get a loader + counting-up timer so progress is visibly alive.
import { Button, Card, Group, Loader, Paper, Stack, Text } from "@mantine/core";

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
  return (
    <Card>
      <Stack gap="md">
        <JobCardHeader state={job.state} type={job.type} title={listingName ?? "—"} />
        <PipelineTrack
          model={phasesForJob(job)}
          attempts={job.attempts}
          trailing={
            job.state === "running" && (
              <Group gap={8} wrap="nowrap">
                <Loader size="xs" />
                {(job.started_at ?? job.created_at) && (
                  <ElapsedTimer since={(job.started_at ?? job.created_at)!} />
                )}
              </Group>
            )
          }
        />
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
