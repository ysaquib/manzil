import { Box, Popover, Stack, Text, Tooltip, UnstyledButton } from "@mantine/core";
import { IconAlertTriangle, IconClockExclamation, IconLink } from "@tabler/icons-react";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";

import type { RefreshClass, RefreshStall, SingleSourceReason } from "../../features/listings/types";

dayjs.extend(relativeTime);

// Badge slots for Phase 3 TTL/checkpoint semantics (Phase 1 plan §5.2).

const REFRESH_CLASS_LABELS: Record<RefreshClass, string> = {
  pricing: "pricing",
  listing_details: "listing details",
  images: "images",
  reviews: "reviews",
  location: "location",
};

export function StaleBadge({ classes = [] }: { classes?: RefreshClass[] }) {
  if (classes.length === 0) return null;
  return (
    <Tooltip label={`Refresh due: ${classes.map((item) => REFRESH_CLASS_LABELS[item]).join(", ")}`}>
      <Box c="yellow.7" display="flex" style={{ flexShrink: 0 }}>
        <IconClockExclamation size={14} stroke={1.5} aria-label="Stale data" />
      </Box>
    </Tooltip>
  );
}

export function AutoResolvedBadge() {
  return (
    <Tooltip label="A checkpoint used its default after 24 hours. Open the Listing to review it.">
      <Box c="clay.7" display="flex" style={{ flexShrink: 0 }}>
        <IconClockExclamation
          size={14}
          stroke={1.5}
          aria-label="Checkpoint auto-resolved"
        />
      </Box>
    </Tooltip>
  );
}

const SINGLE_SOURCE_COPY: Record<SingleSourceReason, { label: string; detail: string }> = {
  trust_link: {
    label: "Single source",
    detail: "Not cross-checked — by choice",
  },
  discover_exhausted: {
    label: "Single source",
    detail: "Only one site was found for this property",
  },
  discover_failed: {
    label: "Cross-check unavailable",
    detail: "Source discovery could not complete; this listing is not cross-checked",
  },
};

export function SingleSourceBadge({ reason }: { reason: SingleSourceReason }) {
  const copy = SINGLE_SOURCE_COPY[reason];
  return (
    <Tooltip label={copy.detail}>
      <Box c="yellow.7" display="flex" style={{ flexShrink: 0 }}>
        <IconLink size={14} stroke={1.5} aria-label={copy.label} />
      </Box>
    </Tooltip>
  );
}

export function ProblematicBadge() {
  return (
    <Tooltip label="Decision-relevant Sources still disagree; review the evidence or waiting task.">
      <Box c="dimmed" display="flex" style={{ flexShrink: 0 }}>
        <IconAlertTriangle
          size={14}
          stroke={1.5}
          aria-label="Problematic"
        />
      </Box>
    </Tooltip>
  );
}

const STALL_OUTCOME_COPY: Record<string, string> = {
  images_partial: "Some photos on the source page keep failing to download.",
  enrich_no_geocode: "The Property has no geocode yet, so location-derived checks can't run.",
  location_refresh_failed: "The location lookup failed.",
  reviews_refresh_failed: "The reviews lookup failed.",
  job_failed: "The refresh job failed.",
  job_dispatch_error: "The refresh job failed unexpectedly.",
  unmarked: "The refresh completed without confirming this class.",
};

function describeStallOutcome(stall: RefreshStall): string {
  const detail = stall.last_outcome_detail;
  if (stall.refresh_class === "images" && typeof detail.photo_count === "number") {
    const failed = typeof detail.failed_candidates === "number" ? detail.failed_candidates : undefined;
    const progressed = detail.progressed === true;
    const plural = detail.photo_count === 1 ? "" : "s";
    const failedPart =
      failed && failed > 0
        ? ` ${failed} candidate${failed === 1 ? "" : "s"} keep${failed === 1 ? "s" : ""} failing to download;`
        : "";
    const progressPart = progressed
      ? "the gallery grew since the last attempt, so retries continue at the base delay."
      : "no new images were found on the last attempt.";
    return `Gallery holds ${detail.photo_count} usable photo${plural}.${failedPart} ${progressPart}`;
  }
  if (typeof detail.message === "string") return detail.message;
  if (typeof detail.error === "string") return detail.error;
  return STALL_OUTCOME_COPY[stall.last_outcome_code] ?? STALL_OUTCOME_COPY.unmarked;
}

/** Click-to-open, drawer-only observability for P3-12 exponential refresh
 * backoff (DESIGN §14, §20 2026-08-25): a row exists in `hunt_listing_refresh_
 * stalls` only while the scheduler saw a class due and withheld it after
 * repeated non-results. Deliberately a different icon/color pairing from
 * `ProblematicBadge` and a click (not hover) target, since the detail is
 * meant to stay out of the way until someone goes looking for it. */
export function RefreshStalledBadge({ stalls }: { stalls: RefreshStall[] }) {
  if (stalls.length === 0) return null;
  return (
    <Popover width={340} position="bottom-start" withArrow shadow="md" withinPortal>
      <Popover.Target>
        <UnstyledButton
          aria-label={`Refresh backed off for ${stalls.length} class${stalls.length === 1 ? "" : "es"}. Open details.`}
          display="flex"
          c="blue.6"
          style={{ flexShrink: 0 }}
        >
          <IconClockExclamation size={14} stroke={1.5} />
        </UnstyledButton>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="sm">
          <Text size="xs" fw={700}>
            Refresh backed off
          </Text>
          <Text size="xs" c="dimmed">
            The scheduler saw this Listing due for a refresh but withheld it after repeated
            attempts produced no result. It keeps retrying on a growing delay, up to once every
            72 hours, and will pick back up on its own the moment a check succeeds.
          </Text>
          {stalls.map((stall) => (
            <Box key={stall.refresh_class}>
              <Text size="xs" fw={600} tt="capitalize">
                {REFRESH_CLASS_LABELS[stall.refresh_class]}
              </Text>
              <Text size="xs" c="dimmed">
                {describeStallOutcome(stall)}
              </Text>
              <Text size="xs" c="dimmed">
                {stall.consecutive_stalls} attempt{stall.consecutive_stalls === 1 ? "" : "s"} in a
                row · last tried {dayjs(stall.last_attempt_at).fromNow()} · next try{" "}
                {dayjs(stall.next_eligible_at).fromNow()}
              </Text>
            </Box>
          ))}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
