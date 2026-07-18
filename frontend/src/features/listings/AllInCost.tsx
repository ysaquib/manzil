// §9.5 P3-9 all-in cost UI: the Overview cell with the estimated portion
// visually distinct (`$1,845 (~$210 est.)`, §13.2) and the drawer's component
// breakdown with actual/estimated/unknown tags. Reads
// hunt_listings.all_in_components (display metadata) — the pinned
// scores.breakdown stays the scoring truth.
import { Badge, Group, Stack, Table, Text, Tooltip } from "@mantine/core";

import type { AllInComponents } from "./types";

const BADGE_COPY: Record<string, string> = {
  fees_unverified: "fees unverified",
  heat_unknown: "heating type unknown",
  utilities_not_estimated: "utilities not estimated",
};

const BADGE_HINT: Record<string, string> = {
  fees_unverified:
    "The page did not state utility inclusions or a needed estimate is missing — the all-in figure may be incomplete.",
  heat_unknown:
    "Heating fuel unknown — the worse of gas-heat and electric-heat estimates is used.",
  utilities_not_estimated:
    "No utility baselines exist for this metro yet — the all-in excludes utility estimates.",
};

const TAG_COLOR: Record<string, string> = {
  actual: "green",
  estimated: "yellow",
  unknown: "gray",
};

function CompositionBadges({ badges }: { badges: string[] }) {
  return (
    <>
      {badges.map((badge) => (
        <Tooltip key={badge} label={BADGE_HINT[badge] ?? badge} multiline w={260}>
          <Badge size="xs" color="yellow" variant="light">
            {BADGE_COPY[badge] ?? badge}
          </Badge>
        </Tooltip>
      ))}
    </>
  );
}

/** Overview all-in cell. `allIn` is the scored value from the row's breakdown;
 * the composition (listing-level, display plan) supplies the estimated portion
 * and badges. */
export function AllInCell({
  allIn,
  composition,
}: {
  allIn: number | null;
  composition: AllInComponents | null;
}) {
  const est = composition?.estimated_total ?? 0;
  const badges = composition?.badges ?? [];
  return (
    <Group gap={6} wrap="nowrap">
      <Text size="sm">{allIn === null ? "—" : `$${allIn.toLocaleString()}`}</Text>
      {allIn !== null && est > 0 && (
        <Text size="xs" c="dimmed">
          (~${est.toLocaleString()} est.)
        </Text>
      )}
      <CompositionBadges badges={badges} />
    </Group>
  );
}

/** Drawer section: the §9.5 component breakdown with tags. */
export function AllInBreakdown({ composition }: { composition: AllInComponents | null }) {
  if (composition === null) {
    return (
      <Text size="sm" c="dimmed">
        No composition yet — ingestion may still be running.
      </Text>
    );
  }
  return (
    <Stack gap="xs">
      {composition.badges.length > 0 && (
        <Group gap={6}>
          <CompositionBadges badges={composition.badges} />
        </Group>
      )}
      <Table verticalSpacing={4} withRowBorders={false}>
        <Table.Tbody>
          {composition.components.map((component, index) => (
            <Table.Tr key={`${component.name}:${index}`}>
              <Table.Td>
                <Text size="sm">{component.name.replaceAll("_", " ")}</Text>
                {component.note && (
                  <Text size="xs" c="dimmed">
                    {component.note}
                  </Text>
                )}
              </Table.Td>
              <Table.Td width={100}>
                <Text size="sm" ta="right">
                  {component.amount === null ? "unknown" : `$${component.amount.toLocaleString()}`}
                </Text>
              </Table.Td>
              <Table.Td width={90}>
                <Badge size="xs" color={TAG_COLOR[component.tag] ?? "gray"} variant="light">
                  {component.tag}
                </Badge>
              </Table.Td>
            </Table.Tr>
          ))}
          <Table.Tr>
            <Table.Td>
              <Text size="sm" fw={600}>
                All-in / mo ({composition.mode})
              </Text>
            </Table.Td>
            <Table.Td width={100}>
              <Text size="sm" fw={600} ta="right">
                {composition.total === null
                  ? "unknown"
                  : `$${composition.total.toLocaleString()}`}
              </Text>
            </Table.Td>
            <Table.Td width={90} />
          </Table.Tr>
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
