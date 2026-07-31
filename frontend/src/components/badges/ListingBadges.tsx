import { Badge, Box, Tooltip } from "@mantine/core";
import { IconAlertTriangle, IconClockExclamation } from "@tabler/icons-react";

import type { RefreshClass, SingleSourceReason } from "../../features/listings/types";

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
      <Badge size="xs" variant="light" color="yellow">
        {copy.label}
      </Badge>
    </Tooltip>
  );
}

export function ProblematicBadge() {
  return (
    <Tooltip label="Decision-relevant Sources still disagree; review the evidence or waiting task.">
      <Box c="yellow.6" display="flex" style={{ flexShrink: 0 }}>
        <IconAlertTriangle
          size={14}
          stroke={1.5}
          aria-label="Problematic"
        />
      </Box>
    </Tooltip>
  );
}
