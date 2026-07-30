import { describe, expect, it } from "vitest";

import {
  amenityCounts,
  amenityState,
  floorPlanAmenities,
  groupAmenities,
  isScopedAmenity,
} from "../src/features/listings/floorPlanAmenities";
import type { Extraction, Override } from "../src/features/listings/types";
import type { CatalogEntry } from "../src/features/rubric/api";

function entry(key: string, label: string, enumValues?: string[]): CatalogEntry {
  return {
    key,
    label,
    category: "unit",
    domain: "rent",
    fact_scope: "floor_plan",
    value_schema: enumValues ? { type: "string", enum: enumValues } : { type: "integer" },
    default_options: [],
    extraction_hint: "",
    requires_tool: null,
    refresh_class: "static",
  };
}

const PRESENCE = ["confirmed", "advertised_unconfirmed", "none"];
const LAUNDRY = ["in_unit", "hookups", "on_site", "none", "advertised_unconfirmed"];

const catalog: CatalogEntry[] = [
  entry("patio_balcony", "Patio or balcony", PRESENCE),
  entry("in_unit_laundry", "In-unit laundry", LAUNDRY),
  entry("dishwasher", "Dishwasher", PRESENCE),
  entry("private_entry", "Private entry", PRESENCE),
  {
    ...entry("flooring_materials", "Flooring materials"),
    fact_scope: "mixed",
    value_schema: {
      type: "array",
      items: { type: "string", enum: ["carpet", "hardwood", "tile"] },
      minItems: 1,
      uniqueItems: true,
    },
  },
  entry("sqft", "Square footage"), // not a scoped presence criterion
];

function extraction(over: Partial<Extraction>): Extraction {
  return {
    id: `ex-${over.criterion_key}-${over.floor_plan_id ?? "prop"}`,
    property_id: "prop-1",
    hunt_id: null,
    criterion_key: "patio_balcony",
    record_kind: "resolved",
    origin_key: "page:1",
    target_scope: "floor_plan",
    floor_plan_id: "plan-a",
    applicability: null,
    claim_group_id: "cg-1",
    value: "confirmed",
    confidence: "high",
    evidence_quote: null,
    source_id: "src-1",
    model: "gemini-3-flash-preview",
    resolution_rule: null,
    disputed: false,
    extracted_at: "2026-07-26T18:02:00Z",
    ...over,
  };
}

describe("isScopedAmenity", () => {
  it("selects criteria whose effective vocabulary carries advertised_unconfirmed", () => {
    expect(catalog.filter(isScopedAmenity).map((c) => c.key)).toEqual([
      "patio_balcony",
      "in_unit_laundry",
      "dishwasher",
      "private_entry",
      "flooring_materials",
    ]);
  });

  it("excludes criteria that are not part of the scoped tranche", () => {
    expect(isScopedAmenity(entry("sqft", "Square footage"))).toBe(false);
  });
});

describe("amenityState", () => {
  it("maps the P3-SC4 vocabulary onto the four presence buckets", () => {
    expect(amenityState("confirmed")).toBe("confirmed");
    expect(amenityState("in_unit")).toBe("confirmed");
    expect(amenityState(true)).toBe("confirmed");
    expect(amenityState("advertised_unconfirmed")).toBe("advertised");
    expect(amenityState("none")).toBe("absent");
    expect(amenityState(false)).toBe("absent");
  });

  it("treats no claim as unknown, never as an absence", () => {
    expect(amenityState(null)).toBe("unknown");
    expect(amenityState(undefined)).toBe("unknown");
  });
});

