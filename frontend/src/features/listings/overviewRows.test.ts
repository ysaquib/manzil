import { describe, expect, it } from "vitest";

import { buildRows, filterRows, formatRange, sortRows } from "./overviewRows";
import type { FloorPlan, Listing, Score } from "./types";

function makeListing(
  id: string,
  name: string,
  plans: Partial<FloorPlan>[],
  totals: Record<string, number> = {},
): Listing {
  const floorPlans = plans.map(
    (p, i): FloorPlan => ({
      id: `${id}-plan-${i}`,
      property_id: `${id}-prop`,
      source_id: "src",
      plan_name: `Plan ${i}`,
      beds: 2,
      baths: 2,
      sqft_min: null,
      sqft_max: null,
      rent_min: null,
      rent_max: null,
      deposit: null,
      availability_date: null,
      available_units: null,
      ...p,
    }),
  );
  const scores = Object.entries(totals).map(
    ([planId, total]): Score => ({
      hunt_listing_id: id,
      floor_plan_id: planId,
      total,
      breakdown: { base: 10, total, rubric_version: 1, clamped: false, gates: [], criteria: [] },
      rubric_version: 1,
      computed_at: "2026-07-08T00:00:00Z",
    }),
  );
  return {
    id,
    hunt_id: "hunt-1",
    property_id: `${id}-prop`,
    added_by: "user-1",
    status: "active",
    source_policy: "tiers_1_2_3",
    pins: {},
    created_at: "2026-07-08T00:00:00Z",
    property: {
      id: `${id}-prop`,
      name,
      canonical_address: "1 Main St",
      official_url: null,
      floor_plans: floorPlans,
      sources: [],
    },
    scores,
  };
}

const listings = [
  makeListing("l1", "Beta Flats", [{ beds: 2, baths: 2, rent_min: 2000 }], { "l1-plan-0": 11 }),
  makeListing("l2", "Alpha Court", [{ beds: 1, baths: 1, rent_min: 1500 }], { "l2-plan-0": 4 }),
  makeListing("l3", "Gamma Lofts", [{ beds: 2, baths: 1, rent_min: 1800 }]),
];

describe("buildRows", () => {
  it("emits one row per unit group per listing", () => {
    const both = makeListing("l4", "Two Groups", [
      { beds: 1, baths: 1 },
      { beds: 2, baths: 2 },
    ]);
    expect(buildRows([both])).toHaveLength(2);
    expect(buildRows(listings)).toHaveLength(3);
  });
});

describe("filterRows (hide score < N)", () => {
  it("hides rows scoring under the threshold but keeps unscored rows", () => {
    const rows = filterRows(buildRows(listings), 5);
    const names = rows.map((r) => r.listing.property.name);
    expect(names).toContain("Beta Flats"); // 11 ≥ 5
    expect(names).not.toContain("Alpha Court"); // 4 < 5 — hidden
    expect(names).toContain("Gamma Lofts"); // unscored — pending, not a verdict
  });

  it("is a no-op when off", () => {
    expect(filterRows(buildRows(listings), null)).toHaveLength(3);
  });
});

describe("sortRows", () => {
  it("sorts by score desc with unknowns last", () => {
    const rows = sortRows(buildRows(listings), { key: "score", dir: "desc" });
    expect(rows.map((r) => r.listing.property.name)).toEqual([
      "Beta Flats",
      "Alpha Court",
      "Gamma Lofts",
    ]);
  });

  it("keeps unknowns last when ascending too", () => {
    const rows = sortRows(buildRows(listings), { key: "score", dir: "asc" });
    expect(rows.map((r) => r.listing.property.name)).toEqual([
      "Alpha Court",
      "Beta Flats",
      "Gamma Lofts",
    ]);
  });

  it("sorts by name", () => {
    const rows = sortRows(buildRows(listings), { key: "name", dir: "asc" });
    expect(rows[0].listing.property.name).toBe("Alpha Court");
  });
});

describe("formatRange", () => {
  it("renders ranges, single values, and unknowns", () => {
    expect(formatRange(1800, 2100, "$")).toBe("$1,800–$2,100");
    expect(formatRange(1800, 1800, "$")).toBe("$1,800");
    expect(formatRange(null, 950)).toBe("950");
    expect(formatRange(null, null)).toBe("—");
  });
});
