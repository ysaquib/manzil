// Decodes the status dots used across both Tasks tabs. Rendered once, above the
// tabs. Live states first, then terminal — split by a divider.
import { StatusDot, STATE_LABEL } from "./JobCardHeader";
import classes from "./StatusLegend.module.css";
import type { JobState } from "./api";

const LIVE: JobState[] = ["running", "waiting_user", "queued"];
const TERMINAL: JobState[] = ["done", "failed", "cancelled"];

function Item({ state }: { state: JobState }) {
  return (
    <span className={classes.item}>
      <StatusDot state={state} />
      {STATE_LABEL[state]}
    </span>
  );
}

export function StatusLegend() {
  return (
    <div className={classes.bar}>
      <span className={classes.label}>Status</span>
      {LIVE.map((state) => (
        <Item key={state} state={state} />
      ))}
      <span className={classes.divider} />
      {TERMINAL.map((state) => (
        <Item key={state} state={state} />
      ))}
    </div>
  );
}
