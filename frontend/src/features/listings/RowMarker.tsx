// The pinned state marker beside a property name (UI Decision Log 2026-07-26).
//
// One slot, priority-ordered: pipeline state outranks curation state, because a
// row that is still fetching has nothing to curate yet. That ordering is what
// stops a row from sprouting two competing markers.
//
// It is not redundant with the Status chip: the chip carries the word and the
// menu but lives in the Curation group, which scrolls out of view; the marker
// rides the pinned column and answers "where does this one stand" at every
// scroll position.
import { Box, Tooltip } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";

import { interestLabel, interestTone } from "./interestStatus";
import type { PipelineState } from "./rowState";
import type { InterestStatus } from "./types";
import classes from "./OverviewTable.module.css";

export function RowMarker({
  pipeline,
  status,
}: {
  pipeline: PipelineState | null;
  status: InterestStatus | null;
}) {
  if (pipeline === "working") {
    return (
      <Tooltip label="Working on it" openDelay={200}>
        <Box className={classes.marker} role="img" aria-label="Working on it">
          <Box className={classes.spinner} />
        </Box>
      </Tooltip>
    );
  }
  if (pipeline === "failed") {
    return (
      <Tooltip label="Last run failed" openDelay={200}>
        <Box className={classes.marker} c="red" role="img" aria-label="Last run failed">
          <IconAlertTriangle size={14} stroke={1.8} />
        </Box>
      </Tooltip>
    );
  }
  const label = interestLabel(status);
  return (
    <Tooltip label={label} openDelay={200}>
      <Box className={classes.marker} role="img" aria-label={label}>
        <Box
          className={status === null ? `${classes.dot} ${classes.dotEmpty}` : classes.dot}
          bg={status === null ? undefined : `${interestTone(status)}.6`}
        />
      </Box>
    </Tooltip>
  );
}
