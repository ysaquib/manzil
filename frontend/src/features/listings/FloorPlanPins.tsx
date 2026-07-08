// Floor plans + per-group pin control (P1-11, §9.4): each plan is scored
// independently; pinning switches the group's displayed plan and score.
// PATCH /v1/listings/{id}/pins carries the whole pins map (§8.2 shape).
import { Badge, Group, Radio, Stack, Text } from "@mantine/core";

import { formatScore, scoreColor } from "./ScoreCell";
import { usePatchPins } from "./api";
import { formatRange } from "./overviewRows";
import type { Listing, Score } from "./types";
import type { UnitGroupRow } from "./unitGroups";

export function FloorPlanPins({
  huntId,
  listing,
  group,
}: {
  huntId: string;
  listing: Listing;
  group: UnitGroupRow;
}) {
  const patchPins = usePatchPins(huntId);
  const scoreByPlan = new Map<string, Score>(listing.scores.map((s) => [s.floor_plan_id, s]));

  const setPin = (planId: string | null) => {
    const pins = { ...listing.pins };
    if (planId === null) delete pins[group.key];
    else pins[group.key] = planId;
    patchPins.mutate({ listingId: listing.id, pins });
  };

  return (
    <Radio.Group
      value={group.pinnedPlanId ?? "best"}
      onChange={(next) => setPin(next === "best" ? null : next)}
    >
      <Stack gap="xs">
        <Radio
          value="best"
          label={
            <Text size="sm" span>
              Best-scored plan (default)
            </Text>
          }
        />
        {group.plans.map((plan) => {
          const score = scoreByPlan.get(plan.id);
          return (
            <Radio
              key={plan.id}
              value={plan.id}
              label={
                <Group gap="xs" wrap="nowrap">
                  <Text size="sm" span fw={600}>
                    {plan.plan_name}
                  </Text>
                  <Text size="xs" span c="dimmed">
                    {formatRange(plan.rent_min, plan.rent_max, "$")} ·{" "}
                    {formatRange(plan.sqft_min, plan.sqft_max)} sqft
                    {plan.availability_date ? ` · avail ${plan.availability_date}` : ""}
                  </Text>
                  {score && (
                    <Badge size="xs" color={scoreColor(score.total)} variant="light">
                      {formatScore(score.total)}
                    </Badge>
                  )}
                </Group>
              }
            />
          );
        })}
      </Stack>
    </Radio.Group>
  );
}
