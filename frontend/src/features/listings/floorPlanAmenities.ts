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
  id: string;
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

const TYPED_MULTI_CRITERIA = new Set(["in_unit_laundry", "parking", "cooling"]);

export interface AmenityCounts {
  confirmed: number;
  advertised: number;
  absent: number;
  unknown: number;
}

/**
 * A Criterion belongs to the scoped unit tranche when its *effective*
 * vocabulary carries `advertised_unconfirmed` — the marker P3-SC4 gave every
 * member of a presence tranche. P3-SC7's controlled-set flooring Criterion is
 * the one approved exception: its applicability, rather than a string sentinel,
 * distinguishes confirmed from advertised evidence.
 */
export function isScopedAmenity(entry: CatalogEntry): boolean {
  // Optional chain, not a formality: a custom Criterion can reach the UI
  // without a `value_schema`, and a hunt's catalog must never crash the
  // drawer over one.
  return (
    Boolean(entry.value_schema?.enum?.includes(ADVERTISED_UNCONFIRMED)) ||
    Boolean(entry.value_schema?.items?.enum?.includes(ADVERTISED_UNCONFIRMED)) ||
    entry.key === "flooring_materials"
  );
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
 * Resolution goes through the shared frontend
 * `activeOverrides`/`extractionForFloorPlan` seam. Flooring's select/unspecified
 * evidence is deliberately displayed as advertised even though scoring treats
 * it as unknown for this concrete Floor Plan.
 */
export function floorPlanAmenities(
  catalog: CatalogEntry[],
  extractions: Extraction[],
  overrides: Override[],
  floorPlanId: string,
): AmenityFact[] {
  const active = activeOverrides(overrides, floorPlanId);
  return catalog.filter(isScopedAmenity).flatMap((entry) => {
    const override = active.get(entry.key);
    if (TYPED_MULTI_CRITERIA.has(entry.key)) {
      if (override) {
        const values = Array.isArray(override.value) ? override.value : [override.value];
        return values.map((value) => ({
          id: `${entry.key}:override:${String(value)}`,
          key: entry.key,
          label: entry.label,
          state: amenityState(value),
          value,
          scope: "overridden",
          extraction: undefined,
          overridden: true,
        }));
      }
      const rows = extractions.filter((row) => row.criterion_key === entry.key);
      const exact = rows.filter(
        (row) => row.target_scope === "floor_plan" && row.floor_plan_id === floorPlanId,
      );
      const all = rows.filter(
        (row) => row.target_scope === "property" && row.applicability === "all_units",
      );
      const exactValues = new Set(
        exact.filter((row) => typeof row.value === "string").map((row) => row.value),
      );
      const allValues = new Set(
        all.filter((row) => typeof row.value === "string").map((row) => row.value),
      );
      if (exactValues.has("none")) {
        const row = exact.find((candidate) => candidate.value === "none");
        return row
          ? [{
              id: `${entry.key}:${row.id}`,
              key: entry.key,
              label: entry.label,
              state: "absent",
              value: "none",
              scope: scopeLabel(row),
              extraction: row,
              overridden: false,
            }]
          : [];
      }
      const confirmedRows = [
        ...exact.filter((row) => typeof row.value === "string" && row.value !== "none"),
        ...all.filter(
          (row) =>
            typeof row.value === "string" &&
            row.value !== "none" &&
            !exactValues.has(row.value),
        ),
      ];
      if (confirmedRows.length === 0 && allValues.has("none")) {
        const row = all.find((candidate) => candidate.value === "none");
        return row
          ? [{
              id: `${entry.key}:${row.id}`,
              key: entry.key,
              label: entry.label,
              state: "absent",
              value: "none",
              scope: scopeLabel(row),
              extraction: row,
              overridden: false,
            }]
          : [];
      }
      const confirmedValues = new Set(confirmedRows.map((row) => row.value));
      const advertisedRows = rows.filter(
        (row) =>
          row.target_scope === "property" &&
          (row.applicability === "select_units" ||
            row.applicability === "unit_scope_unspecified") &&
          typeof row.value === "string" &&
          row.value !== "none" &&
          !confirmedValues.has(row.value),
      );
      const visible = [
        ...confirmedRows.map((row) => ({ row, state: "confirmed" as const })),
        ...advertisedRows.map((row) => ({ row, state: "advertised" as const })),
      ];
      if (visible.length === 0) {
        return [{
          id: `${entry.key}:unknown`,
          key: entry.key,
          label: entry.label,
          state: "unknown",
          value: null,
          scope: null,
          extraction: undefined,
          overridden: false,
        }];
      }
      return visible.map(({ row, state }) => ({
        id: `${entry.key}:${row.id}`,
        key: entry.key,
        label: entry.label,
        state,
        value: row.value,
        scope: scopeLabel(row),
        extraction: row,
        overridden: false,
      }));
    }
    const extraction = extractionForFloorPlan(extractions, entry.key, floorPlanId);
    const value = override ? override.value : (extraction?.value ?? null);
    const flooringAdvertised =
      entry.key === "flooring_materials" &&
      !override &&
      extraction?.target_scope === "property" &&
      (extraction.applicability === "select_units" ||
        extraction.applicability === "unit_scope_unspecified");
    return [{
      id: entry.key,
      key: entry.key,
      label: entry.label,
      state: flooringAdvertised ? "advertised" : amenityState(value),
      value,
      scope: override ? "overridden" : scopeLabel(extraction),
      extraction,
      overridden: Boolean(override),
    }];
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
