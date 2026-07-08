// Gate controls (§3, §13.2): the criterion-level non-negotiable toggle
// revealing its set-score input. Gates are consequential and rare — the
// set-score stays hidden until the toggle is on.
import { Group, NumberInput, Switch, Text } from "@mantine/core";

import type { NonNegotiable } from "../../lib/contracts";

export function GateControls({
  nonNegotiable,
  onChange,
}: {
  nonNegotiable: NonNegotiable | null;
  onChange: (next: NonNegotiable | null) => void;
}) {
  return (
    <Group gap="sm" align="center">
      <Switch
        size="xs"
        label="Non-negotiable"
        checked={nonNegotiable !== null}
        onChange={(e) => onChange(e.currentTarget.checked ? { set_score: 0 } : null)}
      />
      {nonNegotiable !== null && (
        <>
          <Text size="xs" c="dimmed">
            if not met, score is set to
          </Text>
          <NumberInput
            aria-label="non-negotiable set score"
            size="xs"
            w={80}
            min={0}
            max={15}
            value={nonNegotiable.set_score}
            onChange={(next) =>
              onChange({ set_score: typeof next === "number" ? next : 0 })
            }
          />
        </>
      )}
    </Group>
  );
}
