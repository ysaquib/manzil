import { describe, expect, it } from "vitest";

import {
  applyOverviewFilters,
  buildRows,
  DEFAULT_OVERVIEW_FILTERS,
  filterPills,
  formatRange,
  hasActiveFilters,
  rowAvailability,
  sortRows,
} from "./overviewRows";
import type { FloorPlan, Listing, Score } from "./types";

function makeListing(
  id: string,
  name: string,
  plans: Partial<FloorPlan>[],
  totals: Record<string, number> = {},
  unavailable_at: string | null = null,
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
    unavailable_at,
    property: {
      id: `${id}-prop`,
      name,
      canonical_address: "1 Main St",
      city: null,
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

  it("emits one listing-level row for a listing with no floor plans", () => {
    const noPlans = makeListing("l5", "Empty", []);
    const rows = buildRows([noPlans]);
    expect(rows).toHaveLength(1);
    expect(rows[0].group).toBeNull();
  });

  it("classifies a plan-less listing as unavailable vs pending by unavailable_at", () => {
    const unavailable = makeListing("l6", "Full Building", [], {}, "2026-07-09T00:00:00Z");
    const pending = makeListing("l7", "Still Ingesting", []);
    expect(rowAvailability(buildRows([unavailable])[0])).toBe("unavailable");
    expect(rowAvailability(buildRows([pending])[0])).toBe("pending");
  });
});

describe("applyOverviewFilters (hide score < N)", () => {
  it("hides rows scoring under the threshold but keeps unscored rows", () => {
    const rows = applyOverviewFilters(buildRows(listings), { ...DEFAULT_OVERVIEW_FILTERS, minScore: 5 });
    const names = rows.map((r) => r.listing.property.name);
    expect(names).toContain("Beta Flats"); // 11 ≥ 5
    expect(names).not.toContain("Alpha Court"); // 4 < 5 — hidden
    expect(names).toContain("Gamma Lofts"); // unscored — pending, not a verdict
  });

  it("is a no-op when off", () => {
    expect(applyOverviewFilters(buildRows(listings), DEFAULT_OVERVIEW_FILTERS)).toHaveLength(3);
  });
});

describe("applyOverviewFilters (curation and locality)", () => {
  it("attaches Unit Group state and composes city/status/visited filters", () => {
    const listing = makeListing(
      "c1",
      "City Place",
      [{ beds: 2, baths: 2 }],
      { "c1-plan-0": 9 },
    );
    listing.property.city = "Detroit";
    const rows = buildRows([listing], [{
      hunt_listing_id: "c1",
      unit_group_key: "2-2",
      interest_status: "interested",
      visited: true,
      updated_by: "u1",
      updated_at: "2026-07-15T00:00:00Z",
    }]);
    expect(rows[0].state?.interest_status).toBe("interested");
    expect(applyOverviewFilters(rows, {
      ...DEFAULT_OVERVIEW_FILTERS,
      cities: ["Detroit"],
      statuses: ["interested"],
      visited: true,
    })).toHaveLength(1);
    expect(applyOverviewFilters(rows, {
      ...DEFAULT_OVERVIEW_FILTERS,
      visited: false,
    })).toHaveLength(0);
  });

  it("applies an inclusive score ceiling", () => {
    const rows = buildRows(listings);
    expect(applyOverviewFilters(rows, {
      ...DEFAULT_OVERVIEW_FILTERS,
      maxScore: 4,
    }).map((row) => row.listing.id)).toEqual(["l2", "l3"]);
  });
});

describe("applyOverviewFilters (rent)", () => {
  const rentListings = [
    makeListing("r1", "Cheap", [{ rent_min: 1200, rent_max: 1400 }], { "r1-plan-0": 8 }),
    makeListing("r2", "Mid", [{ rent_min: 1800, rent_max: 2000 }], { "r2-plan-0": 8 }),
    makeListing("r3", "Priceless", [{ rent_min: null, rent_max: null }], { "r3-plan-0": 8 }),
    makeListing("r4", "Pending", []),
  ];

  it("filters by max rent with overlap semantics", () => {
    const rows = applyOverviewFilters(buildRows(rentListings), {
      ...DEFAULT_OVERVIEW_FILTERS,
      maxRent: 1500,
    });
    const names = rows.map((r) => r.listing.property.name);
    expect(names).toContain("Cheap");
    expect(names).not.toContain("Mid");
    expect(names).toContain("Priceless"); // no rent data — unknown, not a verdict
    expect(names).toContain("Pending"); // group null — always passes
  });

  it("filters by min rent", () => {
    const rows = applyOverviewFilters(buildRows(rentListings), {
      ...DEFAULT_OVERVIEW_FILTERS,
      minRent: 1700,
    });
    const names = rows.map((r) => r.listing.property.name);
    expect(names).not.toContain("Cheap");
    expect(names).toContain("Mid");
  });
});

