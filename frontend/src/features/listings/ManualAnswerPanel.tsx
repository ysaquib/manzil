// Manual custom Criteria have no producer (DESIGN §9.2): nothing extracts them
// and nothing refetches them, so the only way one ever gets a value is a person
// answering it here. Collecting them in one place makes that a single pass
// rather than a hunt through the score breakdown for dimmed rows.
import { Badge, Group, Stack, Text } from "@mantine/core";

import { useRubric, type CustomCriterionDef } from "../rubric/api";
import { WidgetForSchema } from "../rubric/widgets/widgetForSchema";
import type { WidgetValue } from "../rubric/widgets/types";
import { useListingDetailDraft } from "./ListingDetailDraft";
import { activeOverrides } from "./overrides";
import type { Override } from "./types";

/** A widget can only round-trip these; anything else reads as unanswered. */
function asWidgetValue(value: unknown): WidgetValue {
  return typeof value === "number" ||
    typeof value === "boolean" ||
    typeof value === "string" ||
    Array.isArray(value)
    ? (value as WidgetValue)
    : null;
}

export function manualCriteriaFor(
  rubric: { enabled: boolean; custom_def: CustomCriterionDef | null }[],
): CustomCriterionDef[] {
  return rubric
    .filter((criterion) => criterion.enabled && criterion.custom_def?.acquisition === "manual")
    .map((criterion) => criterion.custom_def as CustomCriterionDef);
}

/** Lets a caller drop the whole section when the Hunt has no manual Criteria. */
export function useManualCriteria(huntId: string): CustomCriterionDef[] {
  const { data: rubric = [] } = useRubric(huntId);
  return manualCriteriaFor(rubric);
}

export function ManualAnswerPanel({
  huntId,
  overrides,
  floorPlanId,
}: {
  huntId: string;
  overrides: Override[];
  floorPlanId: string | null;
}) {
  const { data: rubric = [] } = useRubric(huntId);
  const { draftOverrides, setDraftOverride } = useListingDetailDraft();
  const manual = manualCriteriaFor(rubric);
  if (manual.length === 0) return null;

  const saved = activeOverrides(overrides, floorPlanId);

  const answerFor = (custom: CustomCriterionDef): WidgetValue => {
    const draft = draftOverrides.get(custom.key);
    if (draft) return asWidgetValue(draft.value);
    return asWidgetValue(saved.get(custom.key)?.value);
  };

  const answered = manual.filter((custom) => answerFor(custom) !== null).length;

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="baseline">
        <Text size="xs" c="dimmed">
          Only you can answer these — nothing is read off the listing.
        </Text>
        <Badge variant="light" color={answered === manual.length ? "green" : "gray"}>
          {`${answered} of ${manual.length}`}
        </Badge>
      </Group>
      {manual.map((custom) => {
        const planScoped = custom.fact_scope === "floor_plan";
        // A Floor Plan-scoped answer needs a concrete plan to attach to; without
        // one the Override would silently widen to the whole Property.
        const blocked = planScoped && floorPlanId === null;
        return (
          <Stack key={custom.key} gap={4}>
            {blocked ? (
              <>
                <Text size="sm" fw={500}>
                  {custom.label}
                </Text>
                <Text size="xs" c="dimmed">
                  Pick a Floor Plan above to answer this one.
                </Text>
              </>
            ) : (
              <>
                <WidgetForSchema
                  schema={custom.value_schema}
                  value={answerFor(custom)}
                  onChange={(value) =>
                    setDraftOverride(custom.key, {
                      value,
                      note: null,
                      target_scope: planScoped ? "floor_plan" : "property",
                      floor_plan_id: planScoped ? floorPlanId : null,
                      applicability: planScoped ? "specific_floor_plans" : null,
                    })
                  }
                  label={custom.label}
                />
                <Text size="xs" c="dimmed">
                  {custom.description}
                </Text>
              </>
            )}
          </Stack>
        );
      })}
    </Stack>
  );
}
