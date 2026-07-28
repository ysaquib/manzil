// Scoped unit-amenity presentation for one Floor Plan (§9.3, P3-SC5 detail
// surface). Pure and unit-tested: catalog + resolved Extractions + active
// Overrides in, four presence buckets out.
//
// The four states are P3-SC4's own vocabulary, not a UI invention: a boolean
// exact/all claim composes to `confirmed` or `none`, a select/unspecified
// positive composes to `advertised_unconfirmed`, and Source silence leaves no
// claim at all. All four are rendered, because UI_DESIGN's data-honesty rule
// means a missing chip and a known absence must never look alike.
import type { CatalogEntry } from "../rubric/api";
import { activeOverrides, extractionForFloorPlan } from "./overrides";
import type { Extraction, Override } from "./types";

export const ADVERTISED_UNCONFIRMED = "advertised_unconfirmed";

export type AmenityState = "confirmed" | "advertised" | "absent" | "unknown";

/** Render order, worst-to-best never — confirmed first, unknown last. */
export const AMENITY_STATES: AmenityState[] = ["confirmed", "advertised", "absent", "unknown"];

export interface AmenityFact {
  key: string;
  label: string;
  state: AmenityState;
  /** Effective value — typed for laundry/parking/cooling/heating. */
  value: unknown;
  /** Applicability wording for the chip's scope tag; null when there is none. */
  scope: string | null;
  extraction: Extraction | undefined;
  overridden: boolean;
}

export interface AmenityCounts {
  confirmed: number;
  advertised: number;
  absent: number;
  unknown: number;
}

/**
 * A Criterion belongs to the scoped unit tranche when its *effective*
 * vocabulary carries `advertised_unconfirmed` — the marker P3-SC4 gave every
 * member of the tranche. Deriving membership from the Catalog rather than a
 * hardcoded key list means P3-SC6/SC7 tranches appear here for free.
 */
export function isScopedAmenity(entry: CatalogEntry): boolean {
  // Optional chain, not a formality: a custom Criterion can reach the UI
  // without a `value_schema`, and a hunt's catalog must never crash the
  // drawer over one.
  return Boolean(entry.value_schema?.enum?.includes(ADVERTISED_UNCONFIRMED));
}

/** Effective value → presence bucket. `null`/absent is unknown, never absent. */
export function amenityState(value: unknown): AmenityState {
  if (value === null || value === undefined) return "unknown";
  if (value === ADVERTISED_UNCONFIRMED) return "advertised";
  if (value === "none" || value === false) return "absent";
  return "confirmed";
}

function scopeLabel(extraction: Extraction | undefined): string | null {
  if (!extraction) return null;
  if (extraction.target_scope === "floor_plan") return "this plan";
  if (extraction.applicability === "all_units") return "all units";
  if (extraction.applicability === "select_units") return "select units";
  if (extraction.applicability === "unit_scope_unspecified") return "units unspecified";
  return null;
}

/**
 * Every scoped amenity for one concrete Floor Plan, in Catalog order.
 * Resolution goes through the same `activeOverrides`/`extractionForFloorPlan`
 * seam the breakdown uses, so the modal can never disagree with the score.
 */
export function floorPlanAmenities(
  catalog: CatalogEntry[],
  extractions: Extraction[],
  overrides: Override[],
  floorPlanId: string,
): AmenityFact[] {
  const active = activeOverrides(overrides, floorPlanId);
  return catalog.filter(isScopedAmenity).map((entry) => {
    const extraction = extractionForFloorPlan(extractions, entry.key, floorPlanId);
    const override = active.get(entry.key);
    const value = override ? override.value : (extraction?.value ?? null);
    return {
      key: entry.key,
      label: entry.label,
      state: amenityState(value),
      value,
      scope: override ? "overridden" : scopeLabel(extraction),
      extraction,
      overridden: Boolean(override),
    };
  });
}

export function groupAmenities(facts: AmenityFact[]): Record<AmenityState, AmenityFact[]> {
  const groups: Record<AmenityState, AmenityFact[]> = {
    confirmed: [],
    advertised: [],
    absent: [],
    unknown: [],
  };
  for (const fact of facts) groups[fact.state].push(fact);
  return groups;
}

export function amenityCounts(facts: AmenityFact[]): AmenityCounts {
  const groups = groupAmenities(facts);
  return {
    confirmed: groups.confirmed.length,
    advertised: groups.advertised.length,
    absent: groups.absent.length,
    unknown: groups.unknown.length,
  };
}
