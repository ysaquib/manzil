// One dial for how large the rubric editor's controls are (UI Decision Log
// 2026-08-11).
//
// Below `48em` every control has to clear the ~44px target UI_DESIGN §5 asks
// for, and every input's type has to clear 16px — the line under which iOS
// Safari zooms the page on focus and does not zoom back. At `size="xs"` the
// editor's inputs are 30px at 12px type and its icon buttons 18–22px, so a
// phone fails all three.
//
// This travels as props rather than living in the CSS Module beside the rest of
// the mobile reflow, because Mantine 9 writes each `size` prop to inline CSS
// variables on the component root — `--input-height: var(--input-height-xs)`
// sits in the wrapper's own `style` attribute — and an inline declaration beats
// any class. Redefining `--input-height-xs` on an ancestor would work, but it
// quietly changes a theme token for anything that later lands in the row.
import { useMediaQuery } from "@mantine/hooks";

export type ControlSizes = {
  /** Match, points and set-score inputs. */
  input: "xs" | "md";
  /** Dealbreaker and remove, inside an option row. */
  action: "sm" | "xl";
  /** The catalog hint and the remove-custom-criterion button in the header. */
  headerAction: "xs" | "xl";
  /** The non-negotiable gate toggle. */
  switch: "xs" | "md";
  /** The card header's enable toggle. */
  headerSwitch: "sm" | "md";
  /** "Add option". */
  button: "xs" | "md";
  /** Glyph inside an icon button; deliberately smaller than its target. */
  glyph: number;
};

const DENSE: ControlSizes = {
  input: "xs",
  action: "sm",
  headerAction: "xs",
  switch: "xs",
  headerSwitch: "sm",
  button: "xs",
  glyph: 14,
};

const TOUCH: ControlSizes = {
  input: "md",
  action: "xl",
  headerAction: "xl",
  switch: "md",
  headerSwitch: "md",
  button: "md",
  glyph: 18,
};

export function useControlSizes(): ControlSizes {
  // `getInitialValueInEffect: false` answers the query during the first render
  // instead of after it. The editor mounts ~30 of these at once, and the default
  // would render every card dense and then re-render it — a visible flash of
  // 30px controls on the one device that can't use them.
  //
  // Falls back to the dense set where `matchMedia` is unavailable (jsdom), which
  // is what every existing viewport already renders.
  const isCompact = useMediaQuery("(max-width: 48em)", false, {
    getInitialValueInEffect: false,
  });
  return isCompact ? TOUCH : DENSE;
}
