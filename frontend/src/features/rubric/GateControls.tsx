// Gate controls (§3, §13.2): the criterion-level non-negotiable toggle
// revealing its set-score input. Gates are consequential and rare — the
// set-score stays hidden until the toggle is on. Rendered as a row of the
// CriterionCard option grid so the input aligns with the points column.
//
// On mobile the row reflows like every other: the switch takes the full first
// line and the set-score sits beneath it. The tooltip that explains what a gate
// does is hover-only, so once the gate is armed the same sentence is repeated
// as visible text — a control this consequential cannot explain itself only to
// a mouse (UI_DESIGN §5).
import { NumberInput, Stack, Switch, Text, Tooltip } from "@mantine/core";

import type { NonNegotiable } from "../../lib/contracts";
import type { ControlSizes } from "./controlSizes";
import { OptionGridRow } from "./OptionGridRow";

const GATE_EXPLANATION =
  "When this criterion's requirement isn't met, the listing's score is set directly instead of adding points";

export function GateControls({
  nonNegotiable,
  onChange,
  sizes,
}: {
  nonNegotiable: NonNegotiable | null;
  onChange: (next: NonNegotiable | null) => void;
  sizes: ControlSizes;
}) {
  const armed = nonNegotiable !== null;
  return (
    <OptionGridRow>
      <Stack gap={4}>
        <Tooltip label={GATE_EXPLANATION} openDelay={300} position="top-start" maw={320} multiline>
          <Switch
            size={sizes.switch}
            label="Non-negotiable"
            checked={armed}
            onChange={(e) => onChange(e.currentTarget.checked ? { set_score: 0 } : null)}
          />
        </Tooltip>
        {armed && (
          <Text size="xs" c="dimmed">
            Not met sets the listing's score to {nonNegotiable.set_score} instead of adding points.
          </Text>
        )}
      </Stack>
      {armed ? (
        <Tooltip label="Score set when the gate fails" openDelay={300}>
          <NumberInput
            aria-label="non-negotiable set score"
            size={sizes.input}
            min={0}
            max={15}
            prefix="→ "
            error
            value={nonNegotiable.set_score}
            onChange={(next) => onChange({ set_score: typeof next === "number" ? next : 0 })}
          />
        </Tooltip>
      ) : (
        <div />
      )}
      <div />
    </OptionGridRow>
  );
}
