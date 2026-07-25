// Floor plans + per-group pin control (P1-11, §9.4): draft-only until drawer Save.
import { Group, Radio, Stack, Text } from "@mantine/core";

import classes from "./FloorPlanPins.module.css";
import { useListingDetailDraft } from "./ListingDetailDraft";
import { formatScore, scoreColor } from "./scoreBands";
import { formatRange } from "./overviewRows";
import type { Score } from "./types";
import type { UnitGroupRow } from "./unitGroups";

function formatBedsBaths(beds: number, baths: number): string {
  return `${beds === 0 ? "Studio" : `${beds} bd`} / ${baths} ba`;
}

// scoreColor → chip band class: "scoreHighest" → "highest", etc. (§9.3 bands).
function bandClass(total: number): string {
  const band = scoreColor(total).replace("score", "").toLowerCase();
  return classes[band] ?? "";
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
            const availability = plan.availability_date;
            const unitTypes = plan.unit_types ?? [];
            return (
              <Radio.Card key={plan.id} value={plan.id} disabled={saving} p="sm" withBorder>
                <Group wrap="nowrap" align="flex-start" gap="sm" className={classes.plan}>
                  <Radio.Indicator />
                  <Stack gap={2} className={classes.planBody}>
                    <Group gap="sm" wrap="nowrap" className={classes.pn}>
                      <Text size="sm" fw={600} className={classes.planName}>
                        {plan.plan_name}
                      </Text>
                      {planScore && (
                        <Text
                          component="span"
                          className={`${classes.planScore} ${bandClass(planScore.total)}`}
                          data-testid={`plan-score-${plan.id}`}
                          data-band={scoreColor(planScore.total).replace("score", "").toLowerCase()}
                        >
                          {formatScore(planScore.total)}
                        </Text>
                      )}
                    </Group>
                    <Text size="xs" c="dimmed">
                      {formatBedsBaths(plan.beds, plan.baths)} ·{" "}
                      {formatRange(plan.sqft_min, plan.sqft_max)} sqft
                    </Text>
                    {unitTypes.length > 0 && (
                      <Text size="xs" c="dimmed">
                        {unitTypes.map((type) => type.replaceAll("_", " ")).join(", ")}
                      </Text>
                    )}
                  </Stack>
                  <Stack gap={1} className={classes.planRight}>
                    <Text size="sm" fw={600} className={classes.rent}>
                      {formatRange(plan.rent_min, plan.rent_max, "$")}
                    </Text>
                    {availability && (
                      <Text size="xs" c="dimmed">
                        avail {availability}
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
