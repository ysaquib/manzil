// One row of a criterion's option ledger. Always hand it exactly three
// children — match, points, actions — so the desktop columns line up and the
// mobile branch's "first child spans the row" rule has something predictable to
// act on. Use `<div />` for a cell with no control; the module drops empty
// cells on mobile rather than leaving a gap.
//
// Geometry (including the sub-`48em` reflow) lives in CriterionCard.module.css.
import { Box } from "@mantine/core";
import { forwardRef, type ReactNode } from "react";

import classes from "./CriterionCard.module.css";

export const OptionGridRow = forwardRef<HTMLDivElement, {
  children: ReactNode;
  // "header" is the column-heading row: same tracks on desktop, hidden on
  // mobile where the columns it names don't exist. Carried as `data-option-row`
  // rather than a second class so the module keys off it directly — and so
  // tests can find rows without a class name (vitest runs with `css: false`).
  variant?: "row" | "header";
}>(({ children, variant = "row" }, ref) => {
  return (
    <Box ref={ref} className={classes.row} data-option-row={variant}>
      {children}
    </Box>
  );
});

OptionGridRow.displayName = "OptionGridRow";
