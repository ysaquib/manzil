import { describe, expect, it } from "vitest";

import type { FloorPlan, Listing, Score } from "./types";
import { deriveUnitGroups, resolveRow, resolveRowWithDraft } from "./unitGroups";

function plan(overrides: Partial<FloorPlan> & { id: string }): FloorPlan {
  return {
    property_id: "prop-1",
    source_id: "src-1",
    plan_name: overrides.id,
    beds: 2,
    baths: 2,
    sqft_min: null,
    sqft_max: null,
    rent_min: null,
    rent_max: null,
    deposit: null,
    availability_date: null,
    available_units: null,
    ...overrides,
  };
}

function score(floorPlanId: string, total: number): Score {
  return {
    hunt_listing_id: "listing-1",
    floor_plan_id: floorPlanId,
    total,
    breakdown: {
      base: 10,
      total,
      rubric_version: 1,
      clamped: false,
      gates: [],
      criteria: [],
    },
    rubric_version: 1,
    computed_at: "2026-07-08T00:00:00Z",
  };
}

function listing(plans: FloorPlan[], scores: Score[], pins: Record<string, string> = {}): Listing {
  return {
    id: "listing-1",
    hunt_id: "hunt-1",
    property_id: "prop-1",
    added_by: "user-1",
    status: "active",
    source_policy: "tiers_1_2_3",
    single_source_reason: null,
    pins,
    created_at: "2026-07-08T00:00:00Z",
    unavailable_at: null,
    all_in_components: null,
    property: {
      id: "prop-1",
      name: "The Test Flats",
      canonical_address: "1 Main St",
      city: null,
      official_url: null,
      floor_plans: plans,
      sources: [],
    },
    scores,
  };
}

describe("deriveUnitGroups", () => {
  it("groups plans by (beds, baths) and sorts larger units first", () => {
    const rows = deriveUnitGroups(
      listing(
        [
          plan({ id: "a", beds: 1, baths: 1 }),
          plan({ id: "b", beds: 2, baths: 2 }),
          plan({ id: "c", beds: 2, baths: 2 }),
        ],
        [],
      ),
    );
    expect(rows.map((r) => r.key)).toEqual(["2-2", "1-1"]);
    expect(rows[0].plans).toHaveLength(2);
  });

  it("unions Floor Plan unit types without implying every plan shares them", () => {
    const rows = deriveUnitGroups(
      listing(
        [
          plan({ id: "a", unit_types: ["apartment", "loft"] }),
          plan({ id: "b", unit_types: ["apartment", "townhome"] }),
        ],
        [],
      ),
    );
    expect(rows[0].unitTypes).toEqual(["apartment", "loft", "townhome"]);
    expect(rows[0].plans[0].unit_types).toEqual(["apartment", "loft"]);
  });

  it("excludes retired Source-local Floor Plans", () => {
    const rows = deriveUnitGroups(
      listing(
        [
          plan({ id: "current", is_current: true }),
          plan({ id: "retired", is_current: false }),
        ],
        [score("current", 9), score("retired", 12)],
      ),
    );
    expect(rows[0].plans.map((candidate) => candidate.id)).toEqual(["current"]);
    expect(rows[0].displayPlan.id).toBe("current");
  });

  it("displays the best score of the group, never naked (§9.4)", () => {
    const rows = deriveUnitGroups(
      listing(
        [plan({ id: "a" }), plan({ id: "b" }), plan({ id: "c" })],
        [score("a", 8), score("b", 11.5)],
      ),
    );
    expect(rows[0].displayScore?.total).toBe(11.5);
    expect(rows[0].displayPlan.id).toBe("b");
    expect(rows[0].scoredPlanCount).toBe(2);
    expect(rows[0].pinnedPlanId).toBeNull();
  });

  it("a per-group pin switches the display plan and score", () => {
    const rows = deriveUnitGroups(
      listing(
        [plan({ id: "a" }), plan({ id: "b" })],
        [score("a", 8), score("b", 11.5)],
        { "2-2": "a" },
      ),
    );
    expect(rows[0].displayPlan.id).toBe("a");
    expect(rows[0].displayScore?.total).toBe(8);
    expect(rows[0].pinnedPlanId).toBe("a");
  });

  it("ignores a pin pointing at a plan no longer in the group", () => {
    const rows = deriveUnitGroups(
      listing([plan({ id: "a" })], [score("a", 9)], { "2-2": "gone" }),
    );
    expect(rows[0].displayPlan.id).toBe("a");
    expect(rows[0].pinnedPlanId).toBeNull();
  });

  it("computes rent and sqft ranges across the group, tolerating nulls", () => {
    const rows = deriveUnitGroups(
      listing(
        [
          plan({ id: "a", rent_min: 1800, rent_max: 1900, sqft_min: 900, sqft_max: 950 }),
          plan({ id: "b", rent_min: null, rent_max: 2100, sqft_min: null, sqft_max: null }),
        ],
        [],
      ),
    );
    expect(rows[0].rentMin).toBe(1800);
    expect(rows[0].rentMax).toBe(2100);
    expect(rows[0].sqftMin).toBe(900);
    expect(rows[0].sqftMax).toBe(950);
  });

  it("leaves ranges null when nothing is known", () => {
    const rows = deriveUnitGroups(listing([plan({ id: "a" })], []));
    expect(rows[0].rentMin).toBeNull();
    expect(rows[0].displayScore).toBeNull();
    expect(rows[0].scoredPlanCount).toBe(0);
  });
});

describe("resolveRow", () => {
  it("reflects updated pins on the live listing", () => {
    const plans = [plan({ id: "a" }), plan({ id: "b" })];
    const scores = [score("a", 8), score("b", 11.5)];
    const before = listing(plans, scores);
    const after = listing(plans, scores, { "2-2": "a" });

    const unresolved = resolveRow([before], "listing-1", "2-2");
    expect(unresolved.group?.pinnedPlanId).toBeNull();
    expect(unresolved.group?.displayPlan.id).toBe("b");

    const resolved = resolveRow([after], "listing-1", "2-2");
    expect(resolved.group?.pinnedPlanId).toBe("a");
    expect(resolved.group?.displayPlan.id).toBe("a");
    expect(resolved.group?.displayScore?.total).toBe(8);
  });

  it("returns null listing when the row no longer exists", () => {
    const rows = resolveRow([], "listing-1", "2-2");
    expect(rows).toEqual({ listing: null, group: null });
  });

  it("returns listing with null group when groupKey is null", () => {
    const l = listing([plan({ id: "a" })], []);
    const rows = resolveRow([l], "listing-1", null);
    expect(rows.listing?.id).toBe("listing-1");
    expect(rows.group).toBeNull();
  });
});

describe("resolveRowWithDraft", () => {
  it("returns updated pinnedPlanId from draft pins without server round-trip", () => {
    const plans = [plan({ id: "a" }), plan({ id: "b" })];
    const scores = [score("a", 8), score("b", 11.5)];
    const listingFixture = listing(plans, scores);

    const { group: serverGroup } = resolveRow([listingFixture], "listing-1", "2-2");
    expect(serverGroup?.pinnedPlanId).toBeNull();
    expect(serverGroup?.displayPlan.id).toBe("b");

    const draftPins = { "2-2": "a" };
    const { group: draftGroup } = resolveRowWithDraft(
      [listingFixture],
      "listing-1",
      "2-2",
      draftPins,
    );
    expect(draftGroup?.pinnedPlanId).toBe("a");
    expect(draftGroup?.displayPlan.id).toBe("a");
    expect(draftGroup?.displayScore?.total).toBe(8);
  });
});