describe("floorPlanAmenities", () => {
  it("shows confirmed and advertised typed values as separate scoped facts", () => {
    const parking: CatalogEntry = {
      ...entry("parking", "Parking"),
      fact_scope: "mixed",
      value_schema: {
        type: "array",
        items: {
          type: "string",
          enum: ["garage", "carport", "none", "advertised_unconfirmed"],
        },
        minItems: 1,
        uniqueItems: true,
      },
    };
    const facts = floorPlanAmenities(
      [parking],
      [
        extraction({
          id: "parking-carport",
          criterion_key: "parking",
          target_scope: "property",
          floor_plan_id: null,
          applicability: "all_units",
          claim_variant: "carport",
          value: "carport",
        }),
        extraction({
          id: "parking-garage",
          criterion_key: "parking",
          target_scope: "property",
          floor_plan_id: null,
          applicability: "select_units",
          claim_variant: "garage",
          value: "garage",
        }),
      ],
      [],
      "plan-a",
    );

    expect(facts).toHaveLength(2);
    expect(facts).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: "parking",
          value: "carport",
          state: "confirmed",
          scope: "all units",
        }),
        expect.objectContaining({
          key: "parking",
          value: "garage",
          state: "advertised",
          scope: "select units",
        }),
      ]),
    );
  });

  it("resolves each criterion for the given plan and labels its applicability", () => {
    const extractions: Extraction[] = [
      extraction({ criterion_key: "patio_balcony", value: "confirmed" }),
      extraction({
        criterion_key: "in_unit_laundry",
        target_scope: "property",
        floor_plan_id: null,
        applicability: "select_units",
        value: "advertised_unconfirmed",
      }),
      extraction({ criterion_key: "private_entry", value: "none" }),
      // dishwasher: no claim at all → unknown
    ];

    const facts = floorPlanAmenities(catalog, extractions, [], "plan-a");
    const byKey = new Map(facts.map((fact) => [fact.key, fact]));

    expect(facts).toHaveLength(5);
    expect(byKey.get("patio_balcony")).toMatchObject({ state: "confirmed", scope: "this plan" });
    expect(byKey.get("in_unit_laundry")).toMatchObject({
      state: "advertised",
      scope: "select units",
    });
    expect(byKey.get("private_entry")).toMatchObject({ state: "absent" });
    expect(byKey.get("dishwasher")).toMatchObject({ state: "unknown", scope: null });
  });

  it("shows uncertain flooring materials as advertised evidence, not confirmed", () => {
    const facts = floorPlanAmenities(
      catalog,
      [
        extraction({
          criterion_key: "flooring_materials",
          target_scope: "property",
          floor_plan_id: null,
          applicability: "select_units",
          value: ["hardwood", "tile"],
        }),
      ],
      [],
      "plan-a",
    );
    expect(facts.find((fact) => fact.key === "flooring_materials")).toMatchObject({
      state: "advertised",
      value: ["hardwood", "tile"],
      scope: "select units",
    });
  });

  it("does not leak another plan's exact claim onto this plan", () => {
    const extractions = [
      extraction({ criterion_key: "patio_balcony", floor_plan_id: "plan-b", value: "confirmed" }),
    ];
    const facts = floorPlanAmenities(catalog, extractions, [], "plan-a");
    expect(facts.find((fact) => fact.key === "patio_balcony")?.state).toBe("unknown");
  });

  it("lets an Override win and marks the fact as human-entered", () => {
    const extractions = [extraction({ criterion_key: "dishwasher", value: "none" })];
    const overrides: Override[] = [
      {
        id: "ov-1",
        hunt_listing_id: "listing-1",
        criterion_key: "dishwasher",
        target_scope: "floor_plan",
        floor_plan_id: "plan-a",
        applicability: null,
        value: "confirmed",
        user_id: "user-1",
        note: null,
        created_at: "2026-07-27T00:00:00Z",
      },
    ];
    const fact = floorPlanAmenities(catalog, extractions, overrides, "plan-a").find(
      (row) => row.key === "dishwasher",
    );
    expect(fact).toMatchObject({ state: "confirmed", overridden: true, scope: "overridden" });
  });
});

describe("groupAmenities / amenityCounts", () => {
  it("buckets and counts every state, including empty ones", () => {
    const facts = floorPlanAmenities(
      catalog,
      [extraction({ criterion_key: "patio_balcony", value: "confirmed" })],
      [],
      "plan-a",
    );
    expect(groupAmenities(facts).confirmed.map((f) => f.key)).toEqual(["patio_balcony"]);
    expect(amenityCounts(facts)).toEqual({
      confirmed: 1,
      advertised: 0,
      absent: 0,
      unknown: 4,
    });
  });
});
