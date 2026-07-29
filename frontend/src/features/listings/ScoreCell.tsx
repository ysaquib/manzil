// Score cell (Phase 1 plan §5.3, DESIGN §9.4/§13.2): color scale by total, a
// stacked-layers indicator when a Unit Group has >1 scored plan, and a marker
// when a manual pin or ephemeral filter selection picked the Display Floor
// Plan. Stale / auto-resolved / single-source badge slots are Phase 3 — inert
// components wired for layout.
import { Group, Text, Box, Tooltip } from "@mantine/core";

import { scoreColor, scoreBand, formatScore } from "./scoreBands";
export { scoreColor, formatScore } from "./scoreBands"; // keep existing import sites (FloorPlanPins) working
import { IconFilter, IconPinnedFilled } from "@tabler/icons-react";

export interface ScoreCellProps {
  total: number;
  max?: number;
  pinned?: boolean;
  filterSelected?: boolean;
  planName?: string;
  /** scored plans in the Unit Group; >1 shows the ×N affordance (absorbs the
   * old Info column — future stale/single-source badges belong on Property) */
  planCount?: number;
}

export function ScoreCell({
  total,
  pinned = false,
  filterSelected = false,
  planName,
  planCount = 1,
}: ScoreCellProps) {
  const selectionLabel = pinned
    ? "pinned shown"
    : filterSelected
      ? "best filter match shown"
      : "best shown";
  return (
    <Group wrap="nowrap" gap={6}>
      <Group gap={0} c={scoreColor(total)}>
        <Text ff={"monospace"} fz="xs" fw={600}>
          {formatScore(total)}
        </Text>
        {scoreBand(total) === 0 && (
          <Text span aria-hidden ml={2} fz="sm">✦</Text>
        )}
      </Group>
      {pinned && (
        <Tooltip label={`Pinned${planName ? `: ${planName}` : ""}`}>
          <Box c={"dimmed"} w={12} display="flex">
            <IconPinnedFilled size={12} stroke={2}/>
          </Box>
        </Tooltip>
      )}
      {!pinned && filterSelected && (
        <Tooltip label={`Filter-selected Floor Plan${planName ? `: ${planName}` : ""}`}>
          <Box
            c="dimmed"
            w={12}
            display="flex"
            aria-label="filter-selected Floor Plan"
          >
            <IconFilter size={12} stroke={2} />
          </Box>
        </Tooltip>
      )}
      {planCount > 1 && (
        <Tooltip label={`${planCount} scored plans — ${selectionLabel}`}>
          <Text ff="monospace" fz={10} c="dimmed" aria-label="multiple scored plans">
            ×{planCount}
          </Text>
        </Tooltip>
      )}
    </Group>
  );
}
