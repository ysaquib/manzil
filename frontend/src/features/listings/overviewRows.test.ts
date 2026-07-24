import { describe, expect, it } from "vitest";

import {
  allInValue,
  applyOverviewFilters,
  buildRows,
  DEFAULT_OVERVIEW_FILTERS,
  filterPills,
  filtersEqual,
  formatRange,
  hasActiveFilters,
  rowAvailability,
  rowComposition,
  sanitizeFilterState,
  sortRows,
} from "./overviewRows";
import type { AllInComponents, FloorPlan, Listing, Score } from "./types";

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
    single_source_reason: null,
    pins: {},
    created_at: "2026-07-08T00:00:00Z",
    unavailable_at,
    all_in_components: null,
    property: {
      id: `${id}-prop`,
      name,
      canonical_address: "1 Main St",
      city: null,
      state: null,
      county: null,
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

// A scored listing whose breakdown carries criterion values (the source the
// criterion filters read); one plan available 2026-08-01.
function makeCriteriaListing(
  id: string,
  criteria: { key: string; value: unknown; unknown?: boolean }[],
  planExtra: Partial<FloorPlan> = {},
): Listing {
  const listing = makeListing(
    id,
    `Prop ${id}`,
    [{ beds: 2, baths: 2, availability_date: "2026-08-01", ...planExtra }],
    { [`${id}-plan-0`]: 8 },
  );
  listing.scores[0].breakdown.criteria = criteria.map((c) => ({
    key: c.key,
    value: c.value,
    matched: null,
    delta: 0,
    unknown: c.unknown,
  }));
  return listing;
}

describe("applyOverviewFilters (criterion + cost + availability-date)", () => {
  const inUnit = makeCriteriaListing("f1", [
    { key: "in_unit_laundry", value: "in_unit" },
    { key: "parking", value: "covered" },
    { key: "dishwasher", value: true },
  ]);
  const onSite = makeCriteriaListing("f2", [
    { key: "in_unit_laundry", value: "on_site" },
    { key: "dishwasher", value: false },
  ], { availability_date: "2026-10-01" });
  const unknownRow = makeCriteriaListing("f3", [
    { key: "in_unit_laundry", value: null, unknown: true },
  ], { availability_date: null });
  const rows = buildRows([inUnit, onSite, unknownRow]);

  it("filters enum criteria and passes unknown values through", () => {
    const filtered = applyOverviewFilters(rows, {
      ...DEFAULT_OVERVIEW_FILTERS,
      laundry: ["in_unit"],
    });
    expect(filtered.map((r) => r.listing.id)).toEqual(["f1", "f3"]); // f3 unknown — passes
  });

  it("filters parking; rows missing the criterion pass", () => {
    const filtered = applyOverviewFilters(rows, {
      ...DEFAULT_OVERVIEW_FILTERS,
      parking: ["garage"],
    });
    expect(filtered.map((r) => r.listing.id)).toEqual(["f2", "f3"]);
  });

  it("filters dishwasher both ways, unknown passing", () => {
    const withDw = applyOverviewFilters(rows, { ...DEFAULT_OVERVIEW_FILTERS, dishwasher: true });
    expect(withDw.map((r) => r.listing.id)).toEqual(["f1", "f3"]);
    const withoutDw = applyOverviewFilters(rows, { ...DEFAULT_OVERVIEW_FILTERS, dishwasher: false });
    expect(withoutDw.map((r) => r.listing.id)).toEqual(["f2", "f3"]);
  });

  it("applies a max all-in ceiling via the composed total, unknown passing", () => {
    const priced = makeCriteriaListing("f4", []);
    priced.scores[0].all_in_components = {
      total: 2400,
      components: [],
      badges: [],
    } as unknown as Score["all_in_components"];
    const filtered = applyOverviewFilters(buildRows([priced, unknownRow]), {
      ...DEFAULT_OVERVIEW_FILTERS,
      maxAllIn: 2000,
    });
    expect(filtered.map((r) => r.listing.id)).toEqual(["f3"]);
  });

  it("passes groups with any plan available on or before the date; unknown dates pass", () => {
    const filtered = applyOverviewFilters(rows, {
      ...DEFAULT_OVERVIEW_FILTERS,
      availableBy: "2026-08-15",
    });
    expect(filtered.map((r) => r.listing.id)).toEqual(["f1", "f3"]); // f2 opens Oct 1
  });
});

describe("sanitizeFilterState / filtersEqual", () => {
  it("drops unknown keys, defaults missing ones, rejects ill-typed values", () => {
    const sanitized = sanitizeFilterState({
      minRent: 900,
      laundry: ["in_unit"],
      bogus: "drop-me",
      maxScore: "twelve",
      dishwasher: true,
    });
    expect(sanitized.minRent).toBe(900);
    expect(sanitized.laundry).toEqual(["in_unit"]);
    expect(sanitized.maxScore).toBeNull();
    expect(sanitized.dishwasher).toBe(true);
    expect("bogus" in sanitized).toBe(false);
    expect(sanitized.cities).toEqual([]);
  });

  it("round-trips defaults and treats array order as irrelevant", () => {
    expect(sanitizeFilterState(null)).toEqual(DEFAULT_OVERVIEW_FILTERS);
    const a = { ...DEFAULT_OVERVIEW_FILTERS, cities: ["Detroit", "Ferndale"] };
    const b = { ...DEFAULT_OVERVIEW_FILTERS, cities: ["Ferndale", "Detroit"] };
    expect(filtersEqual(a, b)).toBe(true);
    expect(filtersEqual(a, { ...b, visited: true })).toBe(false);
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

describe("allInValue / rowComposition (per-plan, P3-9 follow-up)", () => {
  const composition = (rent: number): AllInComponents => ({
    total: rent + 280,
    estimated_total: 280,
    components: [{ name: "rent", amount: rent, tag: "actual" }],
    badges: [],
    mode: "median",
  });

  function withPerPlanComposition(): Listing {
    // Two unit groups with different rents — the 2br is the listing-level
    // display plan; the 1br row must NOT inherit its composition.
    const listing = makeListing(
      "v",
      "The Villas",
      [
        { beds: 1, baths: 1, rent_max: 1069 },
        { beds: 2, baths: 1, rent_max: 1179 },
      ],
      { "v-plan-0": 10.5, "v-plan-1": 11 },
    );
    listing.all_in_components = composition(1179); // listing-level display plan
    listing.scores[0].all_in_components = composition(1069);
    listing.scores[1].all_in_components = composition(1179);
    return listing;
  }

  it("each unit-group row shows its own plan's composition and total", () => {
    const rows = buildRows([withPerPlanComposition()]);
    const oneBed = rows.find((r) => r.group?.beds === 1)!;
    const twoBed = rows.find((r) => r.group?.beds === 2)!;
    expect(allInValue(oneBed)).toBe(1069 + 280);
    expect(allInValue(twoBed)).toBe(1179 + 280);
    expect(rowComposition(oneBed)?.components[0].amount).toBe(1069);
    expect(rowComposition(twoBed)?.components[0].amount).toBe(1179);
  });

  it("falls back to the listing-level composition for pre-column scores", () => {
    const listing = withPerPlanComposition();
    listing.scores[0].all_in_components = null;
    listing.scores[1].all_in_components = null;
    const rows = buildRows([listing]);
    const oneBed = rows.find((r) => r.group?.beds === 1)!;
    expect(rowComposition(oneBed)?.components[0].amount).toBe(1179); // status quo
    expect(allInValue(oneBed)).toBeNull(); // criterion absent from breakdown
  });
});

describe("applyOverviewFilters (free-text query, m1)", () => {
  it("matches property name and address, case-insensitively", () => {
    const byName = applyOverviewFilters(buildRows(listings), {
      ...DEFAULT_OVERVIEW_FILTERS,
      query: "alpha",
    });
    expect(byName.map((r) => r.listing.property.name)).toEqual(["Alpha Court"]);

    const byAddress = applyOverviewFilters(buildRows(listings), {
      ...DEFAULT_OVERVIEW_FILTERS,
      query: "MAIN st",
    });
    expect(byAddress).toHaveLength(3); // every fixture lives at 1 Main St
  });

  it("treats a whitespace-only query as off", () => {
    expect(
      applyOverviewFilters(buildRows(listings), { ...DEFAULT_OVERVIEW_FILTERS, query: "   " }),
    ).toHaveLength(3);
  });

  it("survives sanitize and shows a pill", () => {
    expect(sanitizeFilterState({ query: "alpha" }).query).toBe("alpha");
    expect(sanitizeFilterState({ query: 7 }).query).toBeNull();
    expect(filterPills({ ...DEFAULT_OVERVIEW_FILTERS, query: "alpha" })).toEqual([
      { key: "query", label: "Search: alpha" },
    ]);
  });
});

describe("sortRows (m2 keys)", () => {
  it("sorts by all-in cost with unknowns last", () => {
    const cheap = makeListing("s1", "Cheap", [{ beds: 1, baths: 1 }], { "s1-plan-0": 8 });
    cheap.scores[0].all_in_components = {
      total: 1500, estimated_total: 0, components: [], badges: [], mode: "median",
    };
    const dear = makeListing("s2", "Dear", [{ beds: 1, baths: 1 }], { "s2-plan-0": 9 });
    dear.scores[0].all_in_components = {
      total: 2400, estimated_total: 0, components: [], badges: [], mode: "median",
    };
    const unknown = makeListing("s3", "Unknown", [{ beds: 1, baths: 1 }], { "s3-plan-0": 10 });
    const rows = sortRows(buildRows([dear, unknown, cheap]), { key: "allIn", dir: "asc" });
    expect(rows.map((r) => r.listing.property.name)).toEqual(["Cheap", "Dear", "Unknown"]);
  });

  it("sorts by earliest availability date with dateless rows last", () => {
    const soon = makeListing("a1", "Soon", [{ availability_date: "2026-08-01" }]);
    const later = makeListing("a2", "Later", [
      { availability_date: "2026-09-15" },
      { availability_date: "2026-10-01" },
    ]);
    const never = makeListing("a3", "No Date", [{ beds: 3 }]);
    const rows = sortRows(buildRows([later, never, soon]), { key: "available", dir: "asc" });
    expect(rows.map((r) => r.listing.property.name)).toEqual(["Soon", "Later", "No Date"]);
  });

  it("sorts by recently added", () => {
    const old = makeListing("t1", "Old", [{ beds: 1 }]);
    old.created_at = "2026-07-01T00:00:00Z";
    const fresh = makeListing("t2", "Fresh", [{ beds: 1 }]);
    fresh.created_at = "2026-07-18T00:00:00Z";
    const rows = sortRows(buildRows([old, fresh]), { key: "added", dir: "desc" });
    expect(rows.map((r) => r.listing.property.name)).toEqual(["Fresh", "Old"]);
  });
});
