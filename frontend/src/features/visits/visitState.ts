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
 */
export function visitState(visit: {
  started_at: string | null;
  ended_at: string | null;
  cancelled_at: string | null;
}): VisitState {
  if (visit.cancelled_at) return "cancelled";
  if (visit.ended_at) return "completed";
  if (visit.started_at) return "in_progress";
  return "planned";
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
