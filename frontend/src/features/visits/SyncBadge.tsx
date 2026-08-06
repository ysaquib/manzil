// Pending-write indicator (VC-6, plan §7.2; reshaped in VC-12/VC-16).
//
// The promise the checklist makes is that an answer is never lost. This is
// where that promise is visible: when the signal dies, writes queue instead of
// failing, and the badge says how many are waiting.
//
// Two things were wrong with the first cut, and both were about *where* it sits
// rather than what it says:
//
//   * It rendered nothing when idle, so the moment a write started the badge
//     appeared and pushed every row below it down — on the one surface where
//     you are aiming one-handed at a specific 44px target. It now occupies a
//     reserved, fixed-height slot that is always in the layout. Empty or full,
//     nothing below it moves.
//
//   * `color="ochre"` names a colour `theme.ts` does not define, so Mantine
//     resolved it to the literal CSS string `ochre` and the badge rendered with
//     no background at all. The ochre scale lives in Mantine's `yellow` slot;
//     the status map is what knows that now.
import { Badge, Group, Text, Tooltip } from "@mantine/core";
import { IconCloudOff, IconRefresh } from "@tabler/icons-react";
import { useMutationState } from "@tanstack/react-query";

import { SAVE_ENTRIES_KEY } from "../../lib/offline";
import { isDemo } from "../../lib/demo";
import { toneFor } from "./statusColors";
import classes from "./SyncBadge.module.css";

/** Wording for a count of queued writes. */
export function pendingLabel(count: number): string {
  return count === 1 ? "1 change waiting to sync" : `${count} changes waiting to sync`;
}

export function SyncBadge() {
  // In demo mode there is no queue and never will be: a demo write is
  // intercepted before it reaches the network (apiClient.ts), so no mutation
  // ever pauses and the ordinary badge would sit permanently silent — quietly
  // implying everything had saved. Say the true thing instead, in the slot
  // already reserved for it.
  if (isDemo()) {
    return (
      <div className={classes.slot} aria-live="polite">
        <Tooltip
          multiline
          w={240}
          label="This is a demo. Your answers stay in this browser and are never sent anywhere — reload the page and the tour starts over."
        >
          <Badge
            size="sm"
            variant={toneFor("queued").variant}
            color={toneFor("queued").color}
            leftSection={<IconCloudOff size={12} aria-hidden />}
          >
            Demo — not saved
          </Badge>
        </Tooltip>
      </div>
    );
  }

  // Paused mutations are the queue: TanStack marks a write paused when the
  // browser is offline and resumes it on reconnect.
  const paused = useMutationState({
    filters: { mutationKey: SAVE_ENTRIES_KEY, status: "pending" },
    select: (mutation) => mutation.state.isPaused,
  });
  const waiting = paused.filter(Boolean).length;
  const inFlight = paused.length - waiting;

  // The slot is always rendered; only its contents change. That is the whole
  // fix — an element that appears and disappears is an element that reflows
  // everything under it.
  return (
    <div className={classes.slot} aria-live="polite">
      {waiting > 0 ? (
        <Tooltip
          multiline
          w={240}
          label="Your answers are saved on this device and will sync by themselves when the signal comes back. Nothing is lost."
        >
          <Badge
            size="sm"
            variant={toneFor("queued").variant}
            color={toneFor("queued").color}
            leftSection={<IconCloudOff size={12} aria-hidden />}
          >
            {pendingLabel(waiting)}
          </Badge>
        </Tooltip>
      ) : inFlight > 0 ? (
        <Group gap={6} wrap="nowrap">
          <IconRefresh size={14} className={classes.spin} aria-hidden />
          <Text size="xs" c="dimmed">
            Saving…
          </Text>
        </Group>
      ) : null}
    </div>
  );
}
