// Collapsed Floor Plan card (P3-SC5, §9.4). The card carries enough to rank a
// Unit Group's plans without opening any of them — diagram thumbnail, plan
// identity, the four amenity counts, rent + all-in, and this plan's own score.
// Opening it is the deep read; the modal owns that.
import {
  ActionIcon,
  Box,
  Group,
  Image,
  Paper,
  Text,
  Tooltip,
  UnstyledButton,
  VisuallyHidden,
} from "@mantine/core";
import { IconPin, IconPinFilled } from "@tabler/icons-react";

import classes from "./FloorPlanCard.module.css";
import type { AmenityCounts } from "./floorPlanAmenities";
import { formatRange } from "./overviewRows";
import { formatScore, scoreColor } from "./scoreBands";
import type { FloorPlan, Score } from "./types";

// scoreColor → band class: "scoreHighest" → "highest" (§9.3 bands).
function bandName(total: number): string {
  return scoreColor(total).replace("score", "").toLowerCase();
}

const COUNT_GLYPH: Record<keyof AmenityCounts, string> = {
  confirmed: "✓",
  advertised: "~",
  absent: "✕",
  unknown: "?",
};

const COUNT_LABEL: Record<keyof AmenityCounts, string> = {
  confirmed: "confirmed",
  advertised: "advertised, unconfirmed",
  absent: "not available",
  unknown: "unknown",
};

export interface FloorPlanCardProps {
  plan: FloorPlan;
  score: Score | undefined;
  counts: AmenityCounts;
  /** Signed URL for this plan's first current diagram; null when none. */
  diagramUrl: string | null;
  pinned: boolean;
  /** This plan's detail modal is open. */
  active: boolean;
  /** Retired by a later refresh but retained (§8.2 `is_current`). */
  inactive?: boolean;
  allIn: number | null;
  unitGroupLabel: string;
  disabled?: boolean;
  onOpen: () => void;
  onTogglePin: () => void;
}

export function FloorPlanCard({
  plan,
  score,
  counts,
  diagramUrl,
  pinned,
  active,
  inactive,
  allIn,
  unitGroupLabel,
  disabled,
  onOpen,
  onTogglePin,
}: FloorPlanCardProps) {
  const rootClasses = [
    classes.card,
    pinned ? classes.pinned : "",
    active ? classes.active : "",
    inactive ? classes.inactive : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Paper withBorder radius="md" p="xs" className={rootClasses} data-testid={`plan-card-${plan.id}`}>
      <UnstyledButton
        className={classes.open}
        aria-haspopup="dialog"
        aria-label={`Open ${plan.plan_name} floor plan detail`}
        onClick={onOpen}
      />

      <Box className={classes.grid}>
        {diagramUrl ? (
          <Box className={classes.thumb}>
            <Image src={diagramUrl} alt={`${plan.plan_name} floor plan diagram`} loading="lazy" />
          </Box>
        ) : (
          <Box
            className={`${classes.thumb} ${classes.thumbEmpty}`}
            role="img"
            aria-label={`No floor plan diagram for ${plan.plan_name}`}
          >
            <Text fz="0.625rem" c="dimmed" ta="center" lh={1.2} aria-hidden>
              no
              <br />
              diagram
            </Text>
          </Box>
        )}

        <Box className={classes.id}>
          <Group gap="xs" wrap="nowrap">
            <Text fw={600} className={classes.name}>
              {plan.plan_name}
            </Text>
            {inactive && (
              <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>
                no longer listed
              </Text>
            )}
          </Group>
          <Text size="xs" c="dimmed">
            {formatRange(plan.sqft_min, plan.sqft_max)} sqft
            {plan.unit_types?.length
              ? ` · ${plan.unit_types.map((type) => type.replaceAll("_", " ")).join(", ")}`
              : ""}
            {plan.availability_date ? ` · avail ${plan.availability_date}` : ""}
          </Text>
          <Box className={classes.counts} aria-label="amenity summary">
            {(Object.keys(COUNT_GLYPH) as (keyof AmenityCounts)[]).map((state) => (
              <Text
                key={state}
                component="span"
                size="xs"
                className={classes.count}
                data-state={state}
              >
                <Text component="span" fz="0.625rem" aria-hidden>
                  {COUNT_GLYPH[state]}
                </Text>
                {counts[state]}
                <VisuallyHidden>{` ${COUNT_LABEL[state]}`}</VisuallyHidden>
              </Text>
            ))}
          </Box>
        </Box>

        <Box className={classes.rent}>
          <Text fw={600}>{formatRange(plan.rent_min, plan.rent_max, "$")}</Text>
          <Text size="xs" c="dimmed">
            {allIn === null ? "all-in unknown" : `$${allIn.toLocaleString()} all-in`}
          </Text>
        </Box>

        <Box className={classes.rail}>
          {score && (
            <Text
              component="span"
              className={`${classes.score} ${classes[bandName(score.total)] ?? ""}`}
              data-testid={`plan-score-${plan.id}`}
              data-band={bandName(score.total)}
            >
              {formatScore(score.total)}
            </Text>
          )}
          <Tooltip
            label={
              pinned
                ? `Pinned — this plan represents the ${unitGroupLabel} row`
                : `Pin this plan for ${unitGroupLabel}`
            }
          >
            <ActionIcon
              variant={pinned ? "light" : "subtle"}
              color={pinned ? "dusky" : "gray"}
              size="lg"
              disabled={disabled}
              aria-pressed={pinned}
              aria-label={`${pinned ? "Unpin" : "Pin"} ${plan.plan_name} for ${unitGroupLabel}`}
              onClick={onTogglePin}
            >
              {pinned ? <IconPinFilled size={17} /> : <IconPin size={17} stroke={2} />}
            </ActionIcon>
          </Tooltip>
        </Box>
      </Box>
    </Paper>
  );
}
