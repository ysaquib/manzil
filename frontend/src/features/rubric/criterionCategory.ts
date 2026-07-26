// Category → Mantine color name for the rubric cards (UI_DESIGN §2: dynamic
// color is a pure function returning a palette *name*, never a hex).
//
// The hue is identity, not status: it tints a criterion's icon tile and its
// group rule, and never changes with state. Two scales are deliberately absent
// — grape (human-entered values) and red/dusty brick (danger, gate firings) —
// so a tile can never be misread as a status marker (UI_DESIGN §4).
// (UI Decision Log 2026-07-25.)
// Weathered teal is absent as well: it already means "waiting on you"
// (checkpoints) everywhere else in the app.
const CATEGORY_COLOR: Record<string, string> = {
  unit: "blue", // slate blue
  cost: "yellow", // muted ochre
  tenancy: "cyan", // fog blue
  location: "green", // sage
  fittings: "orange", // burnt clay
  amenities: "indigo", // storm
  management: "pink", // dusty rose
};

/** Mantine color name for a criterion category; warm-neutral for anything new. */
export function categoryColor(category: string): string {
  return CATEGORY_COLOR[category] ?? "gray";
}
