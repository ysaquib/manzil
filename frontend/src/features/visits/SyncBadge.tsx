// Pending-write indicator (VC-6, plan §7.2).
//
// The promise the checklist makes is that an answer is never lost. This is
// where that promise is visible: when the signal dies, writes queue instead of
// failing, and the badge says how many are waiting. Silence when there is
// nothing pending — a permanent "synced" chip would be noise on a surface
// people glance at between rooms.
import { Badge, Group, Text, Tooltip } from "@mantine/core";
import { IconCloudOff, IconRefresh } from "@tabler/icons-react";
import { useMutationState } from "@tanstack/react-query";

import { SAVE_ENTRIES_KEY } from "../../lib/offline";
import classes from "./SyncBadge.module.css";

/** Wording for a count of queued writes. */
export function pendingLabel(count: number): string {
  return count === 1 ? "1 change waiting to sync" : `${count} changes waiting to sync`;
}

export function SyncBadge() {
  // Paused mutations are the queue: TanStack marks a write paused when the
  // browser is offline and resumes it on reconnect.
  const paused = useMutationState({
    filters: { mutationKey: SAVE_ENTRIES_KEY, status: "pending" },
    select: (mutation) => mutation.state.isPaused,
  });
  const waiting = paused.filter(Boolean).length;
  const inFlight = paused.length - waiting;

  if (waiting === 0 && inFlight === 0) return null;

  if (waiting === 0) {
    return (
      <Group gap={6} wrap="nowrap" aria-live="polite">
        <IconRefresh size={14} className={classes.spin} aria-hidden />
        <Text size="xs" c="dimmed">
          Saving…
        </Text>
      </Group>
    );
  }

  return (
    <Tooltip
      multiline
      w={240}
      label="Your answers are saved on this device and will sync by themselves when the signal comes back. Nothing is lost."
    >
      <Badge
        size="sm"
        variant="light"
        color="ochre"
        leftSection={<IconCloudOff size={12} aria-hidden />}
        aria-live="polite"
      >
        {pendingLabel(waiting)}
      </Badge>
    </Tooltip>
  );
}
