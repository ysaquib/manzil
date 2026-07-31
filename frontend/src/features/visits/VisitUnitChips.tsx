// The units walked on a Visit, as chips. A unit the listing never advertised
// carries a dashed outline and says so on hover — never implying the listing
// described it (DESIGN §9.7).
import { Badge, Group, Text, Tooltip } from "@mantine/core";

import { unitGroupLabel } from "../listings/unitGroups";
import type { VisitUnit } from "./types";

export function VisitUnitChips({
  units,
  planNames,
}: {
  units: VisitUnit[];
  /** floor_plan_id → plan name, when the listing is loaded. */
  planNames?: Map<string, string>;
}) {
  if (units.length === 0) {
    return (
      <Text size="xs" c="dimmed" fs="italic">
        No units yet
      </Text>
    );
  }
  return (
    <Group gap={6} wrap="wrap">
      {units.map((unit) => {
        const custom = unit.floor_plan_id === null;
        const planName = unit.floor_plan_id ? planNames?.get(unit.floor_plan_id) : undefined;
        const detail = [planName, unitGroupLabel(unit.beds, unit.baths)]
          .filter(Boolean)
          .join(" · ");
        return (
          <Tooltip
            key={unit.id}
            label={custom ? `${detail} · not advertised by the listing` : detail}
          >
            <Badge
              variant="outline"
              radius="sm"
              color={custom ? "teal" : "gray"}
              style={custom ? { borderStyle: "dashed" } : undefined}
            >
              {unit.label}
            </Badge>
          </Tooltip>
        );
      })}
    </Group>
  );
}
