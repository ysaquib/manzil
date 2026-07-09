// Score cell (Phase 1 plan §5.3, DESIGN §9.4/§13.2): color scale by total, a
// stacked-layers indicator when a Unit Group has >1 scored plan, a pinned tag
// when a per-group pin picked the displayed plan. Stale / auto-resolved /
// single-source badge slots are Phase 3 — inert components wired for layout.
import { Badge, Group, Tooltip } from "@mantine/core";
import { IconStack2 } from "@tabler/icons-react";

import {
  AutoResolvedBadge,
  SingleSourceBadge,
  StaleBadge,
} from "../../components/badges/ListingBadges";
import { SCORE_MAX } from "../../lib/contracts";
import { semantic } from "../../theme";

// Pure, unit-tested: maps a total to a Mantine color name. Bands are anchored
// on the §9.3 engine domain — clamp [0, 15], base 10 — so green means "at or
// above base" (no net penalties), tuned here per P1-10.
export function scoreColor(
  total: number,
  max = SCORE_MAX,
): (typeof semantic.scoreBands)[keyof typeof semantic.scoreBands] {
  const pct = max > 0 ? total / max : 0;
  if (pct >= 2 / 3) return semantic.scoreBands.high;
  if (pct >= 1 / 2) return semantic.scoreBands.mid;
  if (pct >= 1 / 3) return semantic.scoreBands.low;
  return semantic.scoreBands.poor;
}

// Half-point deltas are common (§8.2 defaults); 9.5 must not read as 10.
export function formatScore(total: number): string {
  return Number.isInteger(total) ? String(total) : total.toFixed(1);
}

export interface ScoreCellProps {
  total: number;
  max?: number;
  scoredPlanCount?: number;
  pinned?: boolean;
}

export function ScoreCell({ total, max = SCORE_MAX, scoredPlanCount = 1, pinned }: ScoreCellProps) {
  return (
    <Group gap="xs" wrap="nowrap">
      <Badge color={scoreColor(total, max)} variant="filled">
        {formatScore(total)}
      </Badge>
      <StaleBadge />
      <AutoResolvedBadge />
      <SingleSourceBadge />
      {scoredPlanCount > 1 && (
        <Tooltip label={`${scoredPlanCount} scored plans — best shown`}>
          <Badge
            size="xs"
            variant="light"
            color={semantic.surface}
            leftSection={<IconStack2 size={12} stroke={1.5} />}
            aria-label="multiple scored plans"
          >
            {scoredPlanCount}
          </Badge>
        </Tooltip>
      )}
      {pinned && (
        <Badge size="xs" variant="outline" color={semantic.surface}>
          pinned
        </Badge>
      )}
    </Group>
  );
}