describe("applyOverviewFilters (sqft)", () => {
  const sqftListings = [
    makeListing("s1", "Small", [{ sqft_min: 600, sqft_max: 700 }], { "s1-plan-0": 8 }),
    makeListing("s2", "Large", [{ sqft_min: 900, sqft_max: 1100 }], { "s2-plan-0": 8 }),
  ];

  it("filters by sqft range overlap", () => {
    const rows = applyOverviewFilters(buildRows(sqftListings), {
      ...DEFAULT_OVERVIEW_FILTERS,
      minSqft: 800,
    });
    const names = rows.map((r) => r.listing.property.name);
    expect(names).not.toContain("Small");
    expect(names).toContain("Large");
  });
});

describe("applyOverviewFilters (beds)", () => {
  const bedListings = [
    makeListing("b0", "Studio", [{ beds: 0, baths: 1 }], { "b0-plan-0": 8 }),
    makeListing("b1", "One Bed", [{ beds: 1, baths: 1 }], { "b1-plan-0": 8 }),
    makeListing("b2", "Two Bed", [{ beds: 2, baths: 2 }], { "b2-plan-0": 8 }),
    makeListing("b3", "Pending", []),
  ];

  it("filters by min and max beds; pending rows stay visible", () => {
    const rows = applyOverviewFilters(buildRows(bedListings), {
      ...DEFAULT_OVERVIEW_FILTERS,
      minBeds: 1,
      maxBeds: 1,
    });
    const names = rows.map((r) => r.listing.property.name);
    expect(names).not.toContain("Studio");
    expect(names).toContain("One Bed");
    expect(names).not.toContain("Two Bed");
    expect(names).toContain("Pending");
  });
});

describe("applyOverviewFilters (baths)", () => {
  const bathListings = [
    makeListing("ba1", "One Bath", [{ beds: 1, baths: 1 }], { "ba1-plan-0": 8 }),
    makeListing("ba15", "One-and-half", [{ beds: 1, baths: 1.5 }], { "ba15-plan-0": 8 }),
    makeListing("ba2", "Two Bath", [{ beds: 2, baths: 2 }], { "ba2-plan-0": 8 }),
    makeListing("baP", "Pending", []),
  ];

  it("filters by half-step bath bounds; pending rows stay visible", () => {
    const rows = applyOverviewFilters(buildRows(bathListings), {
      ...DEFAULT_OVERVIEW_FILTERS,
      minBaths: 1.5,
      maxBaths: 1.5,
    });
    const names = rows.map((r) => r.listing.property.name);
    expect(names).not.toContain("One Bath");
    expect(names).toContain("One-and-half");
    expect(names).not.toContain("Two Bath");
    expect(names).toContain("Pending");
  });
});

describe("filterPills and hasActiveFilters", () => {
  it("reports active filters", () => {
    expect(hasActiveFilters(DEFAULT_OVERVIEW_FILTERS)).toBe(false);
    const active = {
      ...DEFAULT_OVERVIEW_FILTERS,
      minScore: 5,
      maxRent: 2000,
      minBeds: 2,
      maxBaths: 1.5,
    };
    expect(hasActiveFilters(active)).toBe(true);
    const pills = filterPills(active);
    expect(pills).toHaveLength(4);
    expect(pills[0].label).toBe("Score ≥ 5");
    expect(pills[1].label).toBe("Rent ≤ $2,000");
    expect(pills[2].label).toBe("Beds ≥ 2");
    expect(pills[3].label).toBe("Baths ≤ 1.5");
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

  it("sinks plan-less rows (null score, not 0) below a negatively-scored row", () => {
    const withNeg = [
      makeListing("neg", "Negative", [{ beds: 2, baths: 2 }], { "neg-plan-0": -3 }),
      makeListing("none", "No Availability", [], {}, "2026-07-09T00:00:00Z"),
    ];
    const rows = sortRows(buildRows(withNeg), { key: "score", dir: "desc" });
    expect(rows.map((r) => r.listing.property.name)).toEqual(["Negative", "No Availability"]);
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
