import { Badge, Tooltip } from "@mantine/core";

import type { SingleSourceReason } from "../../features/listings/types";

// Badge slots for Phase 3 TTL/checkpoint semantics (Phase 1 plan §5.2).

export function StaleBadge() {
  return null;
}

export function AutoResolvedBadge() {
  return null;
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
      <Badge size="xs" variant="light" color="red">
        Problematic
      </Badge>
    </Tooltip>
  );
}
