// Score cell (Phase 1 plan §5.3, DESIGN §9.4/§13.2): color scale by total, a
// stacked-layers indicator when a Unit Group has >1 scored plan, a pinned tag
// when a per-group pin picked the displayed plan. Stale / auto-resolved /
// single-source badge slots are Phase 3 — rendered inert here.
import { Badge, Group, Text, Tooltip } from "@mantine/core";

import { SCORE_MAX } from "../../lib/contracts";

// Pure, unit-tested: maps a total to a Mantine color name. Bands are anchored
// on the §9.3 engine domain — clamp [0, 15], base 10 — so green means "at or
// above base" (no net penalties), tuned here per P1-10.
export function scoreColor(total: number, max = SCORE_MAX): "green" | "lime" | "yellow" | "red" {
  const pct = max > 0 ? total / max : 0;
  if (pct >= 2 / 3) return "green";
  if (pct >= 1 / 2) return "lime";
  if (pct >= 1 / 3) return "yellow";
  return "red";
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
      {scoredPlanCount > 1 && (
        <Tooltip label={`${scoredPlanCount} scored plans — best shown`}>
          <Text size="xs" c="dimmed" aria-label="multiple scored plans">
            ▤ {scoredPlanCount}
          </Text>
        </Tooltip>
      )}
      {pinned && (
        <Badge size="xs" variant="outline" color="gray">
          pinned
        </Badge>
      )}
    </Group>
  );
}
