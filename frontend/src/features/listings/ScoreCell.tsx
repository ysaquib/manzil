// Score cell (Phase 1 plan §5.3, DESIGN §9.4/§13.2): color scale by total, a
// stacked-layers indicator when a Unit Group has >1 scored plan, a pinned tag
// when a per-group pin picked the displayed plan. Stale / auto-resolved /
// single-source badge slots are Phase 3 — inert components wired for layout.
import { Group, Text, Box, Tooltip } from "@mantine/core";

import { SCORE_BASE, SCORE_MAX } from "../../lib/contracts";
import { IconPinnedFilled } from "@tabler/icons-react";

// Pure, unit-tested: maps a total to a Mantine color name. Bands are anchored
// on the §9.3 engine domain — clamp [0, 15], base 10 — so green means "at or
// above base" (no net penalties), tuned here per P1-10.
export function scoreColor(
  total: number,
  base = SCORE_BASE,
  max = SCORE_MAX,
): string {
  const pct = max > 0 ? total / base : 0;
  // console.log(pct);
  if (pct >= 5 / 5) return "scoreHighest";
  if (pct >= 4 / 5) return "scoreHigh";
  if (pct >= 3 / 5) return "scoreGood";
  if (pct >= 2 / 5) return "scoreMid";
  if (pct >= 1 / 5) return "scoreLow";
  if (pct >= 0 / 5) return "scorePoor";
  return "scorePoorest";
}

// Half-point deltas are common (§8.2 defaults); 9.5 must not read as 10.
export function formatScore(total: number): string {
  return Number.isInteger(total) ? String(total) : total.toFixed(1);
}

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
      <Text ff={"monospace"} fz="xs" fw={600} c={scoreColor(total)}>
        {formatScore(total)}
      </Text>
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
