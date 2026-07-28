// Override resolution (§9.6, §20 2026-07-18). Pure and unit-tested.
// Overrides are append-only; the LATEST row per criterion wins, and a null
// value is the revert tombstone — "no longer overridden", falling back to the
// extraction. Mirrors the worker's _resolve_effective_values semantics.
import type { Extraction, Override } from "./types";

export const REVERT_NOTE = "Reverted to original";
// P3-SC4's migrated tranche: legacy Property rows carrying no applicability
// never participate in presence composition for these keys, so the fallback
// below must skip them. `heating` follows the same applicability path per
// Floor Plan (IMPLEMENTATION §P3-SC4) and had been missing from this set.
const SCOPED_UNIT_CRITERIA = new Set([
  "patio_balcony",
  "private_entry",
  "in_unit_laundry",
  "parking",
  "cooling",
  "dishwasher",
  "heating",
]);

/** Latest non-tombstone override per criterion key. `overrides` must be
 * newest-first, which is how useOverrides orders them. */
export function activeOverrides(
  overrides: Override[],
  floorPlanId: string | null = null,
): Map<string, Override> {
  const active = new Map<string, Override>();
  const keys = new Set(overrides.map((override) => override.criterion_key));
  for (const key of keys) {
    const rows = overrides.filter((override) => override.criterion_key === key);
    const selected = [
      rows.find((row) => row.target_scope === "floor_plan" && row.floor_plan_id === floorPlanId),
      rows.find((row) => row.target_scope === "property" && row.applicability === "all_units"),
      SCOPED_UNIT_CRITERIA.has(key)
        ? undefined
        : rows.find((row) => row.target_scope === "property" && row.applicability === null),
    ].find((row) => row !== undefined && row.value !== null);
    if (selected) active.set(key, selected);
  }
  return active;
}

export function extractionForFloorPlan(
  extractions: Extraction[],
  criterionKey: string,
  floorPlanId: string | null,
): Extraction | undefined {
  const rows = extractions.filter((row) => row.criterion_key === criterionKey);
  const legacyPropertyFact = SCOPED_UNIT_CRITERIA.has(criterionKey)
    ? undefined
    : rows.find((row) => row.target_scope === "property" && row.applicability === null);
  return (
    rows.find((row) => row.target_scope === "floor_plan" && row.floor_plan_id === floorPlanId) ??
    rows.find((row) => row.target_scope === "property" && row.applicability === "all_units") ??
    legacyPropertyFact ??
    rows.find((row) => row.target_scope === "property" && row.applicability === "select_units") ??
    rows.find(
      (row) => row.target_scope === "property" && row.applicability === "unit_scope_unspecified",
    )
  );
}
