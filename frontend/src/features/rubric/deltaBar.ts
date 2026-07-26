// Magnitude-bar math for the read-only rubric ledger (UI Decision Log
// 2026-07-25). Pure and unit-tested at the boundary (UI_DESIGN §6).
//
// The bar answers "which option actually moves the score", so it scales to the
// criterion's *own* largest delta rather than a global maximum — otherwise a
// ±0.25 criterion would render as four flat rows. Dealbreakers are excluded:
// their delta is meaningless (the option sets the final score outright), so
// letting one define the scale would flatten every real delta on the card.
import type { RubricOption } from "../../lib/contracts";

import { isOptionDealbreaker } from "./rubricDraft";

/** Largest |delta| on a criterion — the bar's full-scale reference. 0 if flat. */
export function deltaScale(options: RubricOption[], unknownDelta: number): number {
  const deltas = options
    .filter((option) => !isOptionDealbreaker(option))
    .map((option) => option.delta)
    .concat(unknownDelta);
  return deltas.reduce((max, delta) => Math.max(max, Math.abs(delta)), 0);
}

/** Fill fraction (0–1) for one delta at a given scale. */
export function deltaFill(delta: number, scale: number): number {
  if (scale <= 0) return 0;
  return Math.min(1, Math.abs(delta) / scale);
}
