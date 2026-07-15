import { Badge, Group, Tooltip } from "@mantine/core";
import { IconStack2 } from "@tabler/icons-react";
import { AutoResolvedBadge, SingleSourceBadge, StaleBadge } from "../../components/badges/ListingBadges";

export interface InfoCellProps {
  scoredPlanCount?: number;
  stale?: boolean;
  autoResolved?: boolean;
  singleSource?: boolean;
}
  
export function InfoCell({ scoredPlanCount = 1, stale, autoResolved, singleSource }: InfoCellProps) {
  return (
    <Group gap={"xs"} wrap="nowrap">
      {stale && <StaleBadge />}
      {autoResolved && <AutoResolvedBadge />}
      {singleSource && <SingleSourceBadge />}
      {scoredPlanCount > 1 && (
        <Tooltip label={`${scoredPlanCount} scored plans — best shown`}>
          <Badge
            size="sm"
            variant="light"
            color={"surface"}
            leftSection={<IconStack2 size={12} stroke={1.5} />}
            aria-label="multiple scored plans"
            >
            {scoredPlanCount}
          </Badge>
        </Tooltip>
      )}
    </Group>
  );
}
