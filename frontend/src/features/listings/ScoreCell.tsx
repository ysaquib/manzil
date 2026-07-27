// Score cell (Phase 1 plan §5.3, DESIGN §9.4/§13.2): color scale by total, a
// stacked-layers indicator when a Unit Group has >1 scored plan, a pinned tag
// when a per-group pin picked the displayed plan. Stale / auto-resolved /
// single-source badge slots are Phase 3 — inert components wired for layout.
import { Group, Text, Box, Tooltip } from "@mantine/core";

import { scoreColor, scoreBand, formatScore } from "./scoreBands";
export { scoreColor, formatScore } from "./scoreBands"; // keep existing import sites (FloorPlanPins) working
import { IconPinnedFilled } from "@tabler/icons-react";

export interface ScoreCellProps {
  total: number;
  max?: number;
  pinned?: boolean;
  /** scored plans in the Unit Group; >1 shows the ×N affordance (absorbs the
   * old Info column — future stale/single-source badges belong on Property) */
  planCount?: number;
}

export function ScoreCell({ total, pinned = false, planCount = 1 }: ScoreCellProps) {
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
        <Tooltip label="Pinned">
          <Box c={"dimmed"} w={12} display="flex">
            <IconPinnedFilled size={12} stroke={2}/>
          </Box>
        </Tooltip>
      )}
      {planCount > 1 && (
        <Tooltip label={`${planCount} scored plans — best shown`}>
          <Text ff="monospace" fz={10} c="dimmed" aria-label="multiple scored plans">
            ×{planCount}
          </Text>
        </Tooltip>
      )}
    </Group>
  );
}
