// Floor plans + per-group pin control (P1-11, §9.4): draft-only until drawer Save.
import { Badge, Group, Radio, Stack, Text } from "@mantine/core";

import { useListingDetailDraft } from "./ListingDetailDraft";
import { formatScore, scoreColor } from "./ScoreCell";
import { formatRange } from "./overviewRows";
import type { Score } from "./types";
import type { UnitGroupRow } from "./unitGroups";

function formatBedsBaths(beds: number, baths: number): string {
  return `${beds === 0 ? "Studio" : `${beds} bd`} / ${baths} ba`;
}

export function FloorPlanPins({
  group,
  scores,
}: {
  group: UnitGroupRow;
  scores: Score[];
}) {
  const { draftPins, setDraftPin, saving } = useListingDetailDraft();
  const scoreByPlan = new Map<string, Score>(scores.map((s) => [s.floor_plan_id, s]));
  const value = draftPins[group.key] ?? "best";

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Choose which floor plan&apos;s score to show for this unit type.
      </Text>
      <Radio.Group
        value={value}
        onChange={(next) => setDraftPin(group.key, next === "best" ? null : next)}
      >
        <Stack gap="xs">
          <Radio.Card value="best" disabled={saving} p="sm" withBorder>
            <Group wrap="nowrap" align="flex-start" gap="sm">
              <Radio.Indicator />
              <Text size="sm">Best-scored plan (default)</Text>
            </Group>
          </Radio.Card>
          {group.plans.map((plan) => {
            const planScore = scoreByPlan.get(plan.id);
            return (
              <Radio.Card key={plan.id} value={plan.id} disabled={saving} p="sm" withBorder>
                <Group wrap="nowrap" align="flex-start" gap="sm">
                  <Radio.Indicator />
                  <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
                    <Group gap="xs" wrap="wrap">
                      <Text size="sm" fw={600}>
                        {plan.plan_name}
                      </Text>
                      {planScore && (
                        <Badge size="xs" color={scoreColor(planScore.total)} variant="light">
                          {formatScore(planScore.total)}
                        </Badge>
                      )}
                    </Group>
                    <Text size="xs" c="dimmed">
                      {formatBedsBaths(plan.beds, plan.baths)} ·{" "}
                      {formatRange(plan.rent_min, plan.rent_max, "$")} ·{" "}
                      {formatRange(plan.sqft_min, plan.sqft_max)} sqft
                      {plan.availability_date ? ` · avail ${plan.availability_date}` : ""}
                    </Text>
                    {(plan.unit_types?.length ?? 0) > 0 && (
                      <Text size="xs" c="dimmed">
                        {plan.unit_types?.map((type) => type.replaceAll("_", " ")).join(", ")}
                      </Text>
                    )}
                  </Stack>
                </Group>
              </Radio.Card>
            );
          })}
        </Stack>
      </Radio.Group>
    </Stack>
  );
}
