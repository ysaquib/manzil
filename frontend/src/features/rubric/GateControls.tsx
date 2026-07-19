// Gate controls (§3, §13.2): the criterion-level non-negotiable toggle
// revealing its set-score input. Gates are consequential and rare — the
// set-score stays hidden until the toggle is on. Rendered as a row of the
// CriterionCard option grid so the input aligns with the points column.
import { NumberInput, Switch, Tooltip } from "@mantine/core";

import type { NonNegotiable } from "../../lib/contracts";
import { OptionGridRow } from "./OptionGridRow";

export function GateControls({
  nonNegotiable,
  onChange,
}: {
  nonNegotiable: NonNegotiable | null;
  onChange: (next: NonNegotiable | null) => void;
}) {
  return (
    <OptionGridRow>
      <Tooltip
        label="When this criterion's requirement isn't met, the listing's score is set directly instead of adding points"
        openDelay={300}
        position="top-start"
        maw={320}
        multiline
      >
        <Switch
          size="xs"
          label="Non-negotiable"
          checked={nonNegotiable !== null}
          onChange={(e) => onChange(e.currentTarget.checked ? { set_score: 0 } : null)}
        />
      </Tooltip>
      {nonNegotiable !== null ? (
        <Tooltip label="Score set when the gate fails" openDelay={300}>
          <NumberInput
            aria-label="non-negotiable set score"
            size="xs"
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
      <div />
    </OptionGridRow>
  );
}
