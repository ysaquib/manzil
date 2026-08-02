// Every status colour the Visits surfaces use, in one place (VC-12).
//
// The bug this exists to stop had three separate shapes, all of them "a
// component picked a colour itself":
//
//  1. `color="ochre"` — a colour `theme.ts` does not define. Mantine resolved it
//     to the literal CSS string `ochre`, which is not a colour, so the sync
//     badge rendered with no background at all. The ochre scale is registered
//     under Mantine's `yellow` slot (`colors.ts` re-tunes the stock names), so
//     `yellow` is what names it.
//
//  2. `variant="filled"` with `autoContrast` on a mid-tone earthy hue. Auto
//     contrast picks black or white text per shade, and sage/dusty-brick sit
//     close enough to the flip point that the *same* control resolved to dark
//     text in one scheme and light text in the other. That is exactly the
//     "contrasts horribly in dark mode" report.
//
//  3. Raw `color="green"` / `color="red"` scattered through the checklist,
//     which meant no single place could be checked or changed.
//
// So: nothing in `features/visits/` names a Mantine colour directly any more.
// Every status resolves through here, and every pairing is `light` — a tinted
// background with same-hue text, which the theme defines for both schemes and
// which does not depend on `autoContrast` at all.
import type { MantineColor } from "@mantine/core";

import type { VisitDefectSeverity, VisitState } from "./types";

/** A colour plus the variant it is legible in. Never one without the other. */
export interface StatusTone {
  color: MantineColor;
  /** `light` everywhere: tinted ground, same-hue text, no autoContrast flip. */
  variant: "light" | "outline";
}

export type VisitStatus =
  /** A check somebody performed and passed. */
  | "pass"
  /** A check somebody performed and failed — and every defect it promotes to. */
  | "problem"
  /** Answered, complete, nothing outstanding. */
  | "complete"
  /** Started but unfinished. */
  | "partial"
  /** Nothing recorded yet. */
  | "empty"
  /** A question the template marks as one you must not leave without. */
  | "critical"
  /** A member's own answer, not the team's. */
  | "personal"
  /** Added by a member rather than shipped in the template. */
  | "custom"
  /** Writes queued locally because the signal went. */
  | "queued";

export const VISIT_STATUS_TONE: Record<VisitStatus, StatusTone> = {
  pass: { color: "green", variant: "light" },
  problem: { color: "red", variant: "light" },
  complete: { color: "green", variant: "light" },
  partial: { color: "yellow", variant: "light" },
  empty: { color: "gray", variant: "light" },
  critical: { color: "yellow", variant: "light" },
  personal: { color: "grape", variant: "light" },
  custom: { color: "teal", variant: "outline" },
  queued: { color: "yellow", variant: "light" },
};

export function toneFor(status: VisitStatus): StatusTone {
  return VISIT_STATUS_TONE[status];
}

/**
 * The severity ramp (VC-10). Four evenly-spaced levels rather than five
 * unlabelled stars: two you would accept and two you would negotiate over.
 *
 * `green → yellow → orange → red` in Mantine's slots, which `colors.ts` has
 * re-tuned to sage → ochre → burnt clay → dusty brick. Each level also carries a
 * word and a distinct glyph, so the ramp survives being read in sunlight or by
 * someone who cannot separate the hues — colour reinforces, it never carries
 * (UI_DESIGN §4).
 */
export const SEVERITY_ORDER: readonly VisitDefectSeverity[] = [
  "noted",
  "minor",
  "major",
  "dealbreaker",
] as const;

export interface SeverityMeta {
  value: VisitDefectSeverity;
  label: string;
  /** What the level means, in the words somebody on a tour would use. */
  help: string;
  color: MantineColor;
}

export const SEVERITY_META: Record<VisitDefectSeverity, SeverityMeta> = {
  noted: {
    value: "noted",
    label: "Noted",
    help: "Doesn't affect day to day, but worth writing down",
    color: "green",
  },
  minor: {
    value: "minor",
    label: "Minor",
    help: "Affects it, but you could live with it",
    color: "yellow",
  },
  major: {
    value: "major",
    label: "Major",
    help: "Costs money or comfort",
    color: "orange",
  },
  dealbreaker: {
    value: "dealbreaker",
    label: "Dealbreaker",
    help: "You would not sign",
    color: "red",
  },
};

/** Mantine palette names, so both schemes stay theme-driven (UI_DESIGN §2). */
export const VISIT_STATE_TONE: Record<VisitState, StatusTone> = {
  planned: { color: "gray", variant: "light" },
  in_progress: { color: "green", variant: "light" },
  completed: { color: "cyan", variant: "light" },
  cancelled: { color: "gray", variant: "outline" },
};
