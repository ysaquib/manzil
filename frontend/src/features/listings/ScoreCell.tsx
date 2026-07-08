// Score cell (Phase 1 plan §5.3, DESIGN §9.4/§13.2): color scale by total, a
// stacked-layers indicator when a Unit Group has >1 scored plan. Stale /
// auto-resolved / single-source badge slots are Phase 3 — rendered inert here.
import { Badge, Group, Text } from "@mantine/core";

// Pure, unit-tested: maps a total to a Mantine color name. Score domain is the
// rubric's point total; thresholds are proportional bands, tuned in P1-10.
export function scoreColor(total: number, max = 100): "green" | "lime" | "yellow" | "red" {
  const pct = max > 0 ? (total / max) * 100 : 0;
  if (pct >= 75) return "green";
  if (pct >= 50) return "lime";
  if (pct >= 25) return "yellow";
  return "red";
}

export interface ScoreCellProps {
  total: number;
  max?: number;
  scoredPlanCount?: number;
}

export function ScoreCell({ total, max = 100, scoredPlanCount = 1 }: ScoreCellProps) {
  return (
    <Group gap="xs" wrap="nowrap">
      <Badge color={scoreColor(total, max)} variant="filled">
        {Math.round(total)}
      </Badge>
      {scoredPlanCount > 1 && (
        <Text size="xs" c="dimmed" aria-label="multiple scored plans">
          ▤ {scoredPlanCount}
        </Text>
      )}
    </Group>
  );
}
