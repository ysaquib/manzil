// The Overview's Visit column (VC-8, DESIGN §9.7, §13.2).
//
// This sits **beside** Fit and is never merged into it. The Rubric score is
// deterministic, reproducible and computed by a domain-blind engine; this is
// what a person felt standing in the room. Averaging them would destroy the one
// comparison that matters — a listing that scores 7 on paper and 2.2 in person
// is exactly the row you want to notice, and a blended 4.6 hides it.
//
// The star is the marker of that difference: it says human judgement, out of 5,
// not points out of a rubric.
import { Group, Text, Tooltip } from "@mantine/core";
import { IconStarFilled } from "@tabler/icons-react";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";

import type { VisitUnitGroupScore } from "./types";
import classes from "./VisitScoreCell.module.css";

dayjs.extend(relativeTime);

/** The colour roles a tour score reads in — warm and human, not the Fit bands. */
export function visitScoreTone(score: number): string {
  if (score >= 4) return "sage";
  if (score >= 3) return "olive";
  if (score >= 2) return "ochre";
  return "brick";
}

export function formatVisitScore(score: number): string {
  // One decimal always: "4" and "4.0" side by side in a column reads as noise.
  return score.toFixed(1);
}

/**
 * Why this row shows the number it does.
 *
 * Stated rather than implied, because two different reductions produced it —
 * the latest tour of each door, then the best of those doors.
 */
export function visitScoreTooltip(entry: VisitUnitGroupScore): string {
  const raters =
    entry.rater_count === 1 ? "1 member rated it" : `${entry.rater_count} members rated it`;
  const doors =
    entry.unit_count > 1
      ? `Best of ${entry.unit_count} units toured in this unit group. `
      : "";
  return `${doors}${raters}, ${dayjs(entry.best_visited_at).fromNow()}. A tour score, never part of Fit.`;
}

export function VisitScoreCell({ entry }: { entry: VisitUnitGroupScore | undefined }) {
  // No tour, or a tour of a door this Unit Group does not advertise: say
  // nothing. An em dash beats a zero, which would read as a bad review.
  if (!entry) {
    return (
      <Text size="xs" c="dimmed" aria-label="not visited">
        —
      </Text>
    );
  }

  return (
    <Tooltip label={visitScoreTooltip(entry)} multiline w={250}>
      <Group gap={3} wrap="nowrap" className={classes.cell}>
        <IconStarFilled size={11} aria-hidden className={classes.star} />
        <Text
          ff="var(--mantine-font-family-monospace)"
          fz="xs"
          fw={600}
          c={visitScoreTone(entry.score)}
        >
          {formatVisitScore(entry.score)}
        </Text>
        {entry.unit_count > 1 && (
          <Text fz="0.625rem" c="dimmed" className={classes.count}>
            ×{entry.unit_count}
          </Text>
        )}
      </Group>
    </Tooltip>
  );
}
