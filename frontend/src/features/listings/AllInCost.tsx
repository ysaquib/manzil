// §9.5 P3-9 all-in cost UI: the Overview cell, with the estimated portion
// visually distinct (`$1,845 (~$210 est.)`, §13.2). Reads
// hunt_listings.all_in_components (display metadata) — the pinned
// scores.breakdown stays the scoring truth. The drawer's own ledger lives in
// CostAndFees (§9.5 consolidation).
import { Box, Group, Stack, Text, Tooltip } from "@mantine/core";
import { IconAlertTriangle, IconUserEdit } from "@tabler/icons-react";

import type { AllInComponents } from "./types";
import classes from "./OverviewTable.module.css";

const BADGE_COPY: Record<string, string> = {
  fees_unverified: "Fees unverified",
  heat_unknown: "Heating type unknown",
  utilities_not_estimated: "Utilities not estimated",
};

/** One quiet triangle instead of a chip per warning (§13.2 declutter): hover
 * lists the warning titles; the drawer keeps the full explanations. */
export function AllInWarningIcon({ badges }: { badges: string[] }) {
  if (badges.length === 0) return null;
  return (
    <Tooltip
      label={
        <Stack gap={2}>
          {badges.map((badge) => (
            <Text size="xs" key={badge}>
              {BADGE_COPY[badge] ?? badge}
            </Text>
          ))}
        </Stack>
      }
    >
      <Box c="yellow.6" display="flex" style={{ flexShrink: 0 }}>
        <IconAlertTriangle
          size={14}
          stroke={1.75}
          aria-label={`${badges.length} all-in warning${badges.length > 1 ? "s" : ""}`}
        />
      </Box>
    </Tooltip>
  );
}

/** Overview all-in cell. `allIn` is the scored value from the row's breakdown;
 * the composition (per-plan, display) supplies the estimated portion and
 * warnings. */
export function AllInCell({
  allIn,
  composition,
}: {
  allIn: number | null;
  composition: AllInComponents | null;
}) {
  const est = composition?.estimated_total ?? 0;
  // Unknown heat already uses the conservative worse-case estimate. It is
  // useful ledger provenance, but too frequent to be an Overview warning.
  const badges = (composition?.badges ?? []).filter((badge) => badge !== "heat_unknown");
  const overridden = composition?.overridden === true;
  return (
    <Group gap={6} wrap="nowrap">
      <Text size="sm" className={classes.figure}>
        {allIn === null ? "—" : `$${allIn.toLocaleString()}`}
      </Text>
      {overridden ? (
        <Tooltip label="Overridden manually — see the drawer for the composed figure">
          <Box c="dimmed" display="flex" style={{ flexShrink: 0 }}>
            <IconUserEdit size={14} stroke={1.5} aria-label="all-in overridden" />
          </Box>
        </Tooltip>
      ) : (
        allIn !== null &&
        est > 0 && (
          <Text size="xs" c="dimmed" className={classes.figure}>
            (~${est.toLocaleString()} est.)
          </Text>
        )
      )}
      <AllInWarningIcon badges={badges} />
    </Group>
  );
}
