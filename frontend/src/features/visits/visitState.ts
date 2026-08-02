// Visit state and template grouping — pure, unit-tested (DESIGN §9.7).
//
// State is *derived* from timestamps on both sides of the wire: the API computes
// it for its responses, and this module computes it for the direct-Supabase
// reads the list uses. There is no status column to read, so this is the only
// definition of "in progress" the frontend has.
import { unitGroupKey, unitGroupLabel } from "../listings/unitGroups";
import type { Visit, VisitState, VisitTemplateItem, VisitUnit } from "./types";

export const VISIT_STATES = ["planned", "in_progress", "completed", "cancelled"] as const;

/**
 * Cancellation outranks everything: a tour that started and was then called off
 * is cancelled, not in progress. Ordering here is the whole rule.
 *
 * A reopen later than the end puts the tour back in progress (VC-9). It does
 * this *without* clearing `ended_at`, which is why the comparison is between
 * two timestamps rather than a null check: ending a reopened tour stamps a new,
 * later `ended_at` and lands back on completed, leaving the reopen stamp where
 * it is as the record that somebody came back to it.
 */
export function visitState(visit: {
  started_at: string | null;
  ended_at: string | null;
  reopened_at?: string | null;
  cancelled_at: string | null;
}): VisitState {
  if (visit.cancelled_at) return "cancelled";
  if (visit.ended_at && !isReopened(visit)) return "completed";
  if (visit.started_at) return "in_progress";
  return "planned";
}

/** True when the latest reopen is more recent than the latest end. */
export function isReopened(visit: {
  ended_at: string | null;
  reopened_at?: string | null;
}): boolean {
  if (!visit.reopened_at || !visit.ended_at) return false;
  return new Date(visit.reopened_at).getTime() > new Date(visit.ended_at).getTime();
}

export const VISIT_STATE_LABEL: Record<VisitState, string> = {
  planned: "Planned",
  in_progress: "In progress",
  completed: "Completed",
  cancelled: "Cancelled",
};

/** Mantine palette names, so both schemes stay theme-driven (`UI_DESIGN` §2). */
export const VISIT_STATE_COLOR: Record<VisitState, string> = {
  planned: "gray",
  in_progress: "green",
  completed: "cyan",
  cancelled: "gray",
};

export function countByState(visits: Visit[]): Record<VisitState | "all", number> {
  const counts = {
    all: visits.length,
    planned: 0,
    in_progress: 0,
    completed: 0,
    cancelled: 0,
  };
  for (const visit of visits) counts[visitState(visit)] += 1;
  return counts;
}

export function filterByState(visits: Visit[], state: VisitState | "all"): Visit[] {
  return state === "all" ? visits : visits.filter((visit) => visitState(visit) === state);
}

/**
 * What a Visit Unit is, for display. A unit with no Floor Plan was never
 * advertised — say so rather than implying the listing described it.
 */
export function unitDescriptor(
  unit: Pick<VisitUnit, "beds" | "baths" | "floor_plan_id">,
  planName?: string | null,
): string {
  const group = unitGroupLabel(unit.beds, unit.baths);
  if (unit.floor_plan_id && planName) return `${planName} · ${group}`;
  if (unit.floor_plan_id) return group;
  return `${group} · not advertised`;
}

/** True when this unit matches no Floor Plan the listing advertises. */
export function isCustomUnit(unit: Pick<VisitUnit, "floor_plan_id">): boolean {
  return unit.floor_plan_id === null;
}

export function unitGroupKeysFor(units: Pick<VisitUnit, "beds" | "baths">[]): string[] {
  return [...new Set(units.map((unit) => unitGroupKey(unit.beds, unit.baths)))];
}

// ---------------------------------------------------------------------------
// Template grouping
// ---------------------------------------------------------------------------

export type Tier = "quick" | "standard" | "thorough";

const TIER_RANK: Record<Tier, number> = { quick: 0, standard: 1, thorough: 2 };

/** The depth dial is cumulative: Standard includes Quick, Thorough includes both. */
export function itemInTier(itemTier: Tier, active: Tier): boolean {
  return TIER_RANK[itemTier] <= TIER_RANK[active];
}

export interface TemplateSection<T extends VisitTemplateItem = VisitTemplateItem> {
  key: string;
  items: T[];
  /** A section is unit-scoped when any item in it is; mixed sections carry both. */
  hasUnitScoped: boolean;
  hasPropertyScoped: boolean;
}

/**
 * Group template items into sections in `display_order`.
 *
 * `display_order` is globally monotonic and a section occupies one contiguous
 * run (asserted by the API-side template test), which is why there is no
 * sections table to read — order and grouping both fall out of the items.
 */
export function groupIntoSections<T extends VisitTemplateItem>(
  items: T[],
  tier: Tier = "thorough",
): TemplateSection<T>[] {
  const visible = items
    .filter((item) => itemInTier(item.tier, tier))
    .sort((a, b) => a.display_order - b.display_order);

  const sections: TemplateSection<T>[] = [];
  for (const item of visible) {
    let section = sections.at(-1);
    if (!section || section.key !== item.section_key) {
      section = {
        key: item.section_key,
        items: [],
        hasUnitScoped: false,
        hasPropertyScoped: false,
      };
      sections.push(section);
    }
    section.items.push(item);
    if (item.scope === "unit") section.hasUnitScoped = true;
    else section.hasPropertyScoped = true;
  }
  return sections;
}

