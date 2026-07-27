// Override control (P1-11, §9.6): per-criterion affordance — edits stage in the
// drawer draft until Save.
import { ActionIcon, Button, Popover, Select, Stack, TextInput, Tooltip } from "@mantine/core";
import { IconPencil } from "@tabler/icons-react";
import { useState } from "react";

import { useListingDetailDraft } from "./ListingDetailDraft";
import { WidgetForSchema } from "../rubric/widgets/widgetForSchema";
import type { ValueSchema } from "../rubric/widgets/types";
import type { WidgetValue } from "../rubric/widgets/types";

/** Portaled combobox dropdowns sit outside the Popover DOM and count as outside clicks. */
const NESTED_COMBOBOX_PROPS = { withinPortal: false } as const;

export function OverrideControl({
  criterionKey,
  schema,
  currentValue,
  factScope,
  floorPlanId,
}: {
  criterionKey: string;
  schema: ValueSchema | undefined;
  currentValue: unknown;
  factScope: "property" | "floor_plan" | "mixed" | "composed" | undefined;
  floorPlanId: string | null;
}) {
  const { draftOverrides, setDraftOverride } = useListingDetailDraft();
  const [opened, setOpened] = useState(false);
  const [value, setValue] = useState<WidgetValue>(null);
  const [note, setNote] = useState("");
  const [target, setTarget] = useState<"floor_plan" | "all_units">("floor_plan");

  const draftEntry = draftOverrides.get(criterionKey);

  const open = () => {
    if (draftEntry) {
      const seed = draftEntry.value;
      setValue(
        typeof seed === "number" || typeof seed === "boolean" || typeof seed === "string"
          ? seed
          : null,
      );
      setNote(draftEntry.note ?? "");
      setTarget(draftEntry.applicability === "all_units" ? "all_units" : "floor_plan");
    } else {
      const seed = currentValue;
      setValue(
        typeof seed === "number" || typeof seed === "boolean" || typeof seed === "string"
          ? seed
          : null,
      );
      setNote("");
      setTarget("floor_plan");
    }
    setOpened(true);
  };

  const apply = () => {
    const exact = target === "floor_plan" && floorPlanId !== null;
    setDraftOverride(criterionKey, {
      value,
      note: note.trim() || null,
      target_scope: exact ? "floor_plan" : "property",
      floor_plan_id: exact ? floorPlanId : null,
      applicability: exact ? "specific_floor_plans" : target === "all_units" ? "all_units" : null,
    });
    setOpened(false);
  };

  return (
    <Popover opened={opened} onChange={setOpened} width={260} position="bottom-end" withArrow>
      <Popover.Target>
        <Tooltip label="Override" openDelay={450}>
          <ActionIcon
            color="gray"
            size="sm"
            variant="subtle"
            onClick={open}
            aria-label={`override ${criterionKey}`}
          >
            <IconPencil size={14} stroke={1.5} color="var(--mantine-color-dimmed)" />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs">
          {(factScope === "floor_plan" || factScope === "mixed") && floorPlanId && (
            <Select
              label="Applies to"
              data={[
                { value: "floor_plan", label: "This Floor Plan" },
                { value: "all_units", label: "All units" },
              ]}
              value={target}
              onChange={(next) => setTarget(next === "all_units" ? "all_units" : "floor_plan")}
              allowDeselect={false}
              comboboxProps={NESTED_COMBOBOX_PROPS}
            />
          )}
          {schema ? (
            <WidgetForSchema
              schema={schema}
              value={value}
              onChange={setValue}
              label="New value"
              comboboxProps={NESTED_COMBOBOX_PROPS}
            />
          ) : (
            <TextInput
              label="New value"
              value={value === null ? "" : String(value)}
              onChange={(e) => setValue(e.currentTarget.value)}
            />
          )}
          <TextInput
            label="Note"
            placeholder="e.g. confirmed by leasing office"
            value={note}
            onChange={(e) => setNote(e.currentTarget.value)}
          />
          <Button size="xs" onClick={apply}>
            Apply
          </Button>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
