// Visit state marker (DESIGN §9.7). Dot plus label: colour reinforces the state
// but the word always carries it, per UI_DESIGN §4.
import { Badge, Box } from "@mantine/core";

import type { VisitState } from "./types";
import { VISIT_STATE_COLOR, VISIT_STATE_LABEL } from "./visitState";
import classes from "./VisitStatePill.module.css";

export function VisitStatePill({ state }: { state: VisitState }) {
  const color = VISIT_STATE_COLOR[state];
  return (
    <Badge
      color={color}
      variant={state === "cancelled" ? "outline" : "light"}
      radius="sm"
      leftSection={
        <Box
          aria-hidden
          className={classes.dot}
          data-live={state === "in_progress" ? "true" : undefined}
          style={{ "--visit-dot-color": `var(--mantine-color-${color}-6)` } as React.CSSProperties}
        />
      }
    >
      {VISIT_STATE_LABEL[state]}
    </Badge>
  );
}
