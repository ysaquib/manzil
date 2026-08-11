// Shared header for both the Active and History job cards: a leading colored
// status dot (see StatusLegend), the listing/title, and a quiet uppercase job
// type. Replaces the previous twin badges (P1-13 refresh).
import { Text } from "@mantine/core";

import classes from "./JobCardHeader.module.css";
import type { JobState, JobType } from "./api";

export const STATE_LABEL: Record<JobState, string> = {
  queued: "Queued",
  running: "Running",
  waiting_user: "Waiting on you",
  done: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
  deleted: "Deleted",
};

export function StatusDot({ state }: { state: JobState }) {
  return <span className={classes.dot} data-state={state} role="img" aria-label={STATE_LABEL[state]} title={STATE_LABEL[state]} />;
}

export function JobCardHeader({
  state,
  type,
  title,
}: {
  state: JobState;
  type: JobType;
  title: string;
}) {
  return (
    <div className={classes.header}>
      <div className={classes.id}>
        <StatusDot state={state} />
        <Text size="sm" fw={600} lineClamp={1} className={classes.title}>
          {title}
        </Text>
      </div>
      <span className={classes.type}>{type}</span>
    </div>
  );
}