/**
 * Before a tour starts, only the property-scoped prep section is answerable —
 * a "planned" Visit has no units walked yet, so unit-scoped items would be
 * asking about rooms nobody has seen (DESIGN §9.7).
 */
export function sectionsOpenBeforeStart<T extends VisitTemplateItem>(
  sections: TemplateSection<T>[],
): TemplateSection<T>[] {
  return sections.filter((section) => section.key === "prep");
}

/** Human-readable section titles. Frontend copy: DESIGN §8.2 has no sections table. */
export const SECTION_TITLE: Record<string, string> = {
  essentials: "Essentials",
  sweep: "The ten-minute sweep",
  prep: "Before you go",
  kitchen: "Kitchen",
  bathrooms: "Bathrooms",
  bedrooms: "Bedrooms & closets",
  living: "Living areas, light & windows",
  laundry: "Laundry",
  systems: "HVAC, plumbing & electrical",
  noise: "Noise & privacy",
  space: "Measurements & storage",
  safety: "Safety & security",
  building: "Building, parking & amenities",
  pets: "Pets",
  red_flags: "Red flags",
  money: "Money",
  lease: "Lease, renewal & exit",
  application: "Application & screening",
  history: "Building history & operations",
  followup: "After the tour",
  verdict_unit: "Verdict — this unit",
  verdict_property: "Verdict — the building",
};

export function sectionTitle(key: string): string {
  return SECTION_TITLE[key] ?? key.replace(/_/g, " ");
}

// ---------------------------------------------------------------------------
// Phases (VC-13)
// ---------------------------------------------------------------------------

/**
 * Twenty-one sections never fitted in a row, and the horizontal strip they were
 * rendered as turned every section change into a scrub past everything else.
 * They roll up into five **phases**, which do fit — and which are the shape of
 * the afternoon rather than an arbitrary split: what you do on the couch, what
 * you do walking around, what you ask the person with the keys, the money
 * conversation, and what you decide afterwards.
 *
 * The phase bar is the only permanent navigation. The full list stays reachable
 * through the section picker, which is a list you open deliberately rather than
 * a strip in the way of the thing under it.
 */
export interface VisitPhase {
  key: string;
  title: string;
  /** Section keys in template order. A section belongs to exactly one phase. */
  sections: string[];
}

export const VISIT_PHASES: VisitPhase[] = [
  { key: "before", title: "Before", sections: ["prep"] },
  {
    key: "walk",
    title: "Walk it",
    sections: [
      "essentials",
      "sweep",
      "kitchen",
      "bathrooms",
      "bedrooms",
      "living",
      "laundry",
      "systems",
      "noise",
      "space",
      "safety",
      "building",
      "pets",
      "red_flags",
    ],
  },
  { key: "ask", title: "Ask", sections: ["lease", "application", "history"] },
  { key: "money", title: "Money", sections: ["money"] },
  {
    key: "wrap",
    title: "Wrap up",
    sections: ["followup", "verdict_unit", "verdict_property"],
  },
];

/** Which phase a section belongs to. Unknown sections fall into Walk it. */
export function phaseForSection(sectionKey: string): VisitPhase {
  return (
    VISIT_PHASES.find((phase) => phase.sections.includes(sectionKey)) ??
    VISIT_PHASES.find((phase) => phase.key === "walk")!
  );
}

/**
 * Phases carrying at least one of the sections actually present, in phase order.
 * A tier or a restriction can empty a phase — a bar item that navigates nowhere
 * is worse than one fewer item.
 */
export function phasesPresent<T extends { key: string }>(
  sections: T[],
): { phase: VisitPhase; sections: T[] }[] {
  const byKey = new Map(sections.map((section) => [section.key, section]));
  return VISIT_PHASES.map((phase) => ({
    phase,
    sections: phase.sections
      .map((key) => byKey.get(key))
      .filter((section): section is T => section !== undefined),
  })).filter((group) => group.sections.length > 0);
}

/**
 * Section keys in template order, flattened across phases. This is what
 * previous/next walks — and it is derived from the sections actually shown, so
 * changing the depth dial changes where "next" goes.
 */
export function sectionOrder<T extends { key: string }>(sections: T[]): string[] {
  return phasesPresent(sections).flatMap((group) => group.sections.map((s) => s.key));
}

/** The section before and after `current`, or null at either end. */
export function neighbours<T extends { key: string }>(
  sections: T[],
  current: string | null,
): { previous: string | null; next: string | null } {
  const order = sectionOrder(sections);
  const index = current ? order.indexOf(current) : -1;
  if (index === -1) return { previous: null, next: null };
  return {
    previous: index > 0 ? order[index - 1] : null,
    next: index < order.length - 1 ? order[index + 1] : null,
  };
}
